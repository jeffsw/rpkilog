import bz2
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rpkilog import rpkiclient_uploader
from rpkilog.snapshot_summary_file import SnapshotSummaryFile

TEST_DATA_DIR = Path(__file__).parent.parent.parent.parent / 'test_data'
GOLDEN_SUMMARY = TEST_DATA_DIR / 'rpkiclient_summary_20250720T100145Z.json.bz2'
GOLDEN_DT = datetime(2025, 7, 20, 10, 1, 45, tzinfo=timezone.utc)
GOLDEN_KEY = '20250720T100145Z.json.bz2'


def _write_sample_json(path: Path, buildtime: str = '2025-07-20T10:01:45Z') -> dict:
    sample_data = {'metadata': {'buildtime': buildtime}, 'roas': []}
    with open(path, 'wt') as fh:
        json.dump(sample_data, fh)
    return sample_data


# --- Unit tests (no disk I/O beyond tmp_path, no S3) ---

def test_filename_matches_legacy_format():
    # legacy uploader derived the key as dt.strftime('%Y%m%dT%H%M%SZ.json.bz2')
    ssf = SnapshotSummaryFile(datetimestamp=GOLDEN_DT, local_storage_dir=Path('/tmp'))
    legacy = GOLDEN_DT.strftime('%Y%m%dT%H%M%SZ.json.bz2')
    assert ssf.default_filename + '.bz2' == legacy
    assert ssf.default_filename + '.bz2' == GOLDEN_KEY


def test_datetimestamp_from_json_matches_legacy():
    json_data = {'metadata': {'buildtime': '2025-07-20T10:01:45Z'}}
    dt = SnapshotSummaryFile.datetimestamp_from_json(json_data)
    assert dt == GOLDEN_DT


def test_s3_upload_skips_when_object_exists(tmp_path, monkeypatch):
    source = tmp_path / 'json'
    _write_sample_json(source)
    monkeypatch.setattr(SnapshotSummaryFile, 's3_exists', lambda self: True)
    result = rpkiclient_uploader.s3_upload(rpkiclient_json=source, s3_bucket_name='example-bucket')
    assert result is None
    assert source.exists()


def test_s3_upload_preserves_source_file(tmp_path, monkeypatch):
    source = tmp_path / 'json'
    _write_sample_json(source)

    class _FakeS3Object:
        key = GOLDEN_KEY

    monkeypatch.setattr(SnapshotSummaryFile, 's3_exists', lambda self: False)
    # skip the real size gate; the sample file is far below MINIMUM_SIZE
    monkeypatch.setattr(SnapshotSummaryFile, 'validate_size', lambda self: None)
    monkeypatch.setattr(SnapshotSummaryFile, 's3_upload', lambda self: _FakeS3Object())
    result = rpkiclient_uploader.s3_upload(rpkiclient_json=source, s3_bucket_name='example-bucket')
    assert result == GOLDEN_KEY
    # CLEANUP_NEVER must leave rpki-client's live source file in place
    assert source.exists()


# --- S3 tests (require live AWS credentials) ---

@pytest.mark.slow
def test_s3_upload_end_to_end(tmp_path, s3_test_bucket):
    # decompress the golden summary into an uncompressed source file, mimicking output/json
    source = tmp_path / 'json'
    with bz2.open(GOLDEN_SUMMARY, 'rb') as src_fh:
        with open(source, 'wb') as dst_fh:
            shutil.copyfileobj(src_fh, dst_fh, length=1024 * 1024)

    # the key derives from the JSON's metadata.buildtime, which differs from the filename's
    # timestamp in the golden data, so compute it the same way the uploader does
    with open(source, 'rt') as fh:
        json_data = json.load(fh)
    expected_dt = SnapshotSummaryFile.datetimestamp_from_json(json_data)
    expected_key = expected_dt.strftime('%Y%m%dT%H%M%SZ.json.bz2')

    # ensure a clean slate so s3_exists() doesn't short-circuit the upload
    s3_test_bucket.Object(expected_key).delete()
    try:
        result = rpkiclient_uploader.s3_upload(
            rpkiclient_json=source,
            s3_bucket_name=s3_test_bucket.name,
        )
        assert result == expected_key
        # object landed in S3 (load() raises if it does not exist)
        s3_test_bucket.Object(expected_key).load()
        # the local source copy is preserved (CLEANUP_NEVER)
        assert source.exists()
    finally:
        s3_test_bucket.Object(expected_key).delete()

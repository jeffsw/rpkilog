import bz2
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rpkilog.local_storage_type import LocalStorageType
from rpkilog.snapshot_summary_file import SnapshotSummaryFile

TEST_DATA_DIR = Path(__file__).parent.parent.parent.parent / 'test_data'
GOLDEN_SUMMARY = TEST_DATA_DIR / 'rpkiclient_summary_20250720T100145Z.json.bz2'
GOLDEN_DT = datetime(2025, 7, 20, 10, 1, 45, tzinfo=timezone.utc)


# --- Unit tests (no disk I/O, no S3) ---

def test_filename_generation():
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT, local_storage_dir=Path('/tmp'))
    assert f.default_filename == '20250720T100145Z.json'


def test_local_filepath_bz2_appends_extension():
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT, local_storage_dir=Path('/tmp'))
    assert str(f.local_filepath_bz2).endswith('.json.bz2')
    assert not str(f.local_filepath_bz2).endswith('.json.bz2.bz2')


def test_local_filepath_uncompressed_no_bz2_suffix():
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT, local_storage_dir=Path('/tmp'))
    assert str(f.local_filepath_uncompressed).endswith('.json')
    assert not str(f.local_filepath_uncompressed).endswith('.bz2')


def test_infer_datetimestamp_from_path_plain():
    p = Path('20250720T100145Z.json')
    dt = SnapshotSummaryFile.infer_datetimestamp_from_path(p)
    assert dt == GOLDEN_DT


def test_infer_datetimestamp_from_path_bz2():
    p = Path('20250720T100145Z.json.bz2')
    dt = SnapshotSummaryFile.infer_datetimestamp_from_path(p)
    assert dt == GOLDEN_DT


def test_infer_datetimestamp_rejects_diff_filename():
    p = Path('20250720T100145Z.vrpdiff.json.bz2')
    with pytest.raises(ValueError):
        SnapshotSummaryFile.infer_datetimestamp_from_path(p)


# --- File I/O unit tests (tmp_path only, no golden data) ---

def test_write_json_roundtrip(tmp_path):
    sample_data = {'metadata': {'buildtime': '2025-07-20T10:01:45Z'}, 'roas': []}
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT, local_storage_dir=tmp_path)
    f.write_json(sample_data)
    assert f.local_storage_type == LocalStorageType.UNCOMPRESSED
    assert f.local_filepath_uncompressed.exists()
    with f.open_for_read() as fh:
        loaded = json.load(fh)
    assert loaded == sample_data


def test_bzip2_compress_changes_state(tmp_path):
    sample_data = {'metadata': {'buildtime': '2025-07-20T10:01:45Z'}, 'roas': []}
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT, local_storage_dir=tmp_path)
    f.write_json(sample_data)
    f.bzip2_compress()
    assert f.local_storage_type == LocalStorageType.BZIP2
    assert f.local_filepath_bz2.exists()
    assert not f.local_filepath_uncompressed.exists()


# --- Golden data tests (read test_data/ only, no S3) ---

@pytest.mark.slow
def test_infer_local_storage_type_bz2():
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT)
    f.infer_local_storage_type(GOLDEN_SUMMARY)
    assert f.local_storage_type == LocalStorageType.BZIP2


@pytest.mark.slow
def test_datetimestamp_from_json():
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT)
    f.infer_local_storage_type(GOLDEN_SUMMARY)
    data = f.json_data_cache
    dt = SnapshotSummaryFile.datetimestamp_from_json(data)
    assert dt.year == GOLDEN_DT.year
    assert dt.month == GOLDEN_DT.month
    assert dt.day == GOLDEN_DT.day


@pytest.mark.slow
def test_json_data_cache_loads():
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT)
    f.infer_local_storage_type(GOLDEN_SUMMARY)
    data = f.json_data_cache
    assert 'metadata' in data
    assert 'roas' in data


@pytest.mark.slow
def test_validate_size_passes():
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT)
    f.infer_local_storage_type(GOLDEN_SUMMARY)
    f.validate_size()


@pytest.mark.slow
def test_write_to_path(tmp_path):
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT)
    f.infer_local_storage_type(GOLDEN_SUMMARY)
    dest = tmp_path / 'out.json.bz2'
    f.write_to_path(dest)
    assert dest.exists()
    with bz2.open(dest, 'rb') as fh:
        data = json.load(fh)
    assert 'roas' in data


# --- S3 tests (require live AWS credentials) ---

@pytest.mark.slow
def test_s3_roundtrip(tmp_path, s3_test_bucket):
    # Copy golden file so s3_upload()'s cleanup_upon_destroy won't touch test_data/
    local_copy = tmp_path / GOLDEN_SUMMARY.name
    shutil.copy2(GOLDEN_SUMMARY, local_copy)
    test_key = f'test_snapshot_summary_file/{GOLDEN_SUMMARY.name}'
    s3_url = f's3://{s3_test_bucket.name}/{test_key}'

    f = SnapshotSummaryFile(
        datetimestamp=GOLDEN_DT,
        local_filepath_bz2=local_copy,
        local_storage_type=LocalStorageType.BZIP2,
        s3_url=s3_url,
    )
    try:
        f.s3_upload()
        assert f.s3_exists()

        download_path = tmp_path / 'downloaded.json.bz2'
        f2 = SnapshotSummaryFile(
            datetimestamp=GOLDEN_DT,
            local_filepath_bz2=download_path,
            local_storage_type=LocalStorageType.UNCACHED,
            s3_url=s3_url,
        )
        f2.s3_download()
        assert download_path.exists()
        with bz2.open(download_path, 'rb') as fh:
            data = json.load(fh)
        assert 'metadata' in data
        assert 'buildtime' in data['metadata']
    finally:
        s3_test_bucket.Object(test_key).delete()

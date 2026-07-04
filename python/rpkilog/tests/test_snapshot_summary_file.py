import bz2
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from rpkilog.cleanup_policy import CleanupPolicy
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


def test_from_s3_object_summary():
    obj = SimpleNamespace(
        bucket_name='example-bucket',
        key='prefix/20250720T100145Z.json.bz2',
        last_modified=datetime(2025, 7, 20, 10, 2, 0, tzinfo=timezone.utc),
    )
    f = SnapshotSummaryFile.from_s3_object_summary(obj)
    assert f.datetimestamp == GOLDEN_DT
    assert f.s3_url == 's3://example-bucket/prefix/20250720T100145Z.json.bz2'
    assert f.s3_stored is True
    assert f.local_storage_type == LocalStorageType.UNCACHED
    assert f.s3_last_modified == obj.last_modified


def test_datetimestamp_from_json_naive_buildtime_becomes_utc():
    # buildtime with no timezone indicator must come back tz-aware in UTC
    json_data = {'metadata': {'buildtime': '2025-07-20 10:01:45'}}
    dt = SnapshotSummaryFile.datetimestamp_from_json(json_data)
    assert dt.tzinfo == timezone.utc
    assert dt == GOLDEN_DT


def test_datetimestamp_from_json_offset_buildtime_converted_to_utc():
    # buildtime carrying a non-UTC offset must be converted to UTC, not relabeled
    json_data = {'metadata': {'buildtime': '2025-07-20T12:01:45+02:00'}}
    dt = SnapshotSummaryFile.datetimestamp_from_json(json_data)
    assert dt.tzinfo == timezone.utc
    assert dt == GOLDEN_DT


# --- s3_url derivation unit tests (no network) ---

def test_s3_url_derived_from_base_url_when_unset(monkeypatch):
    # isolate the process-global base-url classvar (auto-restored on teardown)
    monkeypatch.setattr(SnapshotSummaryFile, '_default_s3_base_url', None, raising=False)
    SnapshotSummaryFile.default_s3_base_url_set('s3://example-bucket/prefix/')
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT)
    # resolving derives the URL from base + filename; s3_path/s3_bucket then read the stored URL
    f._ensure_s3_url()
    assert f.s3_url == 's3://example-bucket/prefix/20250720T100145Z.json.bz2'
    assert f.s3_bucket == 'example-bucket'
    assert f.s3_path == 'prefix/20250720T100145Z.json.bz2'


def test_explicit_s3_url_not_overridden_by_base_url(monkeypatch):
    # A known URL (e.g. a future SQL-loaded record) must win over the class base URL.
    monkeypatch.setattr(SnapshotSummaryFile, '_default_s3_base_url', None, raising=False)
    SnapshotSummaryFile.default_s3_base_url_set('s3://example-bucket/prefix/')
    explicit = 's3://other-bucket/known/object.json.bz2'
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT, s3_url=explicit)
    f._ensure_s3_url()  # must be a no-op when a URL is already known
    assert f.s3_url == explicit
    assert f.s3_bucket == 'other-bucket'
    assert f.s3_path == 'known/object.json.bz2'


def test_s3_url_rejects_non_s3_scheme():
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT)
    with pytest.raises(ValueError):
        f.s3_url = 'https://example-bucket/object.json.bz2'


def test_default_s3_base_url_set_rejects_non_s3_scheme(monkeypatch):
    monkeypatch.setattr(SnapshotSummaryFile, '_default_s3_base_url', None, raising=False)
    with pytest.raises(ValueError):
        SnapshotSummaryFile.default_s3_base_url_set('https://example-bucket/')


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


def test_observation_datetime_and_buildmachine_read_from_json(tmp_path):
    # buildtime deliberately differs from the filename-derived datetimestamp: observation_datetime
    # must reflect the JSON metadata, never the filename
    sample_data = {
        'metadata': {'buildtime': '2025-07-20T10:01:43Z', 'buildmachine': 'josephine'},
        'roas': [],
    }
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT, local_storage_dir=tmp_path)
    f.write_json(sample_data)
    assert f.observation_datetime == datetime(2025, 7, 20, 10, 1, 43, tzinfo=timezone.utc)
    assert f.observation_datetime != f.datetimestamp
    assert f.buildmachine == 'josephine'


def test_bzip2_compress_changes_state(tmp_path):
    sample_data = {'metadata': {'buildtime': '2025-07-20T10:01:45Z'}, 'roas': []}
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT, local_storage_dir=tmp_path)
    f.write_json(sample_data)
    f.bzip2_compress()
    assert f.local_storage_type == LocalStorageType.BZIP2
    assert f.local_filepath_bz2.exists()
    assert not f.local_filepath_uncompressed.exists()


def test_context_manager_cleans_up_when_flagged(tmp_path):
    sample_data = {'metadata': {'buildtime': '2025-07-20T10:01:45Z'}, 'roas': []}
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT, local_storage_dir=tmp_path)
    with f as cm:
        assert cm is f
        f.write_json(sample_data)
        f.cleanup_policy = CleanupPolicy.CLEANUP_ALWAYS
        local_path = f.local_filepath_uncompressed
        assert local_path.exists()
    assert not local_path.exists()
    assert f.local_storage_type == LocalStorageType.UNCACHED


def test_context_manager_keeps_file_when_not_flagged(tmp_path):
    sample_data = {'metadata': {'buildtime': '2025-07-20T10:01:45Z'}, 'roas': []}
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT, local_storage_dir=tmp_path)
    with f:
        f.write_json(sample_data)
        local_path = f.local_filepath_uncompressed
        assert local_path.exists()
    assert local_path.exists()
    assert f.local_storage_type == LocalStorageType.UNCOMPRESSED


def test_context_manager_does_not_suppress_exceptions(tmp_path):
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT, local_storage_dir=tmp_path)
    f.cleanup_policy = CleanupPolicy.CLEANUP_ALWAYS
    with pytest.raises(ValueError):
        with f:
            raise ValueError('boom')


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
def test_observation_datetime_golden_differs_from_filename():
    # the golden file's internal buildtime (100143Z) is two seconds earlier than its filename
    # timestamp (100145Z); observation_datetime must report the buildtime
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT)
    f.infer_local_storage_type(GOLDEN_SUMMARY)
    assert f.observation_datetime == datetime(2025, 7, 20, 10, 1, 43, tzinfo=timezone.utc)
    assert f.buildmachine == 'josephine'


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
def test_s3_roundtrip(tmp_path, s3_test_bucket, s3_base_url_factory):
    # Copy golden file so s3_upload()'s post-upload cleanup won't touch test_data/
    local_copy = tmp_path / GOLDEN_SUMMARY.name
    shutil.copy2(GOLDEN_SUMMARY, local_copy)
    # Point the class at a run-unique base URL; the object derives its key from base + filename.
    s3_base_url_factory(SnapshotSummaryFile, 'test_snapshot_summary_file')

    f = SnapshotSummaryFile(
        datetimestamp=GOLDEN_DT,
        local_filepath_bz2=local_copy,
        local_storage_type=LocalStorageType.BZIP2,
    )
    test_key = None
    try:
        f.s3_upload()
        assert f.s3_exists()
        test_key = f.s3_path

        download_path = tmp_path / 'downloaded.json.bz2'
        f2 = SnapshotSummaryFile(
            datetimestamp=GOLDEN_DT,
            local_filepath_bz2=download_path,
            local_storage_type=LocalStorageType.UNCACHED,
            s3_url=f.s3_url,
        )
        f2.s3_download()
        assert download_path.exists()
        with bz2.open(download_path, 'rb') as fh:
            data = json.load(fh)
        assert 'metadata' in data
        assert 'buildtime' in data['metadata']
    finally:
        if test_key is not None:
            s3_test_bucket.Object(test_key).delete()

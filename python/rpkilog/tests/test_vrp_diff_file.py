import bz2
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rpkilog.local_storage_type import LocalStorageType
from rpkilog.vrp_diff_file import VrpDiffFile

TEST_DATA_DIR = Path(__file__).parent.parent.parent.parent / 'test_data'
GOLDEN_DIFF = TEST_DATA_DIR / 'rpkiclient_vrpdiff_20250720T100145Z.json.bz2'
GOLDEN_DT = datetime(2025, 7, 20, 10, 1, 45, tzinfo=timezone.utc)


# --- Unit tests (no disk I/O, no S3) ---

def test_filename_generation():
    f = VrpDiffFile(datetimestamp=GOLDEN_DT, local_storage_dir=Path('/tmp'))
    assert f.default_filename == '20250720T100145Z.vrpdiff.json'


def test_local_filepath_bz2_appends_extension():
    f = VrpDiffFile(datetimestamp=GOLDEN_DT, local_storage_dir=Path('/tmp'))
    assert str(f.local_filepath_bz2).endswith('.vrpdiff.json.bz2')


def test_local_filepath_uncompressed_no_bz2_suffix():
    f = VrpDiffFile(datetimestamp=GOLDEN_DT, local_storage_dir=Path('/tmp'))
    assert str(f.local_filepath_uncompressed).endswith('.vrpdiff.json')
    assert not str(f.local_filepath_uncompressed).endswith('.bz2')


def test_infer_datetimestamp_from_path_bz2():
    p = Path('20250720T100145Z.vrpdiff.json.bz2')
    dt = VrpDiffFile.infer_datetimestamp_from_path(p)
    assert dt == GOLDEN_DT


def test_infer_datetimestamp_from_path_plain():
    p = Path('20250720T100145Z.vrpdiff.json')
    dt = VrpDiffFile.infer_datetimestamp_from_path(p)
    assert dt == GOLDEN_DT


def test_infer_datetimestamp_rejects_summary_filename():
    p = Path('20250720T100145Z.json.bz2')
    with pytest.raises(ValueError):
        VrpDiffFile.infer_datetimestamp_from_path(p)


def test_from_summary_filename_bz2():
    f = VrpDiffFile.from_summary_filename('20250720T100145Z.json.bz2', local_storage_dir=Path('/tmp'))
    assert f.datetimestamp == GOLDEN_DT


def test_from_summary_filename_plain():
    f = VrpDiffFile.from_summary_filename('20250720T100145Z.json', local_storage_dir=Path('/tmp'))
    assert f.datetimestamp == GOLDEN_DT


def test_from_summary_filename_rejects_diff_filename():
    with pytest.raises(ValueError):
        VrpDiffFile.from_summary_filename('20250720T100145Z.vrpdiff.json.bz2')


# --- Golden data tests (read test_data/ only, no S3) ---

@pytest.mark.slow
def test_infer_local_storage_type_bz2():
    f = VrpDiffFile(datetimestamp=GOLDEN_DT)
    f.infer_local_storage_type(GOLDEN_DIFF)
    assert f.local_storage_type == LocalStorageType.BZIP2


@pytest.mark.slow
def test_json_data_cache_loads():
    f = VrpDiffFile(datetimestamp=GOLDEN_DT)
    f.infer_local_storage_type(GOLDEN_DIFF)
    data = f.json_data_cache
    assert 'metadata' in data
    assert 'vrp_diffs' in data


@pytest.mark.slow
def test_write_to_path(tmp_path):
    f = VrpDiffFile(datetimestamp=GOLDEN_DT)
    f.infer_local_storage_type(GOLDEN_DIFF)
    dest = tmp_path / 'out.vrpdiff.json.bz2'
    f.write_to_path(dest)
    assert dest.exists()
    with bz2.open(dest, 'rb') as fh:
        data = json.load(fh)
    assert 'vrp_diffs' in data


# --- S3 tests (require live AWS credentials) ---

@pytest.mark.slow
def test_s3_roundtrip(tmp_path, s3_test_bucket):
    # Copy golden file so s3_upload()'s cleanup_upon_destroy won't touch test_data/
    local_copy = tmp_path / GOLDEN_DIFF.name
    shutil.copy2(GOLDEN_DIFF, local_copy)
    test_key = f'test_vrp_diff_file/{GOLDEN_DIFF.name}'
    s3_url = f's3://{s3_test_bucket.name}/{test_key}'

    f = VrpDiffFile(
        datetimestamp=GOLDEN_DT,
        local_filepath_bz2=local_copy,
        local_storage_type=LocalStorageType.BZIP2,
        s3_url=s3_url,
    )
    try:
        f.s3_upload()
        assert f.s3_exists()

        download_path = tmp_path / 'downloaded.vrpdiff.json.bz2'
        f2 = VrpDiffFile(
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
        assert 'diff_count' in data['metadata']
    finally:
        s3_test_bucket.Object(test_key).delete()

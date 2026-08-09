import io
import json
import tarfile
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fake_db import FakeDb

from rpkilog.cleanup_policy import CleanupPolicy
from rpkilog.data_file_source import DataFileSource
from rpkilog.local_storage_type import LocalStorageType
from rpkilog.snapshot_file import SnapshotFile
from rpkilog.snapshot_summary_file import SnapshotSummaryFile

GOLDEN_DT = datetime(2021, 11, 21, 0, 7, 9, tzinfo=timezone.utc)
GOLDEN_NAME = 'rpki-20211121T000709Z.tgz'

TEST_DATA_DIR = Path(__file__).parent.parent.parent.parent / 'test_data'
# Golden snapshot TAR (large): internal member is rpki-20260111T194523Z/output/rpki-client.json
GOLDEN_SNAPSHOT_TGZ = TEST_DATA_DIR / 'rpkiclient_snapshot_20260111T194523Z.tgz'
GOLDEN_SNAPSHOT_DT = datetime(2026, 1, 11, 19, 45, 23, tzinfo=timezone.utc)

# The golden snapshot TAR is too large to commit to git, so it exists only on developer machines.
# Tests that read it skip cleanly where it is absent (e.g. GitHub CI).  The synthetic-tar tests above
# cover the same code paths without it.
skipif_no_golden_snapshot = pytest.mark.skipif(
    not GOLDEN_SNAPSHOT_TGZ.exists(),
    reason='large snapshot TAR fixture not committed to git; present only locally',
)


def _make_tgz(path, members):
    """Write a gzipped tar at path containing {member_name: bytes} entries."""
    with tarfile.open(path, 'w:gz') as tf:
        for member_name, payload in members.items():
            info = tarfile.TarInfo(member_name)
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))


def _summary_member_name(dt=GOLDEN_DT):
    return f'rpki-{dt.strftime("%Y%m%dT%H%M%SZ")}/output/rpki-client.json'


# --- Unit tests: filename / path derivation (no disk I/O, no S3) ---

def test_filename_generation():
    f = SnapshotFile(datetimestamp=GOLDEN_DT, local_storage_dir=Path('/tmp'))
    assert f.default_filename == GOLDEN_NAME


def test_local_filepath_tgz():
    f = SnapshotFile(datetimestamp=GOLDEN_DT, local_storage_dir=Path('/tmp'))
    assert str(f.local_filepath_tgz) == f'/tmp/{GOLDEN_NAME}'


def test_json_form_path_properties_raise():
    f = SnapshotFile(datetimestamp=GOLDEN_DT, local_storage_dir=Path('/tmp'))
    with pytest.raises(TypeError):
        _ = f.local_filepath_uncompressed
    with pytest.raises(TypeError):
        _ = f.local_filepath_bz2


def test_repr_does_not_raise():
    # repr_attrs drops the raising JSON-path properties; __repr__ must stay usable in error messages.
    f = SnapshotFile(datetimestamp=GOLDEN_DT, local_storage_dir=Path('/tmp'))
    rendered = repr(f)
    assert 'SnapshotFile(' in rendered
    assert 'local_filepath_tgz' in rendered


# --- Unit tests: parsers ---

def test_infer_datetimestamp_from_path():
    assert SnapshotFile.infer_datetimestamp_from_path(Path(GOLDEN_NAME)) == GOLDEN_DT


def test_infer_datetimestamp_rejects_summary_filename():
    with pytest.raises(ValueError):
        SnapshotFile.infer_datetimestamp_from_path(Path('20211121T000709Z.json.bz2'))


def test_infer_datetimestamp_rejects_vrpdiff_filename():
    with pytest.raises(ValueError):
        SnapshotFile.infer_datetimestamp_from_path(Path('20211121T000709Z.vrpdiff.json.bz2'))


def test_source_url_is_stored_as_provenance():
    # SnapshotFile records source_url but never fetches it; the crawler sets it on construction.
    url = f'https://example.com/2021/11/21/{GOLDEN_NAME}'
    f = SnapshotFile(datetimestamp=GOLDEN_DT, source_url=url, local_storage_dir=Path('/tmp'))
    assert f.source_url == url


# --- Unit tests: default S3 key derivation (no network) ---

def test_s3_url_set_to_default_has_no_bz2_suffix(monkeypatch):
    # isolate the process-global base-url classvar (auto-restored on teardown)
    monkeypatch.setattr(SnapshotFile, '_default_s3_base_url', None, raising=False)
    SnapshotFile.default_s3_base_url_set('s3://example-bucket/prefix/')
    f = SnapshotFile(datetimestamp=GOLDEN_DT)
    url = f.s3_url_set_to_default()
    assert url == f's3://example-bucket/prefix/{GOLDEN_NAME}'
    assert not url.endswith('.bz2')
    assert f.s3_path == f'prefix/{GOLDEN_NAME}'


# --- Unit tests: JSON-only operations are invalid on a snapshot TAR ---

def test_json_only_operations_raise():
    f = SnapshotFile(datetimestamp=GOLDEN_DT, local_storage_dir=Path('/tmp'))
    with pytest.raises(TypeError):
        _ = f.json_data_cache
    with pytest.raises(TypeError):
        f.write_json({'roas': []})
    with pytest.raises(TypeError):
        f.bzip2_compress()
    with pytest.raises(TypeError):
        f.infer_local_storage_type(Path('/tmp/x'))
    with pytest.raises(TypeError):
        f.open_for_read()


# --- Unit tests: local-cache handling (tmp_path only) ---

def test_unlink_cached_removes_tgz(tmp_path):
    p = tmp_path / GOLDEN_NAME
    p.write_bytes(b'fake-tgz')
    f = SnapshotFile(
        datetimestamp=GOLDEN_DT,
        local_filepath_tgz=p,
        local_storage_type=LocalStorageType.SNAPSHOT_TGZ,
        cleanup_policy=CleanupPolicy.CLEANUP_NEVER,
    )
    f.unlink_cached()
    assert not p.exists()
    assert f.local_storage_type == LocalStorageType.UNCACHED


def test_context_manager_cleans_up_tgz(tmp_path):
    p = tmp_path / GOLDEN_NAME
    p.write_bytes(b'fake-tgz')
    f = SnapshotFile(
        datetimestamp=GOLDEN_DT,
        local_filepath_tgz=p,
        local_storage_type=LocalStorageType.SNAPSHOT_TGZ,
        cleanup_policy=CleanupPolicy.CLEANUP_ALWAYS,
    )
    with f:
        assert p.exists()
    assert not p.exists()
    assert f.local_storage_type == LocalStorageType.UNCACHED


def test_write_to_path_copies_local_tgz(tmp_path):
    p = tmp_path / GOLDEN_NAME
    p.write_bytes(b'hello-tgz')
    f = SnapshotFile(
        datetimestamp=GOLDEN_DT,
        local_filepath_tgz=p,
        local_storage_type=LocalStorageType.SNAPSHOT_TGZ,
        cleanup_policy=CleanupPolicy.CLEANUP_NEVER,
    )
    dest = tmp_path / 'out.tgz'
    f.write_to_path(dest)
    assert dest.read_bytes() == b'hello-tgz'


def test_cleanup_raises_on_unhandled_state(tmp_path):
    # SnapshotFile._cleanup_local_cache rejects a JSON storage state it should never carry.
    f = SnapshotFile(
        datetimestamp=GOLDEN_DT,
        local_storage_dir=tmp_path,
        local_storage_type=LocalStorageType.BZIP2,
        cleanup_policy=CleanupPolicy.CLEANUP_NEVER,
    )
    with pytest.raises(ValueError):
        f._cleanup_local_cache()


def test_base_cleanup_safety_net_raises(tmp_path):
    # DataFileSuper._cleanup_local_cache now raises on an unhandled storage state (e.g. a base
    # subclass that has not been taught about SNAPSHOT_TGZ).  s3_stored is False so the destructor's
    # CLEANUP_IF_IN_S3 policy will not re-invoke cleanup during GC.
    from rpkilog.snapshot_summary_file import SnapshotSummaryFile
    f = SnapshotSummaryFile(datetimestamp=GOLDEN_DT, local_storage_dir=tmp_path)
    f.local_storage_type = LocalStorageType.SNAPSHOT_TGZ
    with pytest.raises(ValueError):
        f._cleanup_local_cache()


# --- S3 tests (require live AWS credentials) ---

@pytest.mark.slow
def test_s3_roundtrip(tmp_path, s3_test_bucket, s3_base_url_factory):
    payload = b'\x1f\x8b' + b'pretend-gzipped-tarball-bytes' * 16
    local_copy = tmp_path / GOLDEN_NAME
    local_copy.write_bytes(payload)
    # Point the class at a run-unique base URL; the object derives its key from base + filename.
    s3_base_url_factory(SnapshotFile, 'test_snapshot_file')

    f = SnapshotFile(
        datetimestamp=GOLDEN_DT,
        local_filepath_tgz=local_copy,
        local_storage_type=LocalStorageType.SNAPSHOT_TGZ,
        cleanup_policy=CleanupPolicy.CLEANUP_NEVER,
    )
    test_key = None
    try:
        f.s3_upload()
        assert f.s3_exists()
        assert f.s3_path.endswith(GOLDEN_NAME)
        assert not f.s3_path.endswith('.bz2')
        test_key = f.s3_path

        download_path = tmp_path / 'downloaded.tgz'
        f2 = SnapshotFile(
            datetimestamp=GOLDEN_DT,
            local_filepath_tgz=download_path,
            local_storage_type=LocalStorageType.UNCACHED,
            s3_url=f.s3_url,
            cleanup_policy=CleanupPolicy.CLEANUP_NEVER,
        )
        f2.s3_download()
        assert f2.local_storage_type == LocalStorageType.SNAPSHOT_TGZ
        # uploaded byte-for-byte: the downloaded TAR must equal the original payload
        assert download_path.read_bytes() == payload
    finally:
        if test_key is not None:
            s3_test_bucket.Object(test_key).delete()


# --- validate_tar (synthetic tars, no network) ---

def test_validate_tar_good(tmp_path):
    tgz = tmp_path / GOLDEN_NAME
    _make_tgz(tgz, {_summary_member_name(): b'{}', 'rpki-x/output/rpki-client.log': b'log'})
    f = SnapshotFile(
        datetimestamp=GOLDEN_DT, local_filepath_tgz=tgz,
        local_storage_type=LocalStorageType.SNAPSHOT_TGZ,
    )
    assert f.validate_tar() is True


def test_validate_tar_corrupt_returns_false(tmp_path):
    bad = tmp_path / GOLDEN_NAME
    bad.write_bytes(b'this is not a gzipped tar')
    f = SnapshotFile(
        datetimestamp=GOLDEN_DT, local_filepath_tgz=bad,
        local_storage_type=LocalStorageType.SNAPSHOT_TGZ,
    )
    assert f.validate_tar() is False


def test_validate_tar_requires_local_tgz():
    f = SnapshotFile(
        datetimestamp=GOLDEN_DT, local_storage_dir=Path('/tmp'),
        local_storage_type=LocalStorageType.UNCACHED,
    )
    with pytest.raises(ValueError):
        f.validate_tar()


# --- extract_summary_file (synthetic tars, no network) ---

def test_extract_summary_file(tmp_path):
    summary_payload = json.dumps({'metadata': {'buildtime': '2021-11-21T00:07:09Z'}, 'roas': []}).encode()
    tgz = tmp_path / GOLDEN_NAME
    _make_tgz(tgz, {
        _summary_member_name(): summary_payload,
        'rpki-20211121T000709Z/output/rpki-client.log': b'log',
    })
    snapshot = SnapshotFile(
        datetimestamp=GOLDEN_DT, local_filepath_tgz=tgz,
        local_storage_type=LocalStorageType.SNAPSHOT_TGZ,
    )
    summary = snapshot.extract_summary_file(output_dir=tmp_path)
    assert isinstance(summary, SnapshotSummaryFile)
    assert summary.local_storage_type == LocalStorageType.UNCOMPRESSED
    # named by the snapshot's datetimestamp, not the in-TAR member path
    assert summary.local_filepath_uncompressed.name == '20211121T000709Z.json'
    assert json.loads(summary.local_filepath_uncompressed.read_bytes()) == json.loads(summary_payload)


def test_extract_summary_file_no_member_raises(tmp_path):
    tgz = tmp_path / GOLDEN_NAME
    _make_tgz(tgz, {'rpki-20211121T000709Z/output/other.json': b'{}'})
    snapshot = SnapshotFile(
        datetimestamp=GOLDEN_DT, local_filepath_tgz=tgz,
        local_storage_type=LocalStorageType.SNAPSHOT_TGZ,
    )
    with pytest.raises(KeyError):
        snapshot.extract_summary_file(output_dir=tmp_path)


def test_extract_summary_file_multiple_members_raises(tmp_path):
    tgz = tmp_path / GOLDEN_NAME
    _make_tgz(tgz, {
        'rpki-20211121T000709Z/output/rpki-client.json': b'{}',
        'rpki-20211121T000710Z/output/rpki-client.json': b'{}',
    })
    snapshot = SnapshotFile(
        datetimestamp=GOLDEN_DT, local_filepath_tgz=tgz,
        local_storage_type=LocalStorageType.SNAPSHOT_TGZ,
    )
    with pytest.raises(ValueError):
        snapshot.extract_summary_file(output_dir=tmp_path)


# --- Golden snapshot TAR (large; reads test_data/ only, no S3) ---

@pytest.mark.slow
@skipif_no_golden_snapshot
def test_validate_tar_golden(tmp_path):
    snapshot = SnapshotFile(
        datetimestamp=GOLDEN_SNAPSHOT_DT, local_filepath_tgz=GOLDEN_SNAPSHOT_TGZ,
        local_storage_type=LocalStorageType.SNAPSHOT_TGZ,
        cleanup_policy=CleanupPolicy.CLEANUP_NEVER,
    )
    assert snapshot.validate_tar() is True


@pytest.mark.slow
@skipif_no_golden_snapshot
def test_extract_summary_file_golden(tmp_path):
    snapshot = SnapshotFile(
        datetimestamp=GOLDEN_SNAPSHOT_DT, local_filepath_tgz=GOLDEN_SNAPSHOT_TGZ,
        local_storage_type=LocalStorageType.SNAPSHOT_TGZ,
        cleanup_policy=CleanupPolicy.CLEANUP_NEVER,
    )
    summary = snapshot.extract_summary_file(output_dir=tmp_path)
    assert summary.local_filepath_uncompressed.name == '20260111T194523Z.json'
    data = json.loads(summary.local_filepath_uncompressed.read_bytes())
    assert 'metadata' in data
    assert 'roas' in data


# --- archive_file SQL methods (fake db via fake_db.FakeDb; no MariaDB server) ---

ArchiveFileRow = namedtuple('ArchiveFileRow', [
    'source_id', 'source_url', 'filename_derived_datetime', 'discovered_datetime',
    'file_type_id', 'our_s3_url', 'our_size_bytes', 'our_sha256', 'our_stored_datetime',
    'observation_datetime',
])

JOSEPHINE_TAR_URL = 'https://josephine.sobornost.net/rpkidata/2026/05/01/rpki-20260501T005438Z.tgz'
JOSEPHINE_DT = datetime(2026, 5, 1, 0, 54, 38, tzinfo=timezone.utc)


@pytest.fixture
def josephine_source():
    """Seed the DataFileSource caches so get_by_id() needs no database; restore on teardown."""
    source = DataFileSource(
        id=2, name='josephine.sobornost.net', base_url='https://josephine.sobornost.net/rpkidata/',
    )
    DataFileSource._cache_by_id[source.id] = source
    DataFileSource._cache_by_name[source.name] = source
    yield source
    DataFileSource.invalidate_caches()


def make_archive_file_row(**overrides) -> ArchiveFileRow:
    row = ArchiveFileRow(
        source_id=2,
        source_url=JOSEPHINE_TAR_URL,
        filename_derived_datetime=datetime(2026, 5, 1, 0, 54, 38),
        discovered_datetime=datetime(2026, 5, 1, 1, 0, 0),
        file_type_id=1,
        our_s3_url='s3://rpkilog-snapshot/rpki-20260501T005438Z.tgz',
        our_size_bytes=987654,
        our_sha256=b'\x00' * 32,
        our_stored_datetime=datetime(2026, 5, 1, 1, 0, 5),
        observation_datetime=None,
    )
    retval = row._replace(**overrides)
    return retval


def test_utc_naive_converts_aware_offset():
    aware = datetime(2026, 5, 1, 2, 54, 38, tzinfo=timezone(timedelta(hours=2)))
    assert SnapshotFile._utc_naive(aware) == datetime(2026, 5, 1, 0, 54, 38)


def test_utc_naive_passes_through_naive():
    naive = datetime(2026, 5, 1, 0, 54, 38)
    assert SnapshotFile._utc_naive(naive) == naive


def test_from_db_row_hydrates_datetimestamp_from_column(josephine_source):
    snapshot = SnapshotFile.from_db_row(make_archive_file_row())
    assert snapshot.datetimestamp == JOSEPHINE_DT
    assert snapshot.source is josephine_source
    assert snapshot.source_url == JOSEPHINE_TAR_URL
    assert snapshot.s3_url == 's3://rpkilog-snapshot/rpki-20260501T005438Z.tgz'
    assert snapshot.s3_stored is True
    assert snapshot.discovered_datetime == datetime(2026, 5, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert snapshot.observation_datetime is None


def test_from_db_row_falls_back_to_url_parse(josephine_source):
    snapshot = SnapshotFile.from_db_row(make_archive_file_row(filename_derived_datetime=None))
    assert snapshot.datetimestamp == JOSEPHINE_DT


def test_from_db_row_no_stored_copy(josephine_source):
    row = make_archive_file_row(our_s3_url=None, our_size_bytes=None, our_sha256=None)
    snapshot = SnapshotFile.from_db_row(row)
    assert snapshot.s3_url is None
    assert snapshot.s3_stored is False


def test_from_db_row_seeds_metadata_cache(josephine_source):
    # sha256/size must come from the row: an UNCACHED snapshot with no s3_url would otherwise
    # try (and fail) to derive a default S3 URL and download the file
    snapshot = SnapshotFile.from_db_row(make_archive_file_row())
    assert snapshot.sha256_digest() == b'\x00' * 32
    assert snapshot.size_bytes_uncompressed() == 987654


def test_db_select_within_range_bounds_and_ingested_alter_statement(josephine_source):
    db = FakeDb()
    SnapshotFile.db_select_within_range(
        db=db,
        source=josephine_source,
        datetime_min=datetime(2026, 5, 1, tzinfo=timezone.utc),
        datetime_max=datetime(2026, 5, 2, tzinfo=timezone.utc),
        ingested=False,
    )
    statement, params = db.executed[0]
    assert ' AND filename_derived_datetime >= ?' in statement
    assert ' AND filename_derived_datetime <= ?' in statement
    assert ' AND observation_datetime IS NULL' in statement
    assert statement.endswith(' ORDER BY filename_derived_datetime')
    assert params == (2, datetime(2026, 5, 1), datetime(2026, 5, 2))

    db = FakeDb()
    SnapshotFile.db_select_within_range(db=db, source=josephine_source, ingested=True)
    statement, params = db.executed[0]
    assert 'filename_derived_datetime >= ?' not in statement
    assert ' AND observation_datetime IS NOT NULL' in statement
    assert params == (2,)


def test_db_select_within_range_naive_bounds_assumed_utc(josephine_source):
    db = FakeDb()
    SnapshotFile.db_select_within_range(
        db=db,
        source=josephine_source,
        datetime_min=datetime(2026, 5, 1, 0, 0, 0),
        datetime_max=datetime(2026, 5, 2, 12, 0, 0),
    )
    statement, params = db.executed[0]
    assert params == (2, datetime(2026, 5, 1, 0, 0, 0), datetime(2026, 5, 2, 12, 0, 0))


def test_db_select_within_range_skips_unparseable_source_url(josephine_source):
    good_row = make_archive_file_row()
    bad_row = make_archive_file_row(
        source_url='https://josephine.sobornost.net/rpkidata/README.txt',
        filename_derived_datetime=None,
    )
    db = FakeDb(rows_by_fragment={'FROM archive_file WHERE source_id': [good_row, bad_row]})
    found = SnapshotFile.db_select_within_range(db=db, source=josephine_source)
    assert len(found) == 1
    assert found[0].source_url == JOSEPHINE_TAR_URL


def test_db_row_exists_requires_identity():
    snapshot = SnapshotFile(datetimestamp=JOSEPHINE_DT)
    with pytest.raises(ValueError):
        snapshot.db_row_exists(db=FakeDb())

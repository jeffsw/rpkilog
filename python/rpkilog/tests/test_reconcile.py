"""
Tests for reconcile.py's sql-data-file-to-sql-archive-file helpers, using fake_db.FakeDb and a
fake S3 bucket; no MariaDB server, AWS credentials, or network needed.
"""
from collections import namedtuple
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from fake_db import FakeDb
from test_util import make_fake_bucket

from rpkilog.data_file_source import DataFileSource
from rpkilog.data_file_type import DataFileType
from rpkilog.reconcile import (
    ReconcileOutcome,
    list_snapshot_objects_from_s3,
    synthesize_archive_file_row,
)

DataFileRow = namedtuple(
    'DataFileRow',
    ['observation_datetime', 'summary_s3_url', 'summary_stored_datetime'],
)
FakeS3Object = namedtuple('FakeS3Object', ['bucket_name', 'key', 'size', 'last_modified'])

SOURCE = DataFileSource(
    id=2,
    name='josephine.sobornost.net',
    base_url='https://josephine.sobornost.net/rpkidata/',
)
FILE_TYPE = DataFileType(id=1, kind='full', name='rpkiclient_snapshot_full_v1')
EXPECTED_SOURCE_URL = 'https://josephine.sobornost.net/rpkidata/2026/05/01/rpki-20260501T005438Z.tgz'
# The observation_datetime (metadata buildtime) deliberately differs from the summary FILENAME
# timestamp by 2 seconds; the derived source_url must use the latter.
DATA_FILE_ROW = DataFileRow(
    observation_datetime=datetime(2026, 5, 1, 0, 54, 36),
    summary_s3_url='s3://rpkilog-snapshot-summary/20260501T005438Z.json.bz2',
    summary_stored_datetime=datetime(2026, 5, 1, 1, 0, 0),
)
SNAPSHOT_LISTING = {
    datetime(2026, 5, 1, 0, 54, 38, tzinfo=timezone.utc): FakeS3Object(
        bucket_name='rpkilog-snapshot',
        key='rpki-20260501T005438Z.tgz',
        size=987654,
        last_modified=datetime(2026, 5, 1, 1, 0, 5, tzinfo=timezone.utc),
    ),
}


def find_insert(db: FakeDb):
    """Return the (statement, params) of the archive_file INSERT, or (None, None)."""
    for statement, params in db.executed:
        if statement.startswith('INSERT INTO archive_file'):
            return statement, params
    return None, None


# --- synthesize_archive_file_row ---

def test_synthesize_archive_file_row_inserts_without_our_copy():
    db = FakeDb()
    outcome = synthesize_archive_file_row(
        db=db, source=SOURCE, data_file_row=DATA_FILE_ROW, file_type=FILE_TYPE,
        snapshot_objects_by_datetime={}, dry_run=False,
    )
    assert outcome == ReconcileOutcome.INSERTED
    statement, params = find_insert(db)
    assert params[0] == SOURCE.id
    # source_url + filename_derived_datetime come from the summary FILENAME timestamp...
    assert params[1] == EXPECTED_SOURCE_URL
    assert params[2] == datetime(2026, 5, 1, 0, 54, 38)
    # ...discovered_datetime is backdated to summary_stored_datetime...
    assert params[3] == datetime(2026, 5, 1, 1, 0, 0)
    assert params[4] == FILE_TYPE.id
    # ...and observation_datetime stays the buildtime, 2s earlier than the filename timestamp
    assert params[5] == datetime(2026, 5, 1, 0, 54, 36)
    # no stored TAR in the listing: our_* stay NULL
    assert params[6] is None and params[7] is None and params[8] is None


def test_synthesize_archive_file_row_records_our_copy_from_listing():
    db = FakeDb()
    outcome = synthesize_archive_file_row(
        db=db, source=SOURCE, data_file_row=DATA_FILE_ROW, file_type=FILE_TYPE,
        snapshot_objects_by_datetime=SNAPSHOT_LISTING, dry_run=False,
    )
    assert outcome == ReconcileOutcome.INSERTED
    statement, params = find_insert(db)
    assert params[6] == 's3://rpkilog-snapshot/rpki-20260501T005438Z.tgz'
    assert params[7] == 987654
    assert params[8] == datetime(2026, 5, 1, 1, 0, 5)


def test_synthesize_archive_file_row_discovered_falls_back_to_observation():
    db = FakeDb()
    row = DATA_FILE_ROW._replace(summary_stored_datetime=None)
    synthesize_archive_file_row(
        db=db, source=SOURCE, data_file_row=row, file_type=FILE_TYPE,
        snapshot_objects_by_datetime={}, dry_run=False,
    )
    statement, params = find_insert(db)
    assert params[3] == row.observation_datetime


def test_synthesize_archive_file_row_already_recorded():
    db = FakeDb(rows_by_fragment={'SELECT 1 FROM archive_file': [(1,)]})
    outcome = synthesize_archive_file_row(
        db=db, source=SOURCE, data_file_row=DATA_FILE_ROW, file_type=FILE_TYPE,
        snapshot_objects_by_datetime={}, dry_run=False,
    )
    assert outcome == ReconcileOutcome.ALREADY_RECORDED
    assert find_insert(db) == (None, None)


def test_synthesize_archive_file_row_dry_run_skips_insert():
    db = FakeDb()
    outcome = synthesize_archive_file_row(
        db=db, source=SOURCE, data_file_row=DATA_FILE_ROW, file_type=FILE_TYPE,
        snapshot_objects_by_datetime={}, dry_run=True,
    )
    # outcome counts as INSERTED either way, but only the existence SELECT may hit the db
    assert outcome == ReconcileOutcome.INSERTED
    assert find_insert(db) == (None, None)
    assert len(db.executed) == 1


def test_synthesize_archive_file_row_no_summary_s3_url():
    db = FakeDb()
    row = DATA_FILE_ROW._replace(summary_s3_url=None)
    outcome = synthesize_archive_file_row(
        db=db, source=SOURCE, data_file_row=row, file_type=FILE_TYPE,
        snapshot_objects_by_datetime={}, dry_run=False,
    )
    assert outcome == ReconcileOutcome.NO_SUMMARY_S3_URL
    assert db.executed == []


# --- list_snapshot_objects_from_s3 ---

def make_fake_s3(bucket):
    """A boto3 S3ServiceResource stand-in whose Bucket() returns the given fake bucket."""
    def fake_bucket_factory(bucket_name):
        return bucket

    retval = SimpleNamespace(Bucket=fake_bucket_factory)
    return retval


def test_list_snapshot_objects_rejects_non_s3_url():
    with pytest.raises(ValueError):
        list_snapshot_objects_from_s3(
            s3=make_fake_s3(make_fake_bucket([])),
            s3_snapshot_prefix='https://rpkilog-snapshot/',
            datetime_min=datetime(2026, 5, 1, tzinfo=timezone.utc),
            datetime_max=datetime(2026, 5, 2, tzinfo=timezone.utc),
        )


def test_list_snapshot_objects_keyed_by_datetimestamp_and_skips_unmatched():
    bucket = make_fake_bucket([
        'rpki-20260501T005438Z.tgz',
        'rpki-20260501Tjunk.tgz',   # passes the per-day prefix but is not a snapshot filename
    ])
    bucket.name = 'fake-snapshot-bucket'
    retdict = list_snapshot_objects_from_s3(
        s3=make_fake_s3(bucket),
        s3_snapshot_prefix='s3://fake-snapshot-bucket/',
        datetime_min=datetime(2026, 5, 1, tzinfo=timezone.utc),
        datetime_max=datetime(2026, 5, 1, 23, 59, tzinfo=timezone.utc),
    )
    assert list(retdict) == [datetime(2026, 5, 1, 0, 54, 38, tzinfo=timezone.utc)]
    assert retdict[datetime(2026, 5, 1, 0, 54, 38, tzinfo=timezone.utc)].key == 'rpki-20260501T005438Z.tgz'

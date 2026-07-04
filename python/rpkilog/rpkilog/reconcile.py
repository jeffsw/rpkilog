import argparse
import datetime
import dateutil.parser
import importlib.resources
import logging
from typing import TYPE_CHECKING

from rpkilog.data_file_type import DataFileType
from rpkilog.reconcile_config import ReconcileConfig
from rpkilog.snapshot_summary_file import SnapshotSummaryFile

if TYPE_CHECKING:
    import mariadb


def load_reconcile_config() -> ReconcileConfig:
    """
    Load the reconcile_config.yml data file packaged with this module and return a ReconcileConfig.
    """
    config_resource = importlib.resources.files('rpkilog').joinpath('reconcile_config.yml')
    yaml_str = config_resource.read_text()
    retval = ReconcileConfig.load(yaml_str)
    return retval


def cli_entry_point():
    """
    TODO: implement
    """
    logging.basicConfig(
        datefmt='%Y-%m-%dT%H:%M:%S',
        format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
    )
    ap1 = argparse.ArgumentParser()
    # db
    ap1.add_argument('--db-host', type=str, help='MariaDB host')
    ap1.add_argument('--db-port', default=3306, type=int, help='MariaDB port (default: 3306)')
    ap1.add_argument('--db-user', type=str, help='MariaDB user')
    ap1.add_argument('--db-password', type=str, help='MariaDB password (or use env RPKILOG_DB_PASSWORD')
    ap1.add_argument('--db-name', type=str, help='MariaDB database name')
    # debug
    ap1.add_argument('--debug', action='store_true', help='Break to debugger after parsing arguments')
    # dry-run
    ap1.add_argument('--dry-run', action='store_true', help='Dry run')
    # s3
    ap1.add_argument('--s3-summary-prefix', help='s3://bucket-name/prefix for summary files')

    subparsers = ap1.add_subparsers(dest='subparser_name', required=True)

    ap_from_s3_summary = subparsers.add_parser(
        'from_s3_summary',
        description='Read from given --s3-summary-prefix and update SQL database'
    )
    ap_from_s3_summary.add_argument(
        '--datetime-min',
        type=dateutil.parser.parse,
        default=datetime.datetime.fromisoformat('2000-01-01T00:00:00Z'),
        help='minimum datetimestamp of summary files to reconcile into SQL DB',
    )
    ap_from_s3_summary.add_argument(
        '--datetime-max',
        type=dateutil.parser.parse,
        default=datetime.datetime.fromisoformat('2099-12-31T00:00:00Z'),
        help='maximum datetimestamp of summary files to reconcile into SQL DB',
    )

    args = ap1.parse_args()
    if args.debug:
        breakpoint()

    print(args)

    config = load_reconcile_config()
    if args.subparser_name == 'from_s3_summary':
        reconcile_from_s3_summary(args=args, config=config)


def db_connect(args: argparse.Namespace) -> 'mariadb.Connection':
    """
    Connect to MariaDB using args.db_* and make the connection available to the SQL-row classes.

    Planned implementation:
    1. password from args.db_password, falling back to env RPKILOG_DB_PASSWORD
    2. connect with MariaDB Connector/Python in pure-Python mode (see the driver decision in
       gh-81-sqldb.md), with autocommit=True — db_insert() and friends rely on it

    3. set DataFileSource.default_db_connection and DataFileType.default_db_connection to the new
       connection (the dependency-injection default used by their get_by_name() constructors)
    4. return the connection

    TODO: implement
    TODO: add `mariadb` to pyproject.toml dependencies (2.0 is a release candidate: plain
      `pip install mariadb` yields 1.1, which always builds the C extension; needs a
      pre-release pin)
    TODO: prod will use RDS IAM auth tokens instead of a static password
    """
    pass


def reconcile_from_s3_summary(
        args: argparse.Namespace,
        config: ReconcileConfig,
):
    """
    Reconcile summary files found under --s3-summary-prefix into the SQL data_file table.  Doubles
    as the initial backfill of that table (see "How reconciliation uses this" in gh-81-sqldb.md).

    Planned implementation:
    1. db = db_connect(args)
    2. summary_file_type = DataFileType.get_by_name(SnapshotSummaryFile.sql_file_type_name),
       resolved once per run
    3. summary_files = summary_files_from_s3(args.s3_summary_prefix, args.datetime_min,
       args.datetime_max)
    4. reconcile_summary_file(...) for each, honoring args.dry_run
    5. log summary counts: listed / already-recorded / inserted / unattributable-to-a-source

    TODO: implement
    """
    # thousands of instances may be alive at once; don't retain multi-MB parsed JSON on each
    SnapshotSummaryFile._json_data_cache_enable = False


def summary_files_from_s3(
        s3_summary_prefix: str,
        datetime_min: datetime.datetime,
        datetime_max: datetime.datetime,
) -> list[SnapshotSummaryFile]:
    """
    List summary files stored under the given s3://bucket-name/prefix within the datetime range
    and return a SnapshotSummaryFile for each.

    TODO: parse s3_summary_prefix into bucket name + key prefix (urllib.parse; require s3://
      scheme)
    TODO: bucket = boto3.resource('s3').Bucket(bucket_name), then
      util.list_s3_summary_files_within_range(bucket=bucket, start_datetime=datetime_min,
      end_datetime=datetime_max, prefix=key_prefix)
    TODO: instantiate via SnapshotSummaryFile.from_s3_object_summary(obj); return sorted by
      datetimestamp for orderly progress logging
    """
    pass


def reconcile_summary_file(
        db: 'mariadb.Connection',
        config: ReconcileConfig,
        summary_file: SnapshotSummaryFile,
        summary_file_type: DataFileType,
        dry_run: bool = False,
):
    """
    Ensure the SQL data_file table has a row for one summary file; insert one if missing.

    Planned implementation:
    1. if summary_file.db_row_exists(db=db): nothing to do.  The summary_s3_url branch makes this
       check cheap for files instantiated from an S3 listing (no download needed)
    2. source_name = config.get_source_name(buildmachine=summary_file.buildmachine,
       observation_datetime=summary_file.observation_datetime) — both properties read the JSON
       content, downloading from S3 when uncached
    3. summary_file.source = DataFileSource.get_by_name(source_name)
    4. summary_file.db_insert(db=db, summary_file_type=summary_file_type) — skipped when dry_run;
       logged either way

    TODO: implement
    """
    pass


if __name__ == '__main__':
    cli_entry_point()

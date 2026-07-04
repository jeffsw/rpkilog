import argparse
import datetime
import dateutil.parser
import enum
import importlib.resources
import logging
import os
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
import mariadb

from rpkilog.data_file_source import DataFileSource
from rpkilog.data_file_type import DataFileType
from rpkilog.reconcile_config import ReconcileConfig
from rpkilog.snapshot_summary_file import SnapshotSummaryFile
from rpkilog.util import list_s3_summary_files_within_range

if TYPE_CHECKING:
    from types_boto3_s3.service_resource import S3ServiceResource

logger = logging.getLogger(__name__)


class ReconcileOutcome(enum.Enum):
    """
    Per-file result of reconcile_summary_file(), tallied by reconcile_from_s3_summary().
    """
    ALREADY_RECORDED = 'already_recorded'
    """The data_file table already had a row for the file; nothing to do."""
    INSERTED = 'inserted'
    """A data_file row was inserted — or would have been, under --dry-run."""
    UNATTRIBUTABLE = 'unattributable'
    """No buildmachine_to_source mapping matched, so the file cannot be keyed in data_file."""


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
    Parse CLI arguments and dispatch to the requested reconcile subcommand.
    """
    logging.basicConfig(
        datefmt='%Y-%m-%dT%H:%M:%S',
        format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
        level=logging.INFO,
    )
    ap1 = argparse.ArgumentParser()
    ap1.add_argument(
        '--datetime-min',
        type=dateutil.parser.parse,
        default=datetime.datetime.fromisoformat('2000-01-01T00:00:00Z'),
        help='minimum datetimestamp of data files to reconcile into SQL DB',
    )
    ap1.add_argument(
        '--datetime-max',
        type=dateutil.parser.parse,
        default=datetime.datetime.fromisoformat('2099-12-31T00:00:00Z'),
        help='maximum datetimestamp of data files to reconcile into SQL DB',
    )
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
    ap1.add_argument(
        '--s3-summary-cache-dir',
        type=Path,
        help='local directory for caching downloaded summary files; reused across runs '
             '(default: a temp dir discarded at exit)',
    )
    ap1.add_argument('--s3-summary-prefix', help='s3://bucket-name/prefix for summary files')

    subparsers = ap1.add_subparsers(dest='subparser_name', required=True)

    subparsers.add_parser(
        'from_s3_summary',
        description='Read from given --s3-summary-prefix and update SQL database'
    )

    args = ap1.parse_args()
    if args.debug:
        breakpoint()

    if args.s3_summary_cache_dir is not None:
        args.s3_summary_cache_dir.mkdir(parents=True, exist_ok=True)
        SnapshotSummaryFile.default_local_storage_dir = args.s3_summary_cache_dir
        SnapshotSummaryFile.file_cache_enable = True

    config = load_reconcile_config()
    if args.subparser_name == 'from_s3_summary':
        if args.s3_summary_prefix is None:
            ap1.error('--s3-summary-prefix is required for the from_s3_summary subcommand')
        reconcile_from_s3_summary(args=args, config=config)


def db_connect(args: argparse.Namespace) -> mariadb.SyncConnection:
    """
    Connect to MariaDB using args.db_* and make the connection available to the SQL-row classes.

    The password comes from args.db_password, falling back to env RPKILOG_DB_PASSWORD.

    TODO: prod will use RDS IAM auth tokens instead of a static password

    TOTEST:
    - test_db_connect_password_falls_back_to_env: args.db_password unset + RPKILOG_DB_PASSWORD
      set connects using the env value (mariadb.connect monkeypatched)
    - test_db_connect_cli_password_beats_env: an explicit --db-password wins over the env var
    - test_db_connect_sets_default_db_connections: DataFileSource.default_db_connection and
      DataFileType.default_db_connection are the returned connection afterward
    """
    password = args.db_password
    if password is None:
        password = os.environ.get('RPKILOG_DB_PASSWORD')
    retval = mariadb.connect(
        host=args.db_host,
        port=args.db_port,
        user=args.db_user,
        password=password,
        database=args.db_name,
        autocommit=True,
    )
    DataFileSource.default_db_connection = retval
    DataFileType.default_db_connection = retval
    return retval


def reconcile_from_s3_summary(
        args: argparse.Namespace,
        config: ReconcileConfig,
):
    """
    Reconcile summary files found under --s3-summary-prefix into the SQL data_file table.  Doubles
    as the initial backfill of that table.
    """
    # thousands of instances may be alive at once; don't retain multi-MB parsed JSON on each
    SnapshotSummaryFile._json_data_cache_enable = False
    db = db_connect(args)
    summary_file_type = DataFileType.get_by_name(SnapshotSummaryFile.sql_file_type_name, db=db)
    s3 = boto3.resource('s3')
    summary_files = list_summary_files_from_s3(
        s3=s3,
        s3_summary_prefix=args.s3_summary_prefix,
        datetime_min=args.datetime_min,
        datetime_max=args.datetime_max,
    )
    logger.info(f'listed {len(summary_files)} summary files under {args.s3_summary_prefix}')
    counts = {}
    for outcome in ReconcileOutcome:
        counts[outcome] = 0
    for summary_file in summary_files:
        # the context manager unlinks the file's local download (if any) on exit — unless
        # file_cache_enable is set (--s3-summary-cache-dir), which preserves it for future runs
        with summary_file:
            outcome = reconcile_summary_file(
                db=db,
                config=config,
                summary_file=summary_file,
                summary_file_type=summary_file_type,
                dry_run=args.dry_run,
            )
        counts[outcome] += 1
    if args.dry_run:
        run_mode = 'DRY-RUN '
    else:
        run_mode = ''
    logger.info(
        f'{run_mode}reconcile complete: listed={len(summary_files)} '
        f'already_recorded={counts[ReconcileOutcome.ALREADY_RECORDED]} '
        f'inserted={counts[ReconcileOutcome.INSERTED]} '
        f'unattributable={counts[ReconcileOutcome.UNATTRIBUTABLE]}'
    )


def list_summary_files_from_s3(
        s3: 'S3ServiceResource',
        s3_summary_prefix: str,
        datetime_min: datetime.datetime,
        datetime_max: datetime.datetime,
) -> list[SnapshotSummaryFile]:
    """
    List summary files stored under the given s3://bucket-name/prefix within the datetime range
    and return a SnapshotSummaryFile for each, sorted by datetimestamp.

    util.list_s3_summary_files_within_range is approximate at the range boundaries; files outside
    datetime_min ... datetime_max are filtered out here.  Naive datetime bounds are assumed UTC.

    TOTEST:
    - test_list_summary_files_rejects_non_s3_url
    - test_list_summary_files_sorted_and_filtered
    - test_list_summary_files_naive_bounds_assumed_utc
    """
    parsed_prefix = urllib.parse.urlparse(s3_summary_prefix)
    if parsed_prefix.scheme != 's3' or not parsed_prefix.netloc:
        raise ValueError(f's3_summary_prefix must be an s3://bucket-name/prefix URL: {s3_summary_prefix}')
    bucket = s3.Bucket(parsed_prefix.netloc)
    key_prefix = parsed_prefix.path.lstrip('/')
    if datetime_min.tzinfo is None:
        datetime_min = datetime_min.replace(tzinfo=datetime.timezone.utc)
    if datetime_max.tzinfo is None:
        datetime_max = datetime_max.replace(tzinfo=datetime.timezone.utc)
    object_summaries = list_s3_summary_files_within_range(
        bucket=bucket,
        start_datetime=datetime_min,
        end_datetime=datetime_max,
        prefix=key_prefix,
    )
    retlist = []
    for obj in object_summaries:
        summary_file = SnapshotSummaryFile.from_s3_object_summary(obj)
        if datetime_min <= summary_file.datetimestamp <= datetime_max:
            retlist.append(summary_file)
    retlist.sort(key=lambda summary_file: summary_file.datetimestamp)
    return retlist


def reconcile_summary_file(
        db: mariadb.SyncConnection,
        config: ReconcileConfig,
        summary_file: SnapshotSummaryFile,
        summary_file_type: DataFileType,
        dry_run: bool = False,
) -> ReconcileOutcome:
    """
    Ensure the SQL data_file table has a row for one summary file; insert one if missing.

    A file matching no buildmachine_to_source mapping is counted UNATTRIBUTABLE, but a mapping
    naming a source absent from the source table is config/schema drift and propagates as
    KeyError.  With dry_run, the INSERT is skipped but the outcome is INSERTED either way.

    TOTEST (fake db/config; SnapshotSummaryFile methods monkeypatched):
    - test_reconcile_summary_file_already_recorded
    - test_reconcile_summary_file_inserts
    - test_reconcile_summary_file_dry_run_skips_insert
    - test_reconcile_summary_file_unattributable
    - test_reconcile_summary_file_unknown_source_propagates
    """
    if summary_file.db_row_exists(db=db):
        logger.debug(f'already recorded: {summary_file.s3_url}')
        retval = ReconcileOutcome.ALREADY_RECORDED
        return retval
    try:
        source_name = config.get_source_name(
            buildmachine=summary_file.buildmachine,
            observation_datetime=summary_file.observation_datetime,
        )
    except KeyError as exc:
        logger.warning(f'cannot attribute summary file to a source: {exc}')
        retval = ReconcileOutcome.UNATTRIBUTABLE
        return retval
    summary_file.source = DataFileSource.get_by_name(source_name, db=db)
    observation_datetime = summary_file.observation_datetime.isoformat()
    if dry_run:
        logger.info(
            f'DRY-RUN would insert data_file row: source={source_name} '
            f'observation_datetime={observation_datetime} file={summary_file.s3_url}'
        )
    else:
        summary_file.db_insert(db=db, summary_file_type=summary_file_type)
        logger.info(
            f'inserted data_file row: source={source_name} '
            f'observation_datetime={observation_datetime} file={summary_file.s3_url}'
        )
    retval = ReconcileOutcome.INSERTED
    return retval


if __name__ == '__main__':
    cli_entry_point()

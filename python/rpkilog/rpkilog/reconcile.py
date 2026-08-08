import argparse
import concurrent.futures
import datetime
import dateutil.parser
import enum
import importlib.resources
import logging
import threading
import time
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
import mariadb

from rpkilog.archive_site_crawler import ArchiveSiteCrawler
from rpkilog.data_file_source import DataFileSource
from rpkilog.data_file_type import DataFileType
from rpkilog.local_storage_type import LocalStorageType
from rpkilog.reconcile_config import ReconcileConfig
from rpkilog.snapshot_file import SnapshotFile
from rpkilog.snapshot_summary_file import SnapshotSummaryFile
from rpkilog.sqldb import db_connect, log_startup_args
from rpkilog.util import list_s3_snapshot_files_within_range, list_s3_summary_files_within_range

if TYPE_CHECKING:
    from types_boto3_s3.service_resource import S3ServiceResource

logger = logging.getLogger(__name__)

# per-worker-thread state; reconcile_from_s3_summary_thread_init() stores each worker's own DB
# connection here because a mariadb connection is not safe for concurrent use
_thread_local = threading.local()

# seconds between periodic progress-summary log lines in long row-processing loops, so an
# operator watching a run dominated by already-recorded rows still sees liveness
PROGRESS_LOG_INTERVAL_SECONDS = 5


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
    NO_SUMMARY_S3_URL = 'no_summary_s3_url'
    """data_file row has a NULL summary_s3_url, so the archive filename timestamp cannot be
    inferred; sql-data-file-to-sql-archive-file skips the row."""


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
    secret_arg_dests = set()

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
    db_password_action = ap1.add_argument(
        '--db-password', type=str, help='MariaDB password (or use env RPKILOG_DB_PASSWORD)',
    )
    secret_arg_dests.add(db_password_action.dest)
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
    ap1.add_argument(
        '--s3-snapshot-prefix',
        help='s3://bucket-name/prefix for archived snapshot TARs; when given, '
             'sql-data-file-to-sql-archive-file records our_* columns for TARs still stored there',
    )
    # threads
    ap1.add_argument('--threads', type=int, default=1, help='number of worker threads (default: 1)')

    subparsers = ap1.add_subparsers(dest='subparser_name', required=True)

    subparsers.add_parser(
        'from-s3-summary',
        description='Read from given --s3-summary-prefix and update SQL database'
    )

    subparsers.add_parser(
        'sql-data-file-to-sql-archive-file',
        description='Synthesize archive_file rows from data_file rows of crawled sources (sql -> sql)',
    )

    args = ap1.parse_args()
    if args.debug:
        breakpoint()
    log_startup_args(args=args, secret_dests=secret_arg_dests)

    if args.s3_summary_cache_dir is not None:
        args.s3_summary_cache_dir.mkdir(parents=True, exist_ok=True)
        SnapshotSummaryFile.default_local_storage_dir = args.s3_summary_cache_dir
        SnapshotSummaryFile.file_cache_enable = True

    config = load_reconcile_config()
    match args.subparser_name:
        case 'from-s3-summary':
            if args.s3_summary_prefix is None:
                ap1.error('--s3-summary-prefix is required for the from-s3-summary subcommand')
            reconcile_from_s3_summary(args=args, config=config)
        case 'sql-data-file-to-sql-archive-file':
            reconcile_sql_data_file_to_sql_archive_file(args=args)


def reconcile_from_s3_summary(
        args: argparse.Namespace,
        config: ReconcileConfig,
):
    """
    Reconcile summary files found under --s3-summary-prefix into the SQL data_file table.  Doubles
    as the initial backfill of that table.

    Per-file work runs on a ThreadPoolExecutor sized by --threads.  Each worker thread gets its
    own DB connection (created by reconcile_from_s3_summary_thread_init); outcomes are tallied
    here on the main thread.
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
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=args.threads,
        thread_name_prefix='reconcile',
        initializer=reconcile_from_s3_summary_thread_init,
        initargs=(args,),
    )
    try:
        futures = []
        for summary_file in summary_files:
            future = executor.submit(
                reconcile_from_s3_summary_thread_work,
                config=config,
                summary_file=summary_file,
                summary_file_type=summary_file_type,
                dry_run=args.dry_run,
            )
            futures.append(future)
        for future in futures:
            outcome = future.result()
            counts[outcome] += 1
    finally:
        # cancel_futures so a raising work unit (e.g. config/schema drift KeyError) surfaces
        # without first grinding through every queued file, approximating serial behavior
        executor.shutdown(wait=True, cancel_futures=True)
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


def reconcile_from_s3_summary_thread_init(args: argparse.Namespace):
    """
    ThreadPoolExecutor initializer: create this worker thread's own DB connection in
    _thread_local.  db_connect() re-assigns the default_db_connection classvars on every call;
    that repeat is harmless here because the reconcile code passes db= explicitly throughout.
    """
    _thread_local.db = db_connect(args)


def reconcile_from_s3_summary_thread_work(
        config: ReconcileConfig,
        summary_file: SnapshotSummaryFile,
        summary_file_type: DataFileType,
        dry_run: bool,
) -> ReconcileOutcome:
    """
    Per-file work unit submitted to the executor: reconcile one summary file using this worker
    thread's DB connection, returning the ReconcileOutcome for main-thread tallying.
    """
    with summary_file:
        retval = reconcile_summary_file(
            db=_thread_local.db,
            config=config,
            summary_file=summary_file,
            summary_file_type=summary_file_type,
            dry_run=dry_run,
        )
    return retval


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
    # the URL path names a "directory"; without the slash, s3://bucket/summaries would list
    # the non-existent prefix summaries<date> and silently match nothing
    if key_prefix and not key_prefix.endswith('/'):
        key_prefix += '/'
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


def reconcile_sql_data_file_to_sql_archive_file(args: argparse.Namespace):
    """
    Synthesize archive_file rows from data_file rows of crawled sources (sql -> sql):
    rpki_snapshots we previously downloaded from an archive site and processed — possibly
    deleting our TAR copy since — get their archive_file discovery/ingest history inferred, so a
    later crawler discovery pass over the same site finds only genuinely new files.

    The archive filename timestamp is inferred from summary_s3_url (the crawler names the
    extracted summary after the TAR filename), NOT from observation_datetime: the two differ by
    a few seconds (metadata buildtime vs filename), and the derived source_url must match future
    crawler-discovered URLs byte-for-byte.  With --s3-snapshot-prefix, TARs still stored in our
    snapshot bucket are recorded in the our_* columns from the listing (sha256 stays NULL).
    """
    db = db_connect(args)
    file_type = DataFileType.get_by_name(SnapshotFile.sql_file_type_name, db=db)
    snapshot_objects_by_datetime = {}
    if args.s3_snapshot_prefix is not None:
        s3 = boto3.resource('s3')
        snapshot_objects_by_datetime = list_snapshot_objects_from_s3(
            s3=s3,
            s3_snapshot_prefix=args.s3_snapshot_prefix,
            datetime_min=args.datetime_min,
            datetime_max=args.datetime_max,
        )
        logger.info(
            f'listed {len(snapshot_objects_by_datetime)} snapshot TARs under {args.s3_snapshot_prefix}'
        )
    counts = {}
    for outcome in ReconcileOutcome:
        counts[outcome] = 0
    sources = DataFileSource.get_all(db=db)
    for source in sources:
        if source.base_url is None:
            # one of our own uploaders, not a crawled archive; no archive-site history to infer
            continue
        data_file_rows = list_data_file_rows_for_source(
            db=db,
            source=source,
            datetime_min=args.datetime_min,
            datetime_max=args.datetime_max,
        )
        logger.info(f'source {source.name}: {len(data_file_rows)} data_file rows in range')
        progress_printed_last_time = time.monotonic()
        for row_number, data_file_row in enumerate(data_file_rows, start=1):
            outcome = synthesize_archive_file_row(
                db=db,
                source=source,
                data_file_row=data_file_row,
                file_type=file_type,
                snapshot_objects_by_datetime=snapshot_objects_by_datetime,
                dry_run=args.dry_run,
            )
            counts[outcome] += 1
            if time.monotonic() - progress_printed_last_time >= PROGRESS_LOG_INTERVAL_SECONDS:
                progress_printed_last_time = time.monotonic()
                logger.info(
                    f'progress: source={source.name} row={row_number}/{len(data_file_rows)} '
                    f'already_recorded={counts[ReconcileOutcome.ALREADY_RECORDED]} '
                    f'inserted={counts[ReconcileOutcome.INSERTED]} '
                    f'no_summary_s3_url={counts[ReconcileOutcome.NO_SUMMARY_S3_URL]}'
                )
    if args.dry_run:
        run_mode = 'DRY-RUN '
    else:
        run_mode = ''
    logger.info(
        f'{run_mode}sql-data-file-to-sql-archive-file complete: '
        f'already_recorded={counts[ReconcileOutcome.ALREADY_RECORDED]} '
        f'inserted={counts[ReconcileOutcome.INSERTED]} '
        f'no_summary_s3_url={counts[ReconcileOutcome.NO_SUMMARY_S3_URL]}'
    )


def list_snapshot_objects_from_s3(
        s3: 'S3ServiceResource',
        s3_snapshot_prefix: str,
        datetime_min: datetime.datetime,
        datetime_max: datetime.datetime,
) -> dict[datetime.datetime, object]:
    """
    List archived snapshot TARs stored under the given s3://bucket-name/prefix within the
    datetime range and return {filename-derived datetimestamp: ObjectSummary}.  Keys not
    matching the rpki-<ts>.tgz filename pattern are skipped with a warning.
    """
    parsed_prefix = urllib.parse.urlparse(s3_snapshot_prefix)
    if parsed_prefix.scheme != 's3' or not parsed_prefix.netloc:
        raise ValueError(
            f's3_snapshot_prefix must be an s3://bucket-name/prefix URL: {s3_snapshot_prefix}'
        )
    bucket = s3.Bucket(parsed_prefix.netloc)
    key_prefix = parsed_prefix.path.lstrip('/')
    # the URL path names a "directory"; without the slash, s3://bucket/archive would list
    # the non-existent prefix archiverpki- and silently match nothing
    if key_prefix and not key_prefix.endswith('/'):
        key_prefix += '/'
    object_summaries = list_s3_snapshot_files_within_range(
        bucket=bucket,
        start_datetime=datetime_min,
        end_datetime=datetime_max,
        prefix=key_prefix,
    )
    retdict = {}
    for obj in object_summaries:
        try:
            obj_datetime = SnapshotFile.infer_datetimestamp_from_path(Path(obj.key))
        except ValueError:
            logger.warning(f'UNMATCHED key in snapshot bucket {bucket.name}: {obj.key}')
            continue
        retdict[obj_datetime] = obj
    return retdict


def list_data_file_rows_for_source(
        db: mariadb.SyncConnection,
        source: DataFileSource,
        datetime_min: datetime.datetime,
        datetime_max: datetime.datetime,
):
    """
    Return (observation_datetime, summary_s3_url, summary_stored_datetime) named tuples for one
    source's data_file rows within the datetime range, ordered by observation_datetime.  Naive
    bounds are assumed UTC; the tz-less DATETIME columns store UTC.
    """
    if datetime_min.tzinfo is not None:
        datetime_min = datetime_min.astimezone(datetime.timezone.utc)
    if datetime_max.tzinfo is not None:
        datetime_max = datetime_max.astimezone(datetime.timezone.utc)
    cursor = db.cursor(named_tuple=True)
    try:
        cursor.execute(
            'SELECT observation_datetime, summary_s3_url, summary_stored_datetime FROM data_file'
            ' WHERE source_id = ? AND observation_datetime >= ? AND observation_datetime <= ?'
            ' ORDER BY observation_datetime',
            (source.id, datetime_min.replace(tzinfo=None), datetime_max.replace(tzinfo=None)),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
    return rows


def synthesize_archive_file_row(
        db: mariadb.SyncConnection,
        source: DataFileSource,
        data_file_row,
        file_type: DataFileType,
        snapshot_objects_by_datetime: dict,
        dry_run: bool = False,
) -> ReconcileOutcome:
    """
    Ensure archive_file has a row for one data_file row of a crawled source; INSERT an inferred
    one if missing.

    The inferred row is born ingested: observation_datetime copied from data_file (non-NULL =
    the ingested marker), discovered_datetime backdated to summary_stored_datetime (else
    observation_datetime), and filename_derived_datetime + the derived source_url from the
    summary filename timestamp.  With dry_run, the INSERT is skipped but the outcome is INSERTED
    either way.
    """
    if data_file_row.summary_s3_url is None:
        logger.warning(
            f'cannot infer archive filename timestamp without summary_s3_url: '
            f'source={source.name} observation_datetime={data_file_row.observation_datetime}'
        )
        retval = ReconcileOutcome.NO_SUMMARY_S3_URL
        return retval
    summary_path = Path(urllib.parse.urlparse(data_file_row.summary_s3_url).path)
    filename_datetimestamp = SnapshotSummaryFile.infer_datetimestamp_from_path(summary_path)
    source_url = ArchiveSiteCrawler.derive_tar_url(
        base_url=source.base_url,
        datetimestamp=filename_datetimestamp,
    )
    snapshot = SnapshotFile(
        datetimestamp=filename_datetimestamp,
        local_storage_type=LocalStorageType.UNCACHED,
        source_url=source_url,
    )
    snapshot.source = source
    if snapshot.db_row_exists(db=db):
        logger.debug(f'already recorded: {source_url}')
        retval = ReconcileOutcome.ALREADY_RECORDED
        return retval
    observation_datetime = data_file_row.observation_datetime
    if data_file_row.summary_stored_datetime is not None:
        discovered_datetime = data_file_row.summary_stored_datetime
    else:
        discovered_datetime = observation_datetime
    our_s3_url = None
    our_size_bytes = None
    our_stored_datetime = None
    snapshot_object = snapshot_objects_by_datetime.get(filename_datetimestamp)
    if snapshot_object is not None:
        our_s3_url = f's3://{snapshot_object.bucket_name}/{snapshot_object.key}'
        our_size_bytes = snapshot_object.size
        our_stored_datetime = snapshot_object.last_modified
    if dry_run:
        logger.info(
            f'DRY-RUN would insert archive_file row: source={source.name} '
            f'source_url={source_url} our_s3_url={our_s3_url}'
        )
    else:
        snapshot.db_insert_ingested(
            db=db,
            file_type=file_type,
            discovered_datetime=discovered_datetime,
            observation_datetime=observation_datetime,
            our_s3_url=our_s3_url,
            our_size_bytes=our_size_bytes,
            our_stored_datetime=our_stored_datetime,
        )
        logger.info(f'inserted archive_file row: source={source.name} source_url={source_url}')
    retval = ReconcileOutcome.INSERTED
    return retval


if __name__ == '__main__':
    cli_entry_point()

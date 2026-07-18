#!/usr/bin/env python
"""
Crawl an HTTP index of RPKI archive data and download desirable files.  Upload those files to S3.

For each discovered RPKI archive TAR we don't already have, download it, validate it, extract the
rpki-client summary JSON, and upload the TAR to the snapshot bucket and the summary to the summary
bucket.  The file/storage/S3 concerns are delegated to SnapshotFile and SnapshotSummaryFile; this
module owns acquisition (crawling, downloading, retry) and orchestration.

--discover-only skips all downloading/uploading: the crawl's discovery phase upserts archive_file
rows instead (dedup on the (source_id, source_url) PK), inventorying what the archive publishes so
the backlog downloader can fetch missed snapshots later.  Requires --source-name and --db-*.

--download-backlog skips crawling entirely: the work queue is the source's archive_file rows where
observation_datetime IS NULL, processed oldest-first (download order affects downstream diffing).
Each download is paced by --sleep-between-downloads and updates the row's our_* columns plus the
observation_datetime ingest marker.  Requires --source-name and --db-*.

--filename-datetime-min / --filename-datetime-max restrict processing to snapshots whose filename
datetime falls within the given bounds.  They may be used separately or together.
"""
import argparse
import boto3
from datetime import datetime, timedelta, UTC
import dateutil.parser
from html.parser import HTMLParser
import json
import logging
import os
import re
import requests
from pathlib import Path
import tempfile
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import tenacity

from rpkilog.cleanup_policy import CleanupPolicy
from rpkilog.data_file_source import DataFileSource
from rpkilog.data_file_type import DataFileType
from rpkilog.local_storage_type import LocalStorageType
from rpkilog.snapshot_file import SnapshotFile
from rpkilog.snapshot_summary_file import SnapshotSummaryFile
from rpkilog.sqldb import db_connect, log_startup_args
from rpkilog.util import list_s3_snapshot_files_within_range, list_s3_summary_files_within_range

if TYPE_CHECKING:
    import mariadb


logger = logging.getLogger(__name__)


def _utc_aware(dt: datetime) -> datetime:
    """Return dt as tz-aware UTC; a naive input is assumed to already be UTC."""
    if dt.tzinfo is None:
        retval = dt.replace(tzinfo=UTC)
    else:
        retval = dt.astimezone(UTC)
    return retval


def parse_interval(text: str) -> timedelta:
    """
    Parse a CLI interval like '30s', '5m', or '1h' into a timedelta.  The number may be
    fractional; the s/m/h unit suffix is required so operators never guess a default unit.
    Raises ValueError on any other form (argparse renders that as an invalid-value error).
    """
    match = re.fullmatch(r'(\d+(?:\.\d+)?)([smh])', text.strip())
    if match is None:
        raise ValueError(f'invalid interval {text!r}; expected forms like 30s, 5m, or 1h')
    value = float(match.group(1))
    unit = match.group(2)
    match unit:
        case 's':
            retval = timedelta(seconds=value)
        case 'm':
            retval = timedelta(minutes=value)
        case 'h':
            retval = timedelta(hours=value)
    return retval


class MyHTMLParser(HTMLParser):
    '''
    Subclass for extracting useful URLs from RPKI archive web index pages.  Invoke like:

    parser = MyHTMLParser()
    parser.feed(page_blob)
    '''
    def __init__(self, page_url: str):
        super().__init__()
        self.href_urls = set()
        self.page_url = page_url

    def handle_starttag(
        self,
        tag,
        attrs,
    ):
        if tag != 'a':
            return
        attrdict = dict(attrs)
        if 'href' not in attrdict:
            return
        parsed = urlparse(attrdict['href'])
        if parsed.netloc:
            # absolute url
            found_url = attrdict['href']
        else:
            found_url = self.page_url + attrdict['href']
        self.href_urls.add(found_url)


class ArchiveSiteCrawler():
    '''
    Web-crawl an RPKI archive site.  Retrieve TAR files we haven't previously downloaded (by comparing)
    '''
    fetch_headers = {
        'User-Agent': 'rpkilog.com'
    }
    fetch_index_page_timeout = 10
    fetch_snapshot_timeout = 300

    @classmethod
    @tenacity.retry(before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
                    stop=tenacity.stop_after_attempt(5),
                    wait=tenacity.wait_random(min=3, max=10),
                    )
    def download_tar(cls, url: str, dest_path: Path):
        '''
        Download the RPKI archive TAR at url to dest_path, streaming to disk.

        Acquisition only: the per-archive transport + retry policy live here, NOT on SnapshotFile.
        Raises RuntimeError (with download progress) on failure so the caller aborts rather than
        silently skipping a file.  Retried by the tenacity decorator above.
        '''
        logger.info(f'DOWNLOADING {url}')
        count_bytes_downloaded = 0
        tar_response = None
        try:
            with requests.get(url=url, stream=True, timeout=cls.fetch_snapshot_timeout) as tar_response:
                tar_response.raise_for_status()
                with open(dest_path, 'wb') as dest_fh:
                    for chunk in tar_response.iter_content(chunk_size=1024 * 64):
                        count_bytes_downloaded += len(chunk)
                        dest_fh.write(chunk)
        except Exception as exc:
            if tar_response is not None and 'Content-Length' in tar_response.headers:
                content_length = int(tar_response.headers['Content-Length'])
                percent_downloaded = count_bytes_downloaded / content_length * 100
                raise RuntimeError(
                    f'Failed downloading {url} after {percent_downloaded:.0f}%'
                    f' bytes {count_bytes_downloaded} of {content_length}'
                ) from exc
            raise RuntimeError(
                f'Failed downloading {url} after {count_bytes_downloaded} bytes'
            ) from exc

    @classmethod
    def process_tar_url(
        cls,
        url: str,
        datetimestamp: datetime,
        db: 'mariadb.SyncConnection' = None,
        source: DataFileSource = None,
        summarize: bool = True,
    ) -> str | None:
        '''
        Download one archive TAR, validate it, extract its summary, and upload both the TAR (to the
        snapshot bucket) and the summary (to the summary bucket).

        Acquisition (download + retry) lives in download_tar(); every file/storage/S3 concern is
        delegated to SnapshotFile / SnapshotSummaryFile.  SnapshotFile.default_s3_base_url and
        SnapshotSummaryFile.default_s3_base_url must already be set (see wrapped_entry_point).

        When db + source are given (the backlog downloader), the snapshot's archive_file row is
        updated after uploading: db_update_our_copy() records the stored-copy columns, and
        db_update_ingested() stamps observation_datetime from the summary's authoritative
        metadata.buildtime.  With summarize=False (--no-summarize-after-download) the summary is
        not extracted or uploaded and observation_datetime stays NULL, so the row remains in the
        backlog for a later summarizing run (which re-downloads the TAR).

        Returns the snapshot's S3 key on success, or None when the TAR failed validation and was
        skipped (a later run re-downloads it).  Raises on download or upload failure (so the job
        aborts rather than silently skipping a file).  All local temp files live under a
        TemporaryDirectory that is removed on return.
        '''
        with tempfile.TemporaryDirectory() as work_dir_str:
            work_dir = Path(work_dir_str)
            snapshot = SnapshotFile(
                datetimestamp=datetimestamp,
                local_storage_dir=work_dir,
                local_storage_type=LocalStorageType.SNAPSHOT_TGZ,
                source_url=url,
                cleanup_policy=CleanupPolicy.CLEANUP_NEVER,
            )
            if source is not None:
                snapshot.source = source
            cls.download_tar(url=url, dest_path=snapshot.local_filepath_tgz)
            if not snapshot.validate_tar():
                logger.warning(f'TAR_FAILED_VALIDATION skipping {url}')
                return None
            if summarize:
                summary = snapshot.extract_summary_file(output_dir=work_dir)
                summary.cleanup_policy = CleanupPolicy.CLEANUP_NEVER
            logger.info(f'UPLOADING snapshot {snapshot.default_filename} to snapshot bucket')
            snapshot.s3_upload()
            if summarize:
                logger.info(f'UPLOADING summary {summary.default_filename} to summary bucket')
                summary.s3_upload()
            if db is not None:
                snapshot.db_update_our_copy(db=db)
                if summarize:
                    snapshot.db_update_ingested(
                        db=db, observation_datetime=summary.observation_datetime,
                    )
            retstr = snapshot.s3_path
        return retstr

    @classmethod
    def derive_tar_url(cls, base_url: str, datetimestamp: datetime) -> str:
        '''
        Map a source's base_url + a FILENAME-derived datetimestamp to the canonical archive TAR
        URL, e.g. https://josephine.sobornost.net/rpkidata/ + 2026-05-01T00:54:38Z ->
        https://josephine.sobornost.net/rpkidata/2026/05/01/rpki-20260501T005438Z.tgz

        This is the inverse of the crawl: the day-page path (%Y/%m/%d/) matches
        fetch_tar_urls_from_archive_site() and the filename matches
        SnapshotFile.default_filename_strftime_expression, so a derived URL is byte-for-byte
        identical to the same file's crawler-discovered URL.  That identity matters because
        archive_file dedups on source_url: any mismatch would silently split rows.  Pass the
        filename timestamp (e.g. from a summary S3 key), NOT the metadata buildtime, which
        differs by a few seconds.  A naive datetimestamp is assumed UTC.
        '''
        if datetimestamp.tzinfo is not None:
            datetimestamp = datetimestamp.astimezone(UTC)
        if not base_url.endswith('/'):
            base_url = base_url + '/'
        retstr = (
            base_url
            + datetimestamp.strftime('%Y/%m/%d/')
            + datetimestamp.strftime(SnapshotFile.default_filename_strftime_expression)
        )
        return retstr

    @classmethod
    def fetch_tar_urls_from_archive_site(
        cls,
        site_root: str,
        start_date: datetime,
        max_date: datetime = None,
    ) -> set:
        '''
        Discovery phase: crawl the specified RPKI archive site_root and get the URLs of TARs
        between start_date and max_date (default: now; NOT an eager parameter default, which
        would be evaluated once at import time and go stale in a long-lived process).
        Depends on the URL scheme for index pages being site_root/YYYY/MM/DD/.  Naive datetimes
        are assumed UTC.  Every UTC day from start_date through max_date inclusive is fetched;
        a 404 on a day page is tolerated (e.g. today's page before the first snapshot).

        Return the URLs in a set.
        '''
        start_date = _utc_aware(start_date)
        if max_date is None:
            max_date = datetime.now(UTC)
        else:
            max_date = _utc_aware(max_date)
        discovered_tar_urls = set()
        for day_offset in range((max_date.date() - start_date.date()).days + 1):
            day = start_date + timedelta(days=day_offset)
            url_fragment = day.strftime('%Y/%m/%d/')  # e.g. 2026/05/01
            day_page_url = site_root + ('' if site_root.endswith('/') else '/') + url_fragment
            daily_tar_file_urls = cls.fetch_tar_urls_from_day_page(
                day_page_url=day_page_url,
                site_root=site_root,
                start_date=start_date,
            )
            for tar_url in daily_tar_file_urls:
                discovered_tar_urls.add(tar_url)
        return discovered_tar_urls

    @classmethod
    @tenacity.retry(before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
                    stop=tenacity.stop_after_attempt(15),
                    wait=tenacity.wait_random(min=1, max=3),
                    )
    def fetch_tar_urls_from_day_page(cls, day_page_url: str, site_root: str, start_date: datetime) -> set:
        '''
        Fetch the "day page," which contains a list of files for a given date.
        
        Parse that page and find all the URLs of RPKI archive TARs on the page.
        Ignore any RPKI archive filenames with datetime-based name before start_date.

        Return a set containing the TAR URLs.
        '''
        logger.info(f'FETCHING day page {day_page_url}')
        urls_on_day_page = cls.fetch_page_href_urls(page_url=day_page_url)
        tar_file_urls = set()
        for url in sorted(urls_on_day_page):
            if not url.startswith(day_page_url):
                continue
            try:
                tar_datetime = SnapshotFile.infer_datetimestamp_from_path(Path(url))
            except ValueError:
                # not an 'rpki-...Z.tgz' link (parent-dir links, other files, etc.)
                continue
            if tar_datetime < _utc_aware(start_date):
                logger.debug(f'Not crawling into {url} because it is before {start_date.isoformat()}')
                continue
            tar_file_urls.add(url)
        return tar_file_urls

    @classmethod
    def fetch_page_href_urls(cls, page_url: str) -> set:
        'Fetch page_url, parse it, and return a set of all the a-tag href attributes found on the page.'
        try:
            res = requests.get(url=page_url, timeout=cls.fetch_index_page_timeout, headers=cls.fetch_headers)
            if res.status_code == 404:
                logger.info(f'404 when fetching {page_url} which may be normal if that date is in the'
                            f' future, due to sloppy date arithmetic when fetching index pages')
                return set()
            res.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f'Exception fetching {page_url}') from exc
        parser = MyHTMLParser(page_url=page_url)
        parser.feed(res.text)
        return parser.href_urls

    @classmethod
    def cli_entry_point(cls):
        realtime_initial = datetime.now(UTC)
        logging.basicConfig(
            level='INFO',
            datefmt='%Y-%m-%dT%H:%M:%S',
            format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
        )
        secret_arg_dests = set()
        ap = argparse.ArgumentParser()
        ap.add_argument('--debug', action='store_true', help='Break to debugger after parsing arguments')
        ap.add_argument('--debug-save-urls', type=Path,
                        help='Save the list of available tar file URLs to given file')
        ap.add_argument('--discover-only', action='store_true',
                        help='Only inventory the archive site into SQL archive_file rows; '
                             'download nothing (requires --source-name and --db-* arguments)')
        ap.add_argument('--download-backlog', action='store_true',
                        help='Do not crawl; download+process the archive_file backlog '
                             '(observation_datetime NULL) oldest-first (requires --source-name '
                             'and --db-* arguments)')
        ap.add_argument('--dry-run', action='store_true',
                        help='Report what would be done -- archive_file inserts '
                             '(--discover-only) or downloads/uploads (crawl or '
                             '--download-backlog) -- without doing it')
        ap.add_argument('--fetch-snapshot-timeout', default=300, type=float,
                        help='Timeout, in seconds, for fetching snapshot files (default: 300)')
        ap.add_argument('--maximum-crawl-age', type=float, default=14,
                        help='Crawl at most this many days (default: 14)')
        ap.add_argument('--minimum-file-age', type=float,
                        help='Defer snapshots younger than this many minutes (default: 10); works '
                             'around archives that write files into public dirs progressively')
        ap.add_argument('--no-summarize-after-download', action='store_true',
                        help='With --download-backlog: upload the TAR but skip summary '
                             'extraction/upload; the row stays backlogged for a later '
                             'summarizing run')
        # db (only needed with --source-name today; --discover-only will also require them)
        ap.add_argument('--db-host', type=str, help='MariaDB host')
        ap.add_argument('--db-port', default=3306, type=int, help='MariaDB port (default: 3306)')
        ap.add_argument('--db-user', type=str, help='MariaDB user')
        db_password_action = ap.add_argument(
            '--db-password', type=str, help='MariaDB password (or use env RPKILOG_DB_PASSWORD)',
        )
        secret_arg_dests.add(db_password_action.dest)
        ap.add_argument('--db-name', type=str, help='MariaDB database name')
        ap.add_argument('--s3-snapshot-bucket-name',
                        help='S3 bucket for uploading RPKI TAR files (required unless --discover-only)')
        ap.add_argument('--s3-snapshot-summary-bucket-name',
                        help='S3 bucket containing JSON summary files (required unless --discover-only)')
        ap.add_argument('--site-root',
                        help='Root of web archive site (alternative: --source-name)')
        ap.add_argument('--sleep-between-downloads', type=parse_interval,
                        help='With --download-backlog: pause between downloads to pace the '
                             'archive site, e.g. 30s, 5m, or 1h (each sleep is logged)')
        ap.add_argument('--source-name',
                        help='Crawl the `source` DB row with this name, using its base_url as '
                             'the site root -- guarantees discovered URLs match archive_file '
                             'rows byte-for-byte (requires --db-* arguments)')
        ap.add_argument('--start-date', type=dateutil.parser.parse,
                        help='Do not download snapshots earlier than this date')
        ap.add_argument('--filename-datetime-min', type=dateutil.parser.parse,
                        help='Only process snapshots whose filename datetime is >= this (optional)')
        ap.add_argument('--filename-datetime-max', type=dateutil.parser.parse,
                        help='Only process snapshots whose filename datetime is <= this (optional)')
        ap.add_argument('--job-max-runtime', type=float, help='Max runtime in seconds (default: unlimited)')
        ap.add_argument('--job-max-downloads', default=2, type=int,
                        help='Max files to download before stopping (default: 2)')
        args = ap.parse_args()
        if (args.site_root is None) == (args.source_name is None):
            ap.error('exactly one of --site-root or --source-name is required')
        if args.discover_only and args.download_backlog:
            ap.error('--discover-only and --download-backlog are mutually exclusive')
        if args.discover_only and args.source_name is None:
            ap.error('--discover-only requires --source-name (archive_file rows need a source_id)')
        if args.download_backlog and args.source_name is None:
            ap.error('--download-backlog requires --source-name (its work queue is that '
                     'source\'s archive_file rows)')
        if not args.discover_only and (
                args.s3_snapshot_bucket_name is None or args.s3_snapshot_summary_bucket_name is None):
            ap.error('--s3-snapshot-bucket-name and --s3-snapshot-summary-bucket-name are '
                     'required unless --discover-only')
        if args.debug:
            breakpoint()
        log_startup_args(args=args, secret_dests=secret_arg_dests)
        if args.job_max_runtime is not None:
            job_deadline = datetime.now(UTC) + timedelta(seconds=args.job_max_runtime)
        else:
            job_deadline = None
        if args.minimum_file_age is not None:
            minimum_file_age = timedelta(minutes=args.minimum_file_age)
        else:
            minimum_file_age = None

        # Resolve the site root: prefer the DB source row's base_url over a hand-typed URL, so
        # discovered source_url values match derive_tar_url() inference byte-for-byte.
        site_root = args.site_root
        db = None
        source = None
        if args.source_name is not None:
            db = db_connect(args)
            source = DataFileSource.get_by_name(args.source_name, db=db)
            if source.base_url is None:
                ap.error(f'source {source.name!r} has no base_url; it is not a crawled archive')
            site_root = source.base_url

        if args.download_backlog:
            wrapped_retval = cls.download_backlog_entry_point(
                db=db,
                source=source,
                s3_snapshot_bucket_name=args.s3_snapshot_bucket_name,
                s3_snapshot_summary_bucket_name=args.s3_snapshot_summary_bucket_name,
                fetch_snapshot_timeout=args.fetch_snapshot_timeout,
                filename_datetime_min=args.filename_datetime_min,
                filename_datetime_max=args.filename_datetime_max,
                job_deadline=job_deadline,
                job_max_downloads=args.job_max_downloads,
                sleep_between_downloads=args.sleep_between_downloads,
                summarize=not args.no_summarize_after_download,
                dry_run=args.dry_run,
            )
        elif args.discover_only:
            wrapped_retval = cls.discover_only_entry_point(
                db=db,
                source=source,
                site_root=site_root,
                start_date=args.start_date,
                maximum_crawl_age=args.maximum_crawl_age,
                filename_datetime_min=args.filename_datetime_min,
                filename_datetime_max=args.filename_datetime_max,
                dry_run=args.dry_run,
            )
        else:
            wrapped_retval = cls.wrapped_entry_point(
                s3_snapshot_bucket_name=args.s3_snapshot_bucket_name,
                s3_snapshot_summary_bucket_name=args.s3_snapshot_summary_bucket_name,
                site_root=site_root,
                debug_save_urls=args.debug_save_urls,
                fetch_snapshot_timeout=args.fetch_snapshot_timeout,
                start_date=args.start_date,
                filename_datetime_min=args.filename_datetime_min,
                filename_datetime_max=args.filename_datetime_max,
                minimum_file_age=minimum_file_age,
                maximum_crawl_age=args.maximum_crawl_age,
                job_deadline=job_deadline,
                job_max_downloads=args.job_max_downloads,
                dry_run=args.dry_run,
            )
        print(json.dumps(wrapped_retval, indent=4))
        times = os.times()
        realtime_final = datetime.now(UTC)
        realtime_elapsed = realtime_final - realtime_initial
        try:
            import psutil
            memory_use_rss_mb = psutil.Process().memory_info().rss / 1048576
            logger.info(f'RAM memory_use_rss_mb={memory_use_rss_mb:.0f}')
        except Exception:
            logger.warning('Unable to invoke psutil.Process().memory_info() to get RAM use.')
        logger.info(f'TIMES usr={times.user} sys={times.system} realtime={realtime_elapsed.total_seconds()}')

    @classmethod
    def wrapped_entry_point(
        cls,
        s3_snapshot_bucket_name: str,
        s3_snapshot_summary_bucket_name: str,
        site_root: str,
        debug_save_urls: Path | None = None,
        fetch_snapshot_timeout: float | None = None,
        start_date: datetime | None = None,
        filename_datetime_min: datetime | None = None,
        filename_datetime_max: datetime | None = None,
        minimum_file_age: timedelta | None = None,
        maximum_crawl_age: float | None = None,
        job_deadline: datetime | None = None,
        job_max_downloads: int | None = None,
        dry_run: bool = False,
    ):
        '''
        Invoked by other entry points, e.g. cli_entry_point.  Orchestrates the three phases:
        already-have filter (s3_already_have_by_datetime), discovery
        (fetch_tar_urls_from_archive_site), and acquisition (acquire_tar_urls).

        Web-crawl the given site_root and find relevant RPKI archive TAR URLs in the HTML a-tags.
        Crawling will try to avoid requesting pages that list only TAR files before start_date.

        Get the list of already-downloaded RPKI TARs by listing the s3_snapshot_summary_bucket
        and comparing the date-based filenames, for example:
            snapshot_summary: 20211121T000709Z.json.bz2
            snapshot: rpki-20211121T000709Z.tgz

        Also get the list of recently-downloaded TARs from s3_snapshot_bucket, in case there are
        some to-be-processed TARs already there.

        In ascending date-based order, download any TAR files we haven't previously processed,
        except TAR files with a datetime-based filename before start_date or outside the optional
        [filename_datetime_min, filename_datetime_max] bounds (each bound applies independently).

        For each such TAR, process_tar_url() uploads the TAR to s3_snapshot_bucket_name and its
        extracted summary to s3_snapshot_summary_bucket_name (both via SnapshotFile /
        SnapshotSummaryFile, whose default S3 base URLs are set below from the bucket names).

        Abort if a download fails, or if an upload fails, to avoid skipping any files.
        '''
        SnapshotFile.default_s3_base_url_set(f's3://{s3_snapshot_bucket_name}/')
        SnapshotSummaryFile.default_s3_base_url_set(f's3://{s3_snapshot_summary_bucket_name}/')

        if filename_datetime_min is not None:
            filename_datetime_min = _utc_aware(filename_datetime_min)
        if filename_datetime_max is not None:
            filename_datetime_max = _utc_aware(filename_datetime_max)
        if job_deadline is not None:
            job_deadline = _utc_aware(job_deadline)

        if maximum_crawl_age:
            maximum_crawl_age = timedelta(days=float(maximum_crawl_age))
        else:
            maximum_crawl_age = timedelta(days=14)
        if start_date is None:
            start_date = datetime.now(UTC) - maximum_crawl_age
        else:
            start_date = _utc_aware(start_date)
        if minimum_file_age is None:
            minimum_file_age = timedelta(minutes=10)
        if fetch_snapshot_timeout:
            cls.fetch_snapshot_timeout = float(fetch_snapshot_timeout)

        already_have_by_datetime = cls.s3_already_have_by_datetime(
            s3_snapshot_bucket_name=s3_snapshot_bucket_name,
            s3_snapshot_summary_bucket_name=s3_snapshot_summary_bucket_name,
            start_datetime=start_date - timedelta(days=1),
        )

        # discovery phase: all rpki tar file URLs, after start_date, on the archive site
        archive_site_available_tar_file_urls = cls.fetch_tar_urls_from_archive_site(
            site_root=site_root,
            start_date=start_date,
        )
        logger.info(f'FETCHED {len(archive_site_available_tar_file_urls)} URLs after {start_date} from {site_root}')
        if debug_save_urls:
            with open(debug_save_urls, 'w') as save_url_fh:
                json.dump(
                    sorted(list(archive_site_available_tar_file_urls)),
                    save_url_fh,
                    sort_keys=True,
                    indent=4
                )

        uploaded = cls.acquire_tar_urls(
            available_tar_urls=archive_site_available_tar_file_urls,
            already_have_by_datetime=already_have_by_datetime,
            filename_datetime_min=filename_datetime_min,
            filename_datetime_max=filename_datetime_max,
            minimum_file_age=minimum_file_age,
            job_deadline=job_deadline,
            job_max_downloads=job_max_downloads,
            dry_run=dry_run,
        )
        return uploaded

    @classmethod
    def s3_already_have_by_datetime(
        cls,
        s3_snapshot_bucket_name: str,
        s3_snapshot_summary_bucket_name: str,
        start_datetime: datetime,
    ) -> dict:
        '''
        Already-have filter phase: list the snapshot and summary buckets from start_datetime
        onward and return {filename-derived datetime: ObjectSummary} covering files present in
        EITHER bucket, e.g.:
            snapshot_summary: 20211121T000709Z.json.bz2
            snapshot: rpki-20211121T000709Z.tgz
        '''
        logger.info('LISTING relevant s3 buckets')
        retval = dict()

        snapshot_bucket = boto3.resource('s3').Bucket(s3_snapshot_bucket_name)
        snapshots = list_s3_snapshot_files_within_range(
            bucket=snapshot_bucket,
            start_datetime=start_datetime,
            end_datetime=datetime.now(UTC),
        )
        for buckobj in snapshots:
            try:
                buckobj_datetime = SnapshotFile.infer_datetimestamp_from_path(Path(buckobj.key))
            except ValueError:
                logger.warning(f'UNMATCHED key in snapshot bucket {snapshot_bucket} : {buckobj.key}')
                continue
            retval[buckobj_datetime] = buckobj

        summary_bucket = boto3.resource('s3').Bucket(s3_snapshot_summary_bucket_name)
        summaries = list_s3_summary_files_within_range(
            bucket=summary_bucket,
            start_datetime=start_datetime,
            end_datetime=datetime.now(UTC),
        )
        for buckobj in summaries:
            try:
                buckobj_datetime = SnapshotSummaryFile.infer_datetimestamp_from_path(Path(buckobj.key))
            except ValueError:
                logger.warning(f'UNMATCHED key in summary bucket {summary_bucket} : {buckobj.key}')
                continue
            retval[buckobj_datetime] = buckobj
        logger.info(f'LISTED {len(snapshots)} snapshots and {len(summaries)} summaries in S3 buckets.')
        return retval

    @classmethod
    def acquire_tar_urls(
        cls,
        available_tar_urls,
        already_have_by_datetime: dict,
        filename_datetime_min: datetime = None,
        filename_datetime_max: datetime = None,
        minimum_file_age: timedelta = None,
        job_deadline: datetime = None,
        job_max_downloads: int = None,
        dry_run: bool = False,
    ) -> list:
        '''
        Acquisition phase: in ascending URL (= chronological) order, run process_tar_url()
        (download/validate/extract/upload) for each TAR not in already_have_by_datetime and not
        excluded by the optional filename bounds or minimum_file_age; stop at job_deadline or
        job_max_downloads.  Returns the uploaded snapshot S3 keys.

        With dry_run, every filter (and the job_max_downloads limit) applies as usual, but
        instead of downloading, each would-be acquisition is logged and its would-be snapshot
        key is returned -- so the output mirrors what a real run would do.
        '''
        uploaded = list()
        for available_tar_url in sorted(available_tar_urls):
            try:
                available_tar_datetime = SnapshotFile.infer_datetimestamp_from_path(Path(available_tar_url))
            except ValueError:
                logger.warning(f'UNMATCHED available_tar_url {available_tar_url}')
                continue
            if available_tar_datetime in already_have_by_datetime:
                # we've previously downloaded this tar from the archive site
                continue
            if filename_datetime_min is not None and available_tar_datetime < filename_datetime_min:
                continue
            if filename_datetime_max is not None and available_tar_datetime > filename_datetime_max:
                continue
            available_tar_age = datetime.now(UTC) - available_tar_datetime
            if minimum_file_age is not None and available_tar_age < minimum_file_age:
                # file is too young; skip it.  A future iteration will download it.
                # This is a workaround for some archive sites writing files into their public directories
                # progressively as they're built, rather than moving files into it when complete.
                logger.info(f'DEFER too-young available_tar_url {available_tar_url}')
                continue

            # new tar we need from archive site
            if job_deadline is not None and job_deadline < datetime.now(UTC):
                # We're past the deadline.  Could run out of lambda execution time.  Stop here.
                logger.warning(f'JOB_DEADLINE reached.')
                break
            if job_max_downloads is not None and job_max_downloads <= len(uploaded):
                logger.warning(f'JOB_MAX_DOWNLOADS reached.')
                break

            if dry_run:
                snapshot_key = available_tar_datetime.strftime(
                    SnapshotFile.default_filename_strftime_expression
                )
                logger.info(f'DRY-RUN would download {available_tar_url} and upload {snapshot_key}')
            else:
                snapshot_key = cls.process_tar_url(url=available_tar_url, datetimestamp=available_tar_datetime)
                if snapshot_key is None:
                    continue
            uploaded.append(snapshot_key)

        return uploaded

    @classmethod
    def discover_only_entry_point(
        cls,
        db: 'mariadb.SyncConnection',
        source: DataFileSource,
        site_root: str,
        start_date: datetime | None = None,
        maximum_crawl_age: float | None = None,
        filename_datetime_min: datetime | None = None,
        filename_datetime_max: datetime | None = None,
        dry_run: bool = False,
    ) -> dict:
        '''
        Discover-only mode: crawl the archive site's index pages within the datetimestamp range
        and upsert archive_file rows, downloading nothing.  Dedup is the (source_id, source_url)
        PK via SnapshotFile.db_row_exists(); inserts via db_insert_discovered(), stamping
        discovered_datetime, filename_derived_datetime, and file_type_id.  The resulting backlog
        (observation_datetime IS NULL) is what the rate-limited backlog downloader will fetch.

        With dry_run, the crawl and the db_row_exists() dedup check run normally (so tallies are
        accurate), but the INSERT is skipped; a row is counted discovered either way.

        The crawled day-page range runs from filename_datetime_min (else start_date, else
        now - maximum_crawl_age [default 14 days]) through filename_datetime_max (else now).
        Returns outcome tallies for the CLI's JSON output.
        '''
        if maximum_crawl_age:
            maximum_crawl_age = timedelta(days=float(maximum_crawl_age))
        else:
            maximum_crawl_age = timedelta(days=14)
        if filename_datetime_min is not None:
            filename_datetime_min = _utc_aware(filename_datetime_min)
        if filename_datetime_max is not None:
            filename_datetime_max = _utc_aware(filename_datetime_max)
        if filename_datetime_min is not None:
            crawl_start = filename_datetime_min
        elif start_date is not None:
            crawl_start = _utc_aware(start_date)
        else:
            crawl_start = datetime.now(UTC) - maximum_crawl_age

        file_type = DataFileType.get_by_name(SnapshotFile.sql_file_type_name, db=db)
        available_tar_urls = cls.fetch_tar_urls_from_archive_site(
            site_root=site_root,
            start_date=crawl_start,
            max_date=filename_datetime_max,
        )
        logger.info(f'FETCHED {len(available_tar_urls)} URLs from {site_root}')
        counts = {
            'discovered': 0,
            'already_recorded': 0,
            'out_of_range': 0,
        }
        for available_tar_url in sorted(available_tar_urls):
            try:
                datetimestamp = SnapshotFile.infer_datetimestamp_from_path(Path(available_tar_url))
            except ValueError:
                logger.warning(f'UNMATCHED available_tar_url {available_tar_url}')
                continue
            if filename_datetime_min is not None and datetimestamp < filename_datetime_min:
                counts['out_of_range'] += 1
                continue
            if filename_datetime_max is not None and datetimestamp > filename_datetime_max:
                counts['out_of_range'] += 1
                continue
            snapshot = SnapshotFile(
                datetimestamp=datetimestamp,
                local_storage_type=LocalStorageType.UNCACHED,
                source_url=available_tar_url,
            )
            snapshot.source = source
            if snapshot.db_row_exists(db=db):
                logger.debug(f'already recorded: {available_tar_url}')
                counts['already_recorded'] += 1
                continue
            if dry_run:
                logger.info(f'DRY-RUN would insert archive_file row: {available_tar_url}')
            else:
                snapshot.db_insert_discovered(db=db, file_type=file_type)
                logger.info(f'DISCOVERED inserted archive_file row: {available_tar_url}')
            counts['discovered'] += 1
        if dry_run:
            run_mode = 'DRY-RUN '
        else:
            run_mode = ''
        logger.info(
            f"{run_mode}discover-only complete: discovered={counts['discovered']} "
            f"already_recorded={counts['already_recorded']} out_of_range={counts['out_of_range']}"
        )
        retval = counts
        return retval

    @classmethod
    def download_backlog_entry_point(
        cls,
        db: 'mariadb.SyncConnection',
        source: DataFileSource,
        s3_snapshot_bucket_name: str,
        s3_snapshot_summary_bucket_name: str,
        fetch_snapshot_timeout: float | None = None,
        filename_datetime_min: datetime | None = None,
        filename_datetime_max: datetime | None = None,
        job_deadline: datetime | None = None,
        job_max_downloads: int | None = None,
        sleep_between_downloads: timedelta | None = None,
        summarize: bool = True,
        dry_run: bool = False,
    ) -> dict:
        '''
        Download-backlog mode: no crawling; the work queue is the source's archive_file rows
        where observation_datetime IS NULL (via db_select_within_range(ingested=False)),
        processed OLDEST FIRST -- download order matters because downstream diffing consumes
        the resulting summaries chronologically.

        Each row runs through process_tar_url() with db + source, which uploads the TAR (and,
        unless summarize is False, its summary) and updates the row: our_* stored-copy columns
        plus the observation_datetime ingest marker.  A TAR failing validation is tallied and
        left backlogged for a later run.  sleep_between_downloads paces the archive site --
        each pause is logged with its duration before sleeping.  job_deadline and
        job_max_downloads bound the run just like crawl mode.

        With dry_run, rows are listed and tallied (job_max_downloads still applies) but nothing
        is downloaded and there is no sleeping.  Returns tallies plus the uploaded (or would-be)
        snapshot S3 keys for the CLI's JSON output.
        '''
        SnapshotFile.default_s3_base_url_set(f's3://{s3_snapshot_bucket_name}/')
        SnapshotSummaryFile.default_s3_base_url_set(f's3://{s3_snapshot_summary_bucket_name}/')
        if fetch_snapshot_timeout:
            cls.fetch_snapshot_timeout = float(fetch_snapshot_timeout)
        if job_deadline is not None:
            job_deadline = _utc_aware(job_deadline)
        backlog = SnapshotFile.db_select_within_range(
            db=db,
            source=source,
            datetime_min=filename_datetime_min,
            datetime_max=filename_datetime_max,
            ingested=False,
        )
        logger.info(
            f'BACKLOG {len(backlog)} archive_file rows with observation_datetime NULL'
            f' for source {source.name}'
        )
        counts = {
            'backlog_rows': len(backlog),
            'failed_validation': 0,
        }
        uploaded = list()
        downloads_performed = 0
        for snapshot in backlog:
            if job_deadline is not None and job_deadline < datetime.now(UTC):
                logger.warning('JOB_DEADLINE reached.')
                break
            if job_max_downloads is not None and job_max_downloads <= downloads_performed:
                logger.warning('JOB_MAX_DOWNLOADS reached.')
                break
            if dry_run:
                snapshot_key = snapshot.datetimestamp.strftime(
                    SnapshotFile.default_filename_strftime_expression
                )
                logger.info(f'DRY-RUN would download {snapshot.source_url} and upload {snapshot_key}')
                downloads_performed += 1
                uploaded.append(snapshot_key)
                continue
            if sleep_between_downloads is not None and downloads_performed > 0:
                sleep_seconds = sleep_between_downloads.total_seconds()
                logger.info(f'SLEEPING {sleep_seconds:g}s between downloads')
                time.sleep(sleep_seconds)
            snapshot_key = cls.process_tar_url(
                url=snapshot.source_url,
                datetimestamp=snapshot.datetimestamp,
                db=db,
                source=source,
                summarize=summarize,
            )
            downloads_performed += 1
            if snapshot_key is None:
                counts['failed_validation'] += 1
                continue
            uploaded.append(snapshot_key)
        counts['uploaded'] = uploaded
        if dry_run:
            run_mode = 'DRY-RUN '
        else:
            run_mode = ''
        logger.info(
            f"{run_mode}download-backlog complete: uploaded={len(uploaded)} "
            f"failed_validation={counts['failed_validation']} backlog_rows={counts['backlog_rows']}"
        )
        retval = counts
        return retval

#!/usr/bin/env python
"""
Given a Routinator base URL, fetch a VRP snapshot.  Optionally, upload it to S3.

Optionally, produce a *summary* in our internal format.  Optionally, upload that to S3.
"""
import argparse
from datetime import datetime, timezone
import logging
import pdb
import urllib.parse
import urllib.request
from pathlib import Path

from rpkilog.summary_file import SummaryFile
from rpkilog.routinator_snapshot_file import RoutinatorSnapshotFile

logger = logging.getLogger()


def cli_entry_point(args_passed=None):
    startup_time = datetime.now(timezone.utc)
    default_filename_prefix = startup_time.strftime('%Y-%m-%dT%H%M%SZ')
    ap = argparse.ArgumentParser(
        description='Given a Routinator base URL, fetch a VRP snapshot.  Optionally summarize it.', )
    ap.add_argument('--debug', action='store_true', help='break to debugger upon start-up')
    ap.add_argument('--routinator-base-url', type=urllib.parse.urlparse,
                    default='http://localhost:8323', help='routinator base url like http://localhost:8323')
    ap.add_argument('--snapshot-dir', required=True, type=Path, help='Destination directory for snapshot')
    ap.add_argument('--snapshot-keep', action='store_true', default=False, help='Keep snapshot on disk after completion (default NO)')
    ap.add_argument('--snapshot-upload', type=urllib.parse.urlparse, help='S3 upload prefix like s3://buck/snap-')
    ap.add_argument('--summary-dir', type=Path, help='Destination directory for summary')
    ap.add_argument('--summary-keep', action='store_true', default=False, help='Keep summary on disk after completion (default NO)')
    ap.add_argument('--summary-upload', type=urllib.parse.urlparse, help='S3 upload prefix like s3://buck/sum-')
    args = ap.parse_args(args_passed)
    if args.debug:
        pdb.set_trace()
    logging.basicConfig(
        datefmt='%Y-%m-%dT%H:%M:%S',
        format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
    )

    RoutinatorSnapshotFile.default_local_storage_dir = args.snapshot_dir.expanduser()
    if args.snapshot_upload:
        RoutinatorSnapshotFile.default_s3_base_url_set(args.snapshot_upload)
    if args.summary_dir:
        SummaryFile.default_local_storage_dir = args.summary_dir.expanduser()
    if args.summary_upload:
        SummaryFile.default_s3_base_url_set(args.summary_upload)

    snapshot_obj = RoutinatorSnapshotFile.fetch_from_routinator()
    logger.info(f'downloaded snapshot {snapshot_obj.local_filepath_uncompressed}')
    if args.snapshot_upload:
        snapshot_obj.s3_upload()
    snapshot_obj.cleanup_upon_destroy = not args.snapshot_keep

    summary_obj = snapshot_obj.summarize_to_file()
    logger.info(f'summarized to {summary_obj.local_filepath_bz2}')
    if args.summary_upload:
        summary_obj.s3_upload()
    summary_obj.cleanup_upon_destroy = not args.summary_keep


if __name__ == '__main__':
    import sys
    cli_entry_point(sys.argv[1:])

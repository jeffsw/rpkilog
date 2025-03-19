#!/usr/bin/env python
"""
Given a Routinator base URL, fetch a VRP snapshot.  Optionally, upload it to S3.

Optionally, produce a *summary* in our internal format.  Optionally, upload that to S3.
"""
import argparse
import bz2
from datetime import datetime, timezone
import logging
import pdb
import urllib.parse
import urllib.request
from pathlib import Path

from rpkilog.routinator_snapshot_file import RoutinatorSnapshotFile

logger = logging.getLogger()


def cli_entry_point(args_passed):
    startup_time = datetime.now(timezone.utc)
    default_filename_prefix = startup_time.strftime('%Y-%m-%dT%H%M%SZ')
    ap = argparse.ArgumentParser(
        description='Given a Routinator base URL, fetch a VRP snapshot.  Optionally summarize it.', )
    ap.add_argument('--debug', action='store_true', help='break to debugger upon start-up')
    ap.add_argument('--routinator-base-url', type=urllib.parse.urlparse,
                    default='http://localhost:8323', help='routinator base url like http://localhost:8323')
    ap.add_argument('--snapshot-dir', required=True, type=Path, help='Destination directory for snapshot')
    ap.add_argument('--snapshot-keep', default=False, help='Keep snapshot on disk after completion?')
    ap.add_argument('--snapshot-upload', type=urllib.parse.urlparse, help='S3 upload prefix like s3://buck/snap-')
    ap.add_argument('--summary-dir', type=Path, help='Destination directory for summary')
    ap.add_argument('--summary-upload', type=urllib.parse.urlparse, help='S3 upload prefix like s3://buck/sum-')
    args = ap.parse_args(args_passed)
    if args.debug:
        pdb.set_trace()

    RoutinatorSnapshotFile.default_local_storage_dir = args.snapshot_dir
    if args.snapshot_upload:
        RoutinatorSnapshotFile.default_s3_base_url = args.snapshot_upload
    snapshot_obj = RoutinatorSnapshotFile.fetch_from_routinator()
    if args.snapshot_upload:
        snapshot_obj.s3_upload()

    # TODO: summarize

    if not args.snapshot_keep:
        snapshot_obj.unlink_cached()

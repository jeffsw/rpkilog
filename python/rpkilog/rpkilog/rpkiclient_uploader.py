"""
Upload rpkiclient's output/json snapshot-summary file to S3, driving a SnapshotSummaryFile so the
filename derivation, size validation, bzip2 compression, and S3 upload all live in one place.
"""
import argparse
import json
import logging
from pathlib import Path
import time

import psutil

from rpkilog.cleanup_policy import CleanupPolicy
from rpkilog.local_storage_type import LocalStorageType
from rpkilog.snapshot_summary_file import SnapshotSummaryFile


logger = logging.getLogger(__name__)


def s3_upload(rpkiclient_json: Path, s3_base_url: str) -> str | None:
    """
    Given a Path to rpkiclient's output/json file, determine if it is already present under the given
    S3 base URL.  If not, bzip2 and upload it.  Object key format is YYYYMMDDTHHMMSSZ.json.bz2.

    The caller supplies the S3 base URL (e.g. 's3://bucket/' or 's3://bucket/prefix/'); we set it as
    the class default and let SnapshotSummaryFile derive the object's URL from it plus the buildtime.

    CLEANUP_NEVER keeps us from deleting rpki-client's live source file, which we point at directly.
    """
    with open(rpkiclient_json, 'rt') as json_fh:
        json_data = json.load(json_fh)
    json_datetime = SnapshotSummaryFile.datetimestamp_from_json(json_data)
    SnapshotSummaryFile.default_s3_base_url_set(s3_base_url)
    ssf = SnapshotSummaryFile(
        datetimestamp=json_datetime,
        local_filepath_uncompressed=rpkiclient_json,
        local_storage_type=LocalStorageType.UNCOMPRESSED,
        cleanup_policy=CleanupPolicy.CLEANUP_NEVER,
    )
    if ssf.s3_exists():
        logger.info(f'Currently available rpkiclient json file {json_datetime} has already been uploaded.')
        return None
    ssf.validate_size()
    logger.info(f'Preparing to compress and upload {ssf.s3_url}')
    s3_object = ssf.s3_upload()
    logger.info(f'Uploaded successfully: {s3_object}')
    retstr = s3_object.key
    return retstr


def cli_entry_point():
    logging.basicConfig(level='INFO')
    ap = argparse.ArgumentParser()
    ap.add_argument(
        '--json-file-path', required=True, type=Path,
        help='Path to rpkiclient summary JSON file'
    )
    ap.add_argument(
        '--s3-snapshot-summary-bucket', required=True, type=str,
        help='Name of the rpkiclient snapshot-summary bucket'
    )
    ap.add_argument('--debug', action='store_true', help='Break to debugger on start-up')
    ap.add_argument(
        '--minimum-uptime', type=float, default=900,
        help='Minimum system uptime in seconds before uploading (default: 900)'
    )
    args = ap.parse_args()
    if args.debug:
        breakpoint()
    uptime = time.time() - psutil.boot_time()
    if uptime < args.minimum_uptime:
        logger.warning(
            f'System uptime {uptime:.0f}s is less than --minimum-uptime {args.minimum_uptime:.0f}s; skipping upload'
        )
        return
    s3_base_url = f's3://{args.s3_snapshot_summary_bucket}/'
    s3_upload(
        rpkiclient_json=args.json_file_path,
        s3_base_url=s3_base_url,
    )

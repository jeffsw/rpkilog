"""
This is being written in a bit of a rush to start sourcing snapshots from our own validator.
There is opportunity for re-use being ignored here.
"""
import argparse
import bz2
from datetime import datetime, timezone, UTC
import json
import logging
from pathlib import Path

import boto3
import dateutil.parser


logger = logging.getLogger(__name__)
MINIMUM_JSON_SIZE = 8_500_000


def get_bz2_filename_from_datetime(dt: datetime) -> str:
    retval = dt.strftime('%Y%m%dT%H%M%SZ.json.bz2')
    return retval


def get_rpkiclient_datetime_from_json(json_serialized: bytes | str) -> datetime:
    json_data = json.loads(json_serialized)
    retval = dateutil.parser.parse(json_data['metadata']['buildtime'])
    return retval


def s3_upload(rpkiclient_json: Path, s3_bucket_name: str) -> str | None:
    """
    Given a Path to rpkiclient's output/json file, determine if it is already present in the given S3 bucket.
    If not, bzip2 and upload it.  Filename format is YYYYMMDDTHHMMSSZ.json.bz2.
    """
    with open(rpkiclient_json, 'rb') as json_fh:
        json_buffer = json_fh.read()
    if len(json_buffer) < MINIMUM_JSON_SIZE:
        raise RuntimeError(f'JSON file is too small to be reliable: {rpkiclient_json} < {MINIMUM_JSON_SIZE}')
    json_datetime = get_rpkiclient_datetime_from_json(json_serialized=json_buffer)
    bz2_filename = get_bz2_filename_from_datetime(json_datetime)
    s3 = boto3.client('s3')
    s3_list_result = s3.list_objects(
        Bucket = s3_bucket_name,
        Prefix = bz2_filename,
    )
    if len(s3_list_result.get('Contents', [])):
        # the currently-available rpkiclient json file has already been uploaded
        return None
    bz2_buffer = bz2.compress(json_buffer)
    bucket = boto3.resource('s3').Bucket(s3_bucket_name)
    s3_object = bucket.put_object(key=bz2_filename, Body=bz2_buffer)
    return s3_object.key


def cli_entry_point():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        '--json-file-path', required=True, type=Path,
        help='Path to rpkiclient summary JSON file'
    )
    ap.add_argument(
        '--s3-snapshot-summary-bucket', required=True, type=str,
        help='Name of the rpkiclient snapshot-summary bucket'
    )

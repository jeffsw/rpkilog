"""
End-to-end tests for util.py S3 functions.

Requires live AWS credentials.  The bucket name is taken from the environment variable
RPKILOG_TEST_S3_BUCKET.  If that variable is not set, the default is computed at runtime as
'rpkilog-test-<account_id>-<region>-an' using the account-regional namespace introduced by AWS.
The bucket is created if it does not exist.
Test objects are uploaded idempotently; pre-existing objects with the same keys do not cause failures.
"""
import os
from datetime import datetime, timezone

import boto3
import pytest
from botocore.exceptions import ClientError

from rpkilog.util import list_s3_object_previous
PREFIX_FSTR = 'test_list_s3_object_previous_{datetime_prefix}'
FILE_CONTENT = b'The quick brown fox jumps over the lazy dog'

# ~30 test objects spanning 1981-1999 with deliberate gaps for scenario coverage:
#   - 1983-07-22 to 1983-11-30: ~4-month gap  (gap-of-months test)
#   - 1985-03-10 to 1985-06-15: ~3-month gap
#   - 1985-03-10T12 and 1985-03-10T18: two objects same day (same-day test)
#   - No objects before 1981-01-15                            (KeyError test)
TEST_DATETIMES = [
    datetime(1981,  1, 15, 12,  0,  0, tzinfo=timezone.utc),
    datetime(1981,  3, 20,  8,  0,  0, tzinfo=timezone.utc),
    datetime(1981,  7,  4, 16,  0,  0, tzinfo=timezone.utc),
    datetime(1982,  2, 14, 10,  0,  0, tzinfo=timezone.utc),
    datetime(1982,  9,  5, 12,  0,  0, tzinfo=timezone.utc),
    datetime(1983,  1, 10,  9,  0,  0, tzinfo=timezone.utc),
    datetime(1983,  7, 22, 14,  0,  0, tzinfo=timezone.utc),
    # ~4-month gap
    datetime(1983, 11, 30, 12,  0,  0, tzinfo=timezone.utc),
    datetime(1984,  4, 15, 10,  0,  0, tzinfo=timezone.utc),
    datetime(1984, 12,  1,  9,  0,  0, tzinfo=timezone.utc),
    datetime(1985,  3, 10, 12,  0,  0, tzinfo=timezone.utc),
    datetime(1985,  3, 10, 18,  0,  0, tzinfo=timezone.utc),
    # ~3-month gap
    datetime(1985,  6, 15, 12,  0,  0, tzinfo=timezone.utc),
    datetime(1986,  1, 20, 12,  0,  0, tzinfo=timezone.utc),
    datetime(1987,  5, 14, 10,  0,  0, tzinfo=timezone.utc),
    datetime(1988,  8, 30, 20,  0,  0, tzinfo=timezone.utc),
    datetime(1989, 11, 10, 15,  0,  0, tzinfo=timezone.utc),
    datetime(1990,  4,  1,  6,  0,  0, tzinfo=timezone.utc),
    datetime(1991,  7,  4, 12,  0,  0, tzinfo=timezone.utc),
    datetime(1992,  2, 29, 12,  0,  0, tzinfo=timezone.utc),
    datetime(1993,  9, 15,  9,  0,  0, tzinfo=timezone.utc),
    datetime(1994, 12, 31, 23, 59,  0, tzinfo=timezone.utc),
    datetime(1995,  3, 20, 12,  0,  0, tzinfo=timezone.utc),
    datetime(1996,  6, 10, 12,  0,  0, tzinfo=timezone.utc),
    datetime(1997,  8, 15,  8,  0,  0, tzinfo=timezone.utc),
    datetime(1998,  1,  1,  0,  1,  0, tzinfo=timezone.utc),
    datetime(1998,  6, 15, 12,  0,  0, tzinfo=timezone.utc),
    datetime(1999,  2, 28, 18,  0,  0, tzinfo=timezone.utc),
    datetime(1999,  5, 30, 12,  0,  0, tzinfo=timezone.utc),
    datetime(1999, 12, 31, 23, 59,  0, tzinfo=timezone.utc),
]


@pytest.fixture(scope='module')
def s3_bucket():
    s3_client = boto3.client('s3')
    region = s3_client.meta.region_name

    bucket_name = os.environ.get('RPKILOG_TEST_S3_BUCKET')
    if not bucket_name:
        account_id = boto3.client('sts').get_caller_identity()['Account']
        bucket_name = f'rpkilog-test-{account_id}-{region}-an'

    s3 = boto3.resource('s3')
    bucket = s3.Bucket(bucket_name)

    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except ClientError as exc:
        code = exc.response['Error']['Code']
        if code in ('404', 'NoSuchBucket'):
            create_bucket_configuration: dict = {}
            if region != 'us-east-1':
                create_bucket_configuration['LocationConstraint'] = region
            if bucket_name.endswith('-an'):
                create_bucket_namespace = 'account-regional'
            else:
                create_bucket_namespace = 'global'
            bucket.create(
                CreateBucketConfiguration=create_bucket_configuration,
                BucketNamespace=create_bucket_namespace,
            )
        else:
            raise

    for dt in TEST_DATETIMES:
        key = PREFIX_FSTR.format(datetime_prefix=dt.strftime('%Y%m%dT%H%M%SZ')) + '.txt'
        bucket.put_object(Key=key, Body=FILE_CONTENT)

    return bucket


def test_gap_of_days(s3_bucket):
    # Files on 1985-03-10 (T12 and T18), then a gap; next file is 1985-06-15.
    # Subject is 1985-03-15: day search finds nothing, month search finds T18:00.
    subject = datetime(1985, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
    key = list_s3_object_previous(s3_bucket, subject, prefix_fstr=PREFIX_FSTR)
    assert '19850310T180000Z' in key


def test_gap_of_months(s3_bucket):
    # Last file before Oct 1983 is 1983-07-22T14:00Z (~3 months prior).
    # Subject is 1983-10-15: day and month searches find nothing, previous-month search finds July.
    subject = datetime(1983, 10, 15, 0, 0, 0, tzinfo=timezone.utc)
    key = list_s3_object_previous(s3_bucket, subject, prefix_fstr=PREFIX_FSTR)
    assert '19830722T140000Z' in key


def test_same_day_two_objects(s3_bucket):
    # Two objects on 1985-03-10: T12:00Z and T18:00Z.
    # Subject is T15:00Z: only T12:00Z sorts before the probe.
    subject = datetime(1985, 3, 10, 15, 0, 0, tzinfo=timezone.utc)
    key = list_s3_object_previous(s3_bucket, subject, prefix_fstr=PREFIX_FSTR)
    assert '19850310T120000Z' in key


def test_keyerror_before_first_object(s3_bucket):
    # The earliest test object is 1981-01-15; subject is 1980-12-31.
    subject = datetime(1980, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    with pytest.raises(KeyError):
        list_s3_object_previous(s3_bucket, subject, prefix_fstr=PREFIX_FSTR)


def test_valueerror_missing_datetime_prefix(s3_bucket):
    subject = datetime(1990, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        list_s3_object_previous(s3_bucket, subject, prefix_fstr='no-placeholder-here')

"""
Shared fixtures for rpkilog tests.
"""
import os

import boto3
import pytest
from botocore.exceptions import ClientError


@pytest.fixture(scope='module')
def s3_test_bucket():
    """
    Yields a boto3 Bucket resource pointed at the rpkilog test bucket.

    Bucket name comes from RPKILOG_TEST_S3_BUCKET env var, or is auto-computed as
    rpkilog-test-{account_id}-{region}-an.  The bucket is created if it does not exist.
    """
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
            bucket.create(
                CreateBucketConfiguration=create_bucket_configuration,
                BucketNamespace='account-regional' if bucket_name.endswith('-an') else 'global',
            )
        else:
            raise

    yield bucket

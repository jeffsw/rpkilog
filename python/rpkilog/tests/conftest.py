"""
Shared fixtures for rpkilog tests.
"""
import os
import uuid

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


@pytest.fixture(scope='session')
def s3_run_id():
    """
    A per-test-process identifier used to namespace S3 objects so concurrent CI matrix jobs (which
    share one bucket) never collide on the same key.  Includes GITHUB_RUN_ID when present so any
    leaked objects are traceable back to the run that created them.
    """
    run = os.environ.get('GITHUB_RUN_ID', 'local')
    retstr = f'{run}-{uuid.uuid4().hex}'
    return retstr


@pytest.fixture
def s3_base_url_factory(s3_test_bucket, s3_run_id):
    """
    Yields a callable set_base_url(cls, namespace) -> str that points a DataFileSuper subclass at a
    run-unique S3 base URL of the form s3://{bucket}/citest/{run_id}/{namespace}/ and returns it.
    The subclass then derives object URLs from that base.  Each subclass's prior class default is
    restored on teardown so the process-global classvar does not leak between tests.
    """
    originals = []

    def set_base_url(cls, namespace):
        originals.append((cls, cls._default_s3_base_url))
        base_url = f's3://{s3_test_bucket.name}/citest/{s3_run_id}/{namespace}/'
        cls.default_s3_base_url_set(base_url)
        return base_url

    yield set_base_url

    for cls, prev in originals:
        cls._default_s3_base_url = prev

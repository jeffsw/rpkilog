#!/usr/bin/env python3
"""
Deploy www/ to S3 bucket rpkilog-www and invalidate CloudFront cache.

Reports each changed or deleted file with its before/after S3 version metadata.
Skips CloudFront invalidation if no files changed.

Usage:
    python scripts/deploy_www.py [--dry-run]

Environment:
    AWS_PROFILE          AWS profile to use (optional)
    CF_DISTRIBUTION_ID   CloudFront distribution ID override (optional;
                         auto-discovered via rpkilog.com alias if not set)
"""

import argparse
import os
import subprocess
import sys
import uuid
from datetime import timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

BUCKET = "rpkilog-www"
CF_DOMAIN = "rpkilog.com"
WWW_DIR = Path(__file__).resolve().parent.parent / "www"


def get_bucket_snapshot(s3):
    """Return {s3_key: {VersionId, LastModified, ETag}} for all current object versions."""
    retdict = {}
    paginator = s3.get_paginator('list_object_versions')
    try:
        for page in paginator.paginate(Bucket=BUCKET):
            for ver in page.get('Versions', []):
                if ver['IsLatest']:
                    retdict[ver['Key']] = {
                        'VersionId': ver['VersionId'],
                        'LastModified': ver['LastModified'],
                        'ETag': ver['ETag'].strip('"'),
                    }
    except ClientError as exc:
        print(f"error listing bucket versions: {exc}", file=sys.stderr)
        sys.exit(1)
    return retdict


def get_object_meta(s3, key):
    """Return {VersionId, LastModified, ETag} for the current version of key, or None if missing."""
    try:
        resp = s3.head_object(Bucket=BUCKET, Key=key)
        retdict = {
            'VersionId': resp.get('VersionId', 'N/A'),
            'LastModified': resp['LastModified'],
            'ETag': resp['ETag'].strip('"'),
        }
        return retdict
    except ClientError:
        return None


def run_sync(dry_run=False):
    """Run aws s3 sync and return (changed_keys, deleted_keys)."""
    cmd = ['aws', 's3', 'sync', str(WWW_DIR), f's3://{BUCKET}/', '--delete']
    if dry_run:
        cmd.append('--dryrun')
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)

    changed = []
    deleted = []
    for line in result.stdout.splitlines():
        # Strip optional dryrun prefix: "(dryrun) upload: ..."
        stripped = line.strip().removeprefix('(dryrun) ')
        if stripped.startswith(('upload:', 'copy:')):
            key = stripped.split(f's3://{BUCKET}/')[-1]
            changed.append(key)
        elif stripped.startswith('delete:'):
            key = stripped.split(f's3://{BUCKET}/')[-1]
            deleted.append(key)
    return changed, deleted


def find_cf_distribution_id(cf):
    """Return CF distribution ID from env var or by discovering via rpkilog.com alias."""
    env_id = os.environ.get('CF_DISTRIBUTION_ID')
    if env_id:
        return env_id
    paginator = cf.get_paginator('list_distributions')
    for page in paginator.paginate():
        for dist in page.get('DistributionList', {}).get('Items', []):
            if CF_DOMAIN in dist.get('Aliases', {}).get('Items', []):
                return dist['Id']
    raise RuntimeError(f"no CloudFront distribution found with alias {CF_DOMAIN}")


def fmt_meta(meta):
    """Format object metadata for display, or '(new)' if the object did not previously exist."""
    if meta is None:
        return "(new)"
    ts = meta['LastModified'].astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return f"version={meta['VersionId']}  modified={ts}"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--dry-run', action='store_true', help='show what would change without uploading')
    args = parser.parse_args()

    s3 = boto3.client('s3')
    cf = boto3.client('cloudfront')

    print(f"snapshot  s3://{BUCKET}/")
    before = get_bucket_snapshot(s3)

    print(f"sync      {WWW_DIR} -> s3://{BUCKET}/")
    changed, deleted = run_sync(dry_run=args.dry_run)

    if not changed and not deleted:
        print("no changes — skipping CloudFront invalidation")
        return

    print()
    for key in changed:
        prev = before.get(key)
        print(f"  changed   {key}")
        print(f"    before  {fmt_meta(prev)}")
        if not args.dry_run:
            after = get_object_meta(s3, key)
            after_ver = after['VersionId'] if after else '(unavailable)'
            print(f"    after   version={after_ver}")

    for key in deleted:
        prev = before.get(key)
        print(f"  deleted   {key}")
        print(f"    before  {fmt_meta(prev)}")

    if args.dry_run:
        print("\n(dry run — no changes made, no invalidation)")
        return

    print()
    dist_id = find_cf_distribution_id(cf)
    print(f"invalidate  CloudFront {dist_id}  /*")
    resp = cf.create_invalidation(
        DistributionId=dist_id,
        InvalidationBatch={
            'Paths': {'Quantity': 1, 'Items': ['/*']},
            'CallerReference': str(uuid.uuid4()),
        },
    )
    inv_id = resp['Invalidation']['Id']
    print(f"  submitted invalidation {inv_id}")


if __name__ == '__main__':
    main()
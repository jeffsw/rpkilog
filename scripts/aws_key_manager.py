#!/usr/bin/python3
"""
Rotate IAM access keys for a given user and write the new credentials to a file.

Intended to be invoked by the system Python from cloud-init.
"""

import argparse
import logging
import os
import shutil
import socket

import boto3

LOG = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Rotate IAM access keys for an IAM user and write credentials to a file."
    )
    parser.add_argument("--username", required=True, help="IAM username whose access keys will be rotated")
    parser.add_argument("--cred-file-path", required=True, help="Path to the AWS credentials file to write")
    parser.add_argument("--cred-file-owner", required=True, help="Unix username to own the credentials file")
    parser.add_argument("--cred-file-group", default=None, help="Unix group to own the credentials file")
    parser.add_argument("--debug", action="store_true", help="Break to debugger upon start-up")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    args = parse_args()

    if args.debug:
        breakpoint()

    iam = boto3.client("iam")

    # 1. Delete any existing access keys, logging metadata first.
    existing_keys = iam.list_access_keys(UserName=args.username)["AccessKeyMetadata"]
    for key in existing_keys:
        last_used_resp = iam.get_access_key_last_used(AccessKeyId=key["AccessKeyId"])
        last_used = last_used_resp.get("AccessKeyLastUsed", {}).get("LastUsedDate", "never")
        LOG.info(
            "Deleting existing access key: KeyId=%s Status=%s CreateDate=%s LastUsed=%s",
            key["AccessKeyId"],
            key["Status"],
            key["CreateDate"],
            last_used,
        )
        iam.delete_access_key(UserName=args.username, AccessKeyId=key["AccessKeyId"])

    # 2. Create a new access key.
    hostname = socket.gethostname()
    description = f"created by aws_key_manager.py from {hostname}"
    new_key = iam.create_access_key(UserName=args.username)["AccessKey"]
    LOG.info("Created new access key: KeyId=%s (%s)", new_key["AccessKeyId"], description)

    # 3. Write credentials file in AWS INI format.
    cred_content = (
        "[default]\n"
        f"aws_access_key_id = {new_key['AccessKeyId']}\n"
        f"aws_secret_access_key = {new_key['SecretAccessKey']}\n"
    )

    cred_path = args.cred_file_path
    with open(os.open(cred_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as f:
        f.write(cred_content)

    shutil.chown(cred_path, user=args.cred_file_owner, group=args.cred_file_group)

    LOG.info("Credentials written to %s (owner=%s)", cred_path, args.cred_file_owner)


if __name__ == "__main__":
    main()

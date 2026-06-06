#!/usr/bin/env bash
#MISE description="Replace rpkiclient-2 VM and its STS token (dev)"
#MISE dir="terraform/root/dev"
set -euo pipefail
terraform apply \
  -replace=module.rpkiclient_uploader.shell_script.key_manager_sts_token \
  -replace=incus_instance.rpkiclient_2

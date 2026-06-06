#!/usr/bin/env bash
#MISE description="Replace opensearch-1 VM and its STS token (dev)"
#MISE dir="terraform/root/dev"
set -euo pipefail
terraform apply \
  -replace=module.opensearch_1_iam_user.shell_script.key_manager_sts_token \
  -replace=random_string.opensearch_1_diff_import \
  -replace=incus_instance.opensearch_1

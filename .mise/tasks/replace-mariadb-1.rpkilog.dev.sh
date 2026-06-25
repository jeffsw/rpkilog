#!/usr/bin/env bash
#MISE description="Replace mariadb-1 VM (dev)"
#MISE dir="terraform/root/dev"
set -euo pipefail
# No STS token to replace yet; a future revision may add one (e.g. for copying
# data from the prod SQL DB into the dev DB).
terraform apply \
  -replace=incus_instance.mariadb_1

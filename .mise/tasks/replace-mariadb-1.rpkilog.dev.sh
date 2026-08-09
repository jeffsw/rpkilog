#!/usr/bin/env bash
#MISE description="Replace mariadb-1 VM and its DB layer (dev)"
#MISE dir="terraform/root/dev"
set -euo pipefail

terraform apply -replace=incus_instance.mariadb_1 -replace=terraform_data.mariadb_1_ready

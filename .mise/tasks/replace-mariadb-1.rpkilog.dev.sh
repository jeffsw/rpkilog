#!/usr/bin/env bash
#MISE description="Replace mariadb-1 VM and its DB layer (dev)"
#MISE dir="terraform/root/dev"
set -euo pipefail

# The database-layer resources all hang off terraform_data.mariadb_1_ready (see sqldb.tf), so
# -replacing that hinge alongside the VM cascades to a correctly ordered rebuild of everything the
# VM wipe destroys.  The hinge must be replaced explicitly here: in-place VM updates deliberately
# do not cascade, so this task is the only rebuild path.
terraform apply -replace=incus_instance.mariadb_1 -replace=terraform_data.mariadb_1_ready

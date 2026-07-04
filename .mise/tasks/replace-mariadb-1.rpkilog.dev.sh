#!/usr/bin/env bash
#MISE description="Replace mariadb-1 VM (dev); the DB layer rebuilds via replace_triggered_by"
#MISE dir="terraform/root/dev"
set -euo pipefail

# The database-layer resources all hang off terraform_data.mariadb_1_ready (see sqldb.tf), so this
# single -replace cascades to a correctly ordered rebuild of everything the VM wipe destroys.
terraform apply -replace=incus_instance.mariadb_1

#!/usr/bin/env bash
#MISE description="Replace mariadb-1 VM (dev); the DB layer rebuilds via replace_triggered_by"
#MISE dir="terraform/root/dev"
set -euo pipefail

# Replacing the VM destroys everything in MariaDB (schema, developer user, grants). The
# database-layer resources don't need to be listed here: in sqldb.tf they all hang off
# terraform_data.mariadb_1_ready (lifecycle.replace_triggered_by / the migration's db_server_token),
# which is itself replaced when the instance id changes. So this single -replace cascades to a
# correctly ordered rebuild -- the readiness gate waits for the new VM's admin user before the DB
# resources are recreated and the schema migration re-runs.
terraform apply -replace=incus_instance.mariadb_1

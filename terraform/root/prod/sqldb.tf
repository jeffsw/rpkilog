# Database schema management via the shared sqldb_schema module (Atlas versioned migrations),
# mirroring terraform/root/dev/sqldb.tf.  Differences from dev:
#   - no readiness gate: Terraform itself waits for RDS availability, and the admin user/grant
#     are petoju/mysql resources already ordered after the instance
#   - no mysql_database resource: the instance's db_name argument created the rpkilog database
#   - TLS: RDS requires secure transport, so the Atlas URL gets tls=skip-verify (encrypted,
#     chain unverified), matching the petoju/mysql provider's prod setting
# The module's local-exec runs wherever terraform runs, so the operator's workstation needs
# database Security Group access (rpkilog-database-security-group update --client <name>).
module "sqldb_schema" {
  source = "../../module/sqldb_schema"

  db_host = aws_db_instance.mariadb1.address
  # referencing the grant (not just the user) orders migrations after the admin user can
  # actually perform DDL on the schema
  db_user     = mysql_grant.mariadb1_admin.user
  db_password = random_password.mariadb1_admin.result
  db_schema   = local.mariadb1_database_name
  db_tls      = "skip-verify"
  # changes when the RDS instance is replaced, re-running migrations on the fresh database
  db_server_token = aws_db_instance.mariadb1.resource_id
}

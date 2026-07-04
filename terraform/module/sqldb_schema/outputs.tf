output "applied_version" {
  description = "Migration version the database is at after this module applies (the latest version in the migrations directory)."
  type        = string
  value       = local.latest_migration_version
  # Ordering only: ensure `atlas migrate apply` has run before callers read this version.
  depends_on = [terraform_data.sqldb_migrate]
}

output "db_schema" {
  description = "Database (schema) the tables were applied to."
  type        = string
  value       = var.db_schema
}

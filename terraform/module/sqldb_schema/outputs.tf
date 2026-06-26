output "applied_version" {
  description = "Migration version the database is at after this module applies (the latest version in the migrations directory)."
  type        = string
  value       = atlas_migration.sqldb.version
}

output "db_schema" {
  description = "Database (schema) the tables were applied to."
  type        = string
  value       = var.db_schema
}

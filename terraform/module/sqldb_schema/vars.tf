variable "db_host" {
  description = "Hostname or IP of the MariaDB server to apply the snapshot schema to (e.g. mariadb-1.rpkilog.dev in dev, the RDS endpoint in prod)."
  type        = string
}

variable "db_port" {
  description = "TCP port of the MariaDB server."
  type        = number
  default     = 3306
}

variable "db_user" {
  description = "MariaDB user Atlas connects as to run migrations. Needs DDL privileges on db_schema plus rights to maintain the atlas_schema_revisions table. Username/password in dev; the RDS master user (Secrets Manager) in prod, since the Atlas provider can't mint RDS IAM tokens."
  type        = string
}

variable "db_password" {
  description = "Password for db_user. Must be URL-safe after urlencode(); our random_password generators use special=false, so this holds."
  type        = string
  sensitive   = true
}

variable "db_schema" {
  description = "Database (schema) the snapshot tables live in. Must already exist; Atlas owns the tables, not the database itself (that's the petoju/mysql provider's job)."
  type        = string
  default     = "rpkilog"
}

variable "db_tls" {
  description = "TLS mode appended to the Atlas URL as ?tls=... (Go MySQL driver values, e.g. skip-verify, preferred, true). Empty (the default, used in dev) omits the parameter. Prod RDS requires secure transport; skip-verify encrypts without chain verification, matching the petoju/mysql provider's prod setting."
  type        = string
  default     = ""
}

variable "db_server_token" {
  description = "Opaque value that changes whenever the target database server is (re)created, so the schema is re-applied to the wiped server. Empty (the default) disables that behavior."
  type        = string
  default     = ""
}

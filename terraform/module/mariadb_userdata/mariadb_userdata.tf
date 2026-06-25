terraform {
  required_version = ">= 1.15"
}

variable "console_password_plaintext" {
  description = "Console login password for the jsw user"
  type        = string
}

variable "fqdn" {
  description = "Fully qualified domain name for the VM (e.g. mariadb-1.rpkilog.dev); sets the system hostname and shell prompt"
  type        = string
  default     = null
}

variable "db_admin_username" {
  description = "MariaDB admin user created at first boot, authenticating with username/password from any host. Used for dev access and, later, by the Atlas and petoju/mysql Terraform providers (the dev incus VM has no RDS IAM auth, so access is username/password)."
  type        = string
}

variable "db_admin_password" {
  description = "Password for the MariaDB admin user"
  type        = string
}

variable "db_developer_username" {
  description = "MariaDB convenience user created at first boot, restricted to @localhost but fully privileged. Its credentials are written to a world-readable /etc/mysql client config so any OS user can run `mariadb` with no password prompt."
  type        = string
}

variable "db_developer_password" {
  description = "Password for the MariaDB developer convenience user"
  type        = string
}

locals {
  user_data_mariadb = {
    console_password_plaintext = nonsensitive(var.console_password_plaintext)
    db_admin_username          = var.db_admin_username
    db_admin_password          = nonsensitive(var.db_admin_password)
    db_developer_username      = var.db_developer_username
    db_developer_password      = nonsensitive(var.db_developer_password)
    fqdn                       = var.fqdn
  }
}

output "userdata" {
  description = "plaintext user data for the mariadb VM"
  type        = string
  value       = templatefile("${path.module}/mariadb_userdata.yml.tftpl", local.user_data_mariadb)
}

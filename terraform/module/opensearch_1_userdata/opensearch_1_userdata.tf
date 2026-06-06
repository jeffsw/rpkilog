terraform {
  required_version = ">= 1.15"
}

variable "console_password_plaintext" {
  description = "Console login password for the jsw user"
  type        = string
}

variable "fqdn" {
  description = "Fully qualified domain name for the VM (e.g. opensearch-1.rpkilog.dev); sets the system hostname and shell prompt"
  type        = string
  default     = null
}

variable "key_manager_aws_access_key_id" {
  description = "Ephemeral STS access key ID for the key-manager role; used by 100_aws_key_manager.py to provision rpkilog user credentials"
  type        = string
}

variable "key_manager_aws_secret_access_key" {
  description = "Ephemeral STS secret access key for the key-manager role"
  type        = string
}

variable "key_manager_aws_session_token" {
  description = "Ephemeral STS session token for the key-manager role"
  type        = string
}

variable "opensearch_1_iam_username" {
  description = "IAM username for the opensearch-1 VM user (e.g. opensearch_1_dev); written into the key-manager wrapper script"
  type        = string
}

variable "opensearch_admin_password" {
  description = "Initial admin password passed to OPENSEARCH_INITIAL_ADMIN_PASSWORD when starting the container"
  type        = string
}

variable "diff_import_es_username" {
  description = "OpenSearch username for the diff_import_from_sqs cron job (e.g. vm-opensearch-1-dev)"
  type        = string
  default     = "vm-opensearch-1-dev"
}

variable "diff_import_es_password" {
  description = "OpenSearch password for the diff_import_from_sqs cron job"
  type        = string
}

locals {
  user_data_opensearch_1 = {
    console_password_plaintext        = nonsensitive(var.console_password_plaintext)
    diff_import_es_username           = var.diff_import_es_username
    diff_import_es_password           = var.diff_import_es_password
    fqdn                              = var.fqdn
    key_manager_aws_access_key_id     = var.key_manager_aws_access_key_id
    key_manager_aws_secret_access_key = var.key_manager_aws_secret_access_key
    key_manager_aws_session_token     = var.key_manager_aws_session_token
    opensearch_1_iam_username         = var.opensearch_1_iam_username
    opensearch_admin_password         = var.opensearch_admin_password
    script_install_opensearch         = "${path.module}/../../../scripts/install_opensearch.sh"
    script_install_rpkilog            = "${path.module}/../../../scripts/install_rpkilog.sh"
    script_key_manager                = "${path.module}/../../../scripts/aws_key_manager.py"
  }
}

output "userdata" {
  description = "plaintext user data for opensearch_1 VM"
  type        = string
  value       = templatefile("${path.module}/opensearch_1_userdata.yml.tftpl", local.user_data_opensearch_1)
}

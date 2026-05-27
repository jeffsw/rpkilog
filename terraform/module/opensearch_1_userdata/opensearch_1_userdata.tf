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

variable "opensearch_admin_password" {
  description = "Initial admin password passed to OPENSEARCH_INITIAL_ADMIN_PASSWORD when starting the container"
  type        = string
}

locals {
  user_data_opensearch_1 = {
    console_password_plaintext = nonsensitive(var.console_password_plaintext)
    fqdn                       = var.fqdn
    opensearch_admin_password  = var.opensearch_admin_password
    script_install_opensearch  = "${path.module}/../../../scripts/install_opensearch.sh"
  }
}

output "userdata" {
  description = "plaintext user data for opensearch_1 VM"
  type        = string
  value       = templatefile("${path.module}/opensearch_1_userdata.yml.tftpl", local.user_data_opensearch_1)
}

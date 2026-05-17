variable "console_password_plaintext" {
  type = string
}

variable "key_manager_aws_access_key_id" {
  type = string
}

variable "key_manager_aws_secret_access_key" {
  type = string
}

variable "key_manager_aws_session_token" {
  type = string
}

variable "uploader_bucket" {
  description = "S3 bucket name for rpkiclient snapshot uploads"
  type        = string
}

variable "uploader_cron_enable" {
  description = "when true, the rpkiclient_uploader cron job in /etc/cron.d/ is active; when false the file is still written but the entry is commented out"
  type        = bool
  default     = false
}

variable "uploader_iam_username" {
  type = string
}

locals {
  user_data_rpkiclient = {
    console_password_plaintext = nonsensitive(var.console_password_plaintext)
    key_manager_aws_access_key_id: var.key_manager_aws_access_key_id
    key_manager_aws_secret_access_key: var.key_manager_aws_secret_access_key
    key_manager_aws_session_token: var.key_manager_aws_session_token
    script_key_manager: format("%s/%s", path.module, "../../../scripts/aws_key_manager.py")
    script_install_rpkilog: format("%s/%s", path.module, "../../../scripts/install_rpkilog.sh")
    terraform_root_path: regex("rpkilog/.*?$", abspath(path.root))
    uploader_bucket: var.uploader_bucket
    uploader_cron_enable: var.uploader_cron_enable
    uploader_iam_username = var.uploader_iam_username
  }
}

output "userdata" {
  description = "plaintext user data for rpkiclient VM"
  value = templatefile("${path.module}/rpkiclient_userdata.yml.tftpl", local.user_data_rpkiclient)
}

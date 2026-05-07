# ⚠️ This user will be created with no API keys or password.  It's necessary to MANUALLY create an API
# secret-key, then re-invoke this Terraform workspace with var.rpkiclient_uploader_iam_secret_key, to
# complete provisioning of all resources.  Prior to that, the default value will allow provisioning the
# VMs & software setup.
variable "rpkiclient_uploader_iam_secret_key" {
  description = "MANUALLY CREATED AWS IAM secret key for the rpkiclient_uploader_<workspace name> user"
  type = string
  ephemeral = true
  default = "PLACEHOLDER_NOT_A_REAL_SECRET_KEY"
}

variable "snapshot_bucket_name" {
  type = string
  default = "rpkilog-snapshot-summary"
}

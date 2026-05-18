variable "snapshot_bucket_name" {
  type    = string
  default = "rpkilog-snapshot-summary"
}

variable "uploader_cron_enable" {
  type    = bool
  default = false
}

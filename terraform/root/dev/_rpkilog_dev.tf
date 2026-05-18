terraform {
  required_version = "~> 1.15.0"
  backend "s3" {
    bucket               = "rpkilog-terraform"
    region               = "us-east-1"
    workspace_key_prefix = "new"
    key                  = "terraform.tfstate"
    use_lockfile         = true
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.44.0"
    }
    incus = {
      source  = "lxc/incus"
      version = "~> 1.0.2"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.8.1"
    }
  }
}

resource "terraform_data" "workspace_check" {
  lifecycle {
    precondition {
      condition     = terraform.workspace == "dev"
      error_message = "This root module requires workspace 'dev'; current workspace is '${terraform.workspace}'."
    }
  }
}

provider "aws" {
  allowed_account_ids = [
    "054500078560", # rpkilog
  ]
  default_tags {
    tags = {
      tf_managed = regex("rpkilog/.*?$", abspath(path.root))
      workspace  = terraform.workspace
    }
  }
  region = "us-east-1"
}

provider "incus" {
  default_remote = "router26a"
  remote {
    name = "router26a"
  }
}

provider "random" {}

data "aws_caller_identity" "main" {}

data "aws_s3_bucket" "snapshot_summary" {
  bucket = var.snapshot_bucket_name
}

data "incus_storage_pool" "default" {
  name = "default"
}

resource "incus_storage_volume" "rpkiclient_2_volume_1" {
  name         = "rpkiclient-2-volume-1"
  pool         = data.incus_storage_pool.default.name
  content_type = "block"
  config = {
    # Sized for ~5 million inodes at 20_000_000_000 / 4096.
    size = "20GiB"
  }
}

resource "incus_storage_volume" "routinator_1_volume_1" {
  name         = "routinator-1-volume-1"
  pool         = data.incus_storage_pool.default.name
  content_type = "block"
  config = {
    # Sized for ~5 million inodes at 20_000_000_000 / 4096.
    size = "20GiB"
  }
}

resource "random_password" "rpkiclient_2" {
  length  = 14
  lower   = true
  numeric = true
  special = false
  upper   = true
}

module "userdata_rpkiclient_2" {
  source                            = "../../module/rpkiclient_userdata"
  console_password_plaintext        = nonsensitive(random_password.rpkiclient_2.result)
  key_manager_aws_access_key_id     = module.rpkiclient_uploader.key_manager.AccessKeyId
  key_manager_aws_secret_access_key = module.rpkiclient_uploader.key_manager.SecretAccessKey
  key_manager_aws_session_token     = module.rpkiclient_uploader.key_manager.SessionToken
  uploader_iam_username             = module.rpkiclient_uploader.user.name
  uploader_bucket                   = data.aws_s3_bucket.snapshot_summary.id
  uploader_cron_enable              = var.uploader_cron_enable
}

# https://registry.terraform.io/providers/lxc/incus/latest/docs/resources/instance
resource "incus_instance" "rpkiclient_2" {
  name  = "rpkiclient-2"
  type  = "virtual-machine"
  image = "images:ubuntu/24.04/cloud"
  config = {
    # https://linuxcontainers.org/incus/docs/main/reference/instance_options/
    "boot.autostart"       = true
    "boot.autostart.delay" = 60
    "limits.cpu"           = "10,11"
    # would run fine with 2GB RAM
    "limits.memory"  = "8GB"
    "user.user-data" = module.userdata_rpkiclient_2.userdata
  }
  device {
    name = "volume1"
    type = "disk"
    # appears as /dev/sdb and cloud-init will partition & create /data filesystem
    properties = {
      source   = incus_storage_volume.rpkiclient_2_volume_1.name
      pool     = data.incus_storage_pool.default.name
      required = true
    }
  }
}

resource "incus_instance" "routinator_1" {
  name  = "routinator-1"
  type  = "virtual-machine"
  image = "images:ubuntu/24.04/cloud"
  config = {
    "boot.autostart"       = true
    "boot.autostart.delay" = 90
    "limits.cpu"           = "8,9"
    # would run fine with 2GB RAM
    "limits.memory" = "8GB"
    # TODO: replace with templatefile() to pass in configuration and AWS API key
    "user.user-data" = file("${path.module}/routinator-1.yml")
  }
  # appears as /dev/sdb and cloud-init will partition & create /data filesystem
  device {
    name = "volume1"
    type = "disk"
    properties = {
      source   = incus_storage_volume.routinator_1_volume_1.name
      pool     = data.incus_storage_pool.default.name
      required = true
    }
  }
}
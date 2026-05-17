terraform {
  required_version = "~> 1.15.0"
  backend "s3" {
    bucket               = "rpkilog-terraform"
    region               = "us-east-1"
    workspace_key_prefix = "new-prod"
    key                  = "terraform.tfstate"
    use_lockfile         = true
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.44.0"
    }
    linode = {
      source  = "linode/linode"
      version = "~> 3.12.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.8.1"
    }
  }
}

variable "jump_servers_ipv4" {
  description = "jump servers ipv4"
  type        = list(string)
  default = [
    "52.86.232.165/32",
    "198.58.103.30/32",
  ]
}

variable "jump_servers_ipv6" {
  description = "jump servers ipv6"
  type        = list(string)
  default = [
    "2600:3c00::f03c:91ff:fe91:5c9d/128"
  ]
}

variable "snapshot_bucket_name" {
  type    = string
  default = "rpkilog-snapshot-summary"
}

variable "uploader_cron_enable" {
  type    = bool
  default = false
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

provider "random" {}

data "aws_caller_identity" "main" {}

data "aws_s3_bucket" "snapshot_summary" {
  bucket = var.snapshot_bucket_name
}

resource "random_password" "rpkiclient" {
  length  = 14
  lower   = true
  numeric = true
  special = false
  upper   = true
}

output "random_password__rpkiclient" {
  description = "rpkiclient VM root password"
  value = nonsensitive(random_password.rpkiclient.result)
}

data "aws_route53_zone" "rpkilog_tld" {
  name = terraform.workspace == "prod" ? "rpkilog.com" : terraform.workspace == "dev" ? "rpkilog.dev" : "unknown"
  private_zone = false
}

module "rpkiclient_uploader" {
  source             = "../../module/aws_iam_user_for_vm"
  name               = "rpkiclient_uploader_${terraform.workspace}"
}

resource "aws_iam_policy" "rpkiclient_uploader" {
  name = "rpkiclient_uploader_${terraform.workspace}"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "s3:ListBucket",
          "s3:PutObject",
          "s3:PutObjectAcl",
          "s3:PutObjectRetention",
          "s3:PutObjectTagging",
        ],
        Resource = [
          data.aws_s3_bucket.snapshot_summary.arn,
          "${data.aws_s3_bucket.snapshot_summary.arn}/*",
        ]
      }
    ]
  })
}

resource "aws_iam_user_policy_attachment" "rpkiclient_uploader" {
  user       = module.rpkiclient_uploader.user.name
  policy_arn = aws_iam_policy.rpkiclient_uploader.arn
}

module "userdata" {
  source                            = "../../module/rpkiclient_userdata"
  console_password_plaintext        = nonsensitive(random_password.rpkiclient.result)
  key_manager_aws_access_key_id     = module.rpkiclient_uploader.key_manager.AccessKeyId
  key_manager_aws_secret_access_key = module.rpkiclient_uploader.key_manager.SecretAccessKey
  key_manager_aws_session_token     = module.rpkiclient_uploader.key_manager.SessionToken
  uploader_iam_username             = module.rpkiclient_uploader.user.name
  uploader_bucket                   = data.aws_s3_bucket.snapshot_summary.id
  uploader_cron_enable              = var.uploader_cron_enable
}

# https://registry.terraform.io/providers/linode/linode/latest/docs/resources/instance
resource "linode_instance" "rpkiclient" {
  label              = "rpkilog-rpkiclient"
  maintenance_policy = "linode/power_off_on"
  region             = "us-southeast"
  watchdog_enabled   = true
  # rpki-client encounters occassional OOMs with 2 GB RAM.  We'll use 4 GB.
  # see `linode-cli linodes types` for instance specifications and prices.
  # g6-standard-1    1 vCPU, 2 GB RAM, 50 GB SSD  $12/mo
  # g6-standard-2    2 vCPU, 4 GB RAM, 80 GB SSD  $24/mo
  type               = "g6-standard-2"
  metadata {
    user_data = base64encode(module.userdata.userdata)
  }
  tags = [
    "rpkiclient",
    "rpkilog",
  ]
  lifecycle {
    ignore_changes = [
      metadata
    ]
  }
}

resource "linode_instance_config" "rpkiclient" {
  linode_id = linode_instance.rpkiclient.id
  label     = "rpkiclient"
  booted    = true
  device {
    device_name = "sda"
    disk_id     = linode_instance_disk.rpkiclient_root.id
  }
  device {
    device_name = "sdb"
    disk_id     = linode_instance_disk.rpkiclient_data.id
  }
}

resource "linode_instance_disk" "rpkiclient_root" {
  linode_id = linode_instance.rpkiclient.id
  label     = "root"
  size      = 20000
  image     = "linode/ubuntu24.04"
  root_pass = nonsensitive(random_password.rpkiclient.result)
}

resource "linode_instance_disk" "rpkiclient_data" {
  linode_id = linode_instance.rpkiclient.id
  label     = "data"
  size      = linode_instance.rpkiclient.specs.0.disk - linode_instance_disk.rpkiclient_root.size
  filesystem = "raw"
}

# see also https://techdocs.akamai.com/linode-api/reference/post-firewalls
resource "linode_firewall" "rpkilog" {
  label = "rpkilog"
  linodes = [
    linode_instance.rpkiclient.id
  ]
  inbound_policy  = "DROP"
  outbound_policy = "ACCEPT"

  inbound {
    label    = "jump_servers_tcp"
    action   = "ACCEPT"
    protocol = "TCP"
    ipv4     = var.jump_servers_ipv4
  }

  inbound {
    label    = "jump_servers_tcp"
    action   = "ACCEPT"
    protocol = "TCP"
    ipv6     = var.jump_servers_ipv6
  }

  inbound {
    label    = "jump_servers_udp"
    action   = "ACCEPT"
    protocol = "UDP"
    ipv4     = var.jump_servers_ipv4
  }

  inbound {
    label    = "jump_servers_udp"
    action   = "ACCEPT"
    protocol = "UDP"
    ipv6     = var.jump_servers_ipv6
  }

  inbound {
    label    = "icmp"
    action   = "ACCEPT"
    protocol = "ICMP"
    ipv4     = ["0.0.0.0/0"]
  }

  inbound {
    label    = "icmp"
    action   = "ACCEPT"
    protocol = "ICMP"
    ipv6     = ["::/0"]
  }
}

resource "aws_route53_record" "rpkiclient_A" {
  zone_id = data.aws_route53_zone.rpkilog_tld.id
  name = "rpkiclient"
  type = "A"
  ttl = 300
  records = linode_instance.rpkiclient.ipv4
}

resource "aws_route53_record" "rpkiclient_AAAA" {
  zone_id = data.aws_route53_zone.rpkilog_tld.id
  name = "rpkiclient"
  type = "AAAA"
  ttl = 300
  records = [cidrhost(linode_instance.rpkiclient.ipv6, 0)]
}

resource "linode_rdns" "rpkiclient_PTR_4" {
  for_each = toset(linode_instance.rpkiclient.ipv4)
  address = each.key
  rdns = aws_route53_record.rpkiclient_A.fqdn
  wait_for_available = true
}

resource "linode_rdns" "rpkiclient_PTR_6" {
  address = cidrhost(linode_instance.rpkiclient.ipv6, 0)
  rdns = aws_route53_record.rpkiclient_AAAA.fqdn
  wait_for_available = true
}

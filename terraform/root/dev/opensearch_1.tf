provider "opensearch" {
  url      = "https://${aws_route53_record.opensearch_1_A.fqdn}:9200"
  insecure = true
  username = "admin"
  password = random_password.opensearch_1_admin.result
}

locals {
  diff_import_es_username = "vm-opensearch-1-${terraform.workspace}"
}

resource "incus_storage_volume" "opensearch_1_volume_1" {
  name         = "opensearch-1-volume-1"
  pool         = data.incus_storage_pool.default.name
  content_type = "block"
  config = {
    size = "800GiB"
  }
}

resource "random_password" "opensearch_1_admin" {
  length           = 20
  lower            = true
  numeric          = true
  special          = true
  override_special = "_"
  upper            = true
}

output "opensearch_1_admin_password" {
  description = "OpenSearch initial admin password (OPENSEARCH_INITIAL_ADMIN_PASSWORD)"
  value       = nonsensitive(random_password.opensearch_1_admin.result)
}

resource "random_string" "opensearch_1_diff_import" {
  length  = 24
  lower   = true
  upper   = false
  numeric = true
  special = false
}

output "opensearch_1_diff_import_username" {
  description = "OpenSearch username for the diff_import_from_sqs cron job"
  value       = local.diff_import_es_username
}

output "opensearch_1_diff_import_password" {
  description = "OpenSearch password for the diff_import_from_sqs cron job"
  value       = random_string.opensearch_1_diff_import.result
}

resource "random_password" "opensearch_1_console" {
  length  = 14
  lower   = true
  numeric = true
  special = false
  upper   = true
}

output "opensearch_1_console_password" {
  description = "opensearch-1 VM console login password for the jsw user"
  value       = nonsensitive(random_password.opensearch_1_console.result)
}

data "aws_s3_bucket" "rpkilog_diff" {
  bucket = "rpkilog-diff"
}

data "aws_sqs_queue" "diff_dev" {
  name = "diff_dev"
}

module "opensearch_1_iam_user" {
  source = "../../module/aws_iam_user_for_vm"
  name   = "opensearch_1_${terraform.workspace}"
}

resource "aws_iam_policy" "opensearch_1" {
  name = "opensearch_1_${terraform.workspace}"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectAttributes",
          "s3:ListBucket",
        ]
        Resource = [
          data.aws_s3_bucket.rpkilog_diff.arn,
          "${data.aws_s3_bucket.rpkilog_diff.arn}/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ChangeMessageVisibility",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl",
          "sqs:ReceiveMessage",
        ]
        Resource = data.aws_sqs_queue.diff_dev.arn
      },
    ]
  })
}

resource "aws_iam_user_policy_attachment" "opensearch_1" {
  user       = module.opensearch_1_iam_user.user.name
  policy_arn = aws_iam_policy.opensearch_1.arn
}

module "userdata_opensearch_1" {
  source                            = "../../module/opensearch_1_userdata"
  console_password_plaintext        = nonsensitive(random_password.opensearch_1_console.result)
  fqdn                              = "opensearch-1.rpkilog.dev"
  key_manager_aws_access_key_id     = module.opensearch_1_iam_user.key_manager.AccessKeyId
  key_manager_aws_secret_access_key = module.opensearch_1_iam_user.key_manager.SecretAccessKey
  key_manager_aws_session_token     = module.opensearch_1_iam_user.key_manager.SessionToken
  opensearch_1_iam_username         = module.opensearch_1_iam_user.user.name
  opensearch_admin_password         = nonsensitive(random_password.opensearch_1_admin.result)
  diff_import_es_username           = local.diff_import_es_username
  diff_import_es_password           = random_string.opensearch_1_diff_import.result
}

# https://registry.terraform.io/providers/lxc/incus/latest/docs/resources/instance
resource "incus_instance" "opensearch_1" {
  name  = "opensearch-1"
  type  = "virtual-machine"
  image = "images:ubuntu/24.04/cloud"
  config = {
    "boot.autostart"       = true
    "boot.autostart.delay" = 120
    "limits.cpu"           = "4"
    "limits.memory"        = "32GB"
    "user.user-data"       = module.userdata_opensearch_1.userdata
  }
  device {
    name = "volume1"
    type = "disk"
    # io.bus = "virtio-blk" places this disk in the /dev/vd* namespace, keeping it
    # separate from the OS disk (/dev/sda via virtio-scsi).  Without this, both disks
    # share the /dev/sd* namespace and Incus can present them in either order.
    properties = {
      source   = incus_storage_volume.opensearch_1_volume_1.name
      pool     = data.incus_storage_pool.default.name
      required = true
      "io.bus" = "virtio-blk"
    }
  }
  wait_for {
    type = "ipv4"
  }
}

resource "aws_route53_record" "opensearch_1_A" {
  zone_id = data.aws_route53_zone.rpkilog_dev.zone_id
  name    = "opensearch-1"
  type    = "A"
  ttl     = 300
  records = [incus_instance.opensearch_1.ipv4_address]
}

# Poll /_cluster/health until OpenSearch is accepting connections before
# allowing the opensearch provider resources below to run.  The VM boots and
# runs cloud-init (package upgrades, Docker pull, container start) before
# OpenSearch is reachable, so a simple depends_on the instance is not enough.
resource "terraform_data" "opensearch_1_ready" {
  lifecycle {
    replace_triggered_by = [incus_instance.opensearch_1]
  }

  provisioner "local-exec" {
    environment = {
      OS_PASSWORD = random_password.opensearch_1_admin.result
    }
    command = <<-EOT
      echo "Waiting for OpenSearch at opensearch-1.rpkilog.dev:9200..."
      until curl -sk -u "admin:$OS_PASSWORD" \
          https://opensearch-1.rpkilog.dev:9200/_cluster/health \
          | grep -q '"status"'; do
        echo "  not ready yet, retrying in 15s..."
        sleep 15
      done
      echo "OpenSearch is ready."
    EOT
  }

  depends_on = [incus_instance.opensearch_1]
}

resource "opensearch_cluster_settings" "opensearch_1" {
  search_default_search_timeout = "30s"
  depends_on                    = [terraform_data.opensearch_1_ready]
}

resource "opensearch_role" "diff_import" {
  role_name   = "diff_import"
  description = "Read, write, and create-index on diff-* indices; cluster monitor for health checks"
  depends_on  = [terraform_data.opensearch_1_ready]

  cluster_permissions = ["cluster_monitor"]

  index_permissions {
    index_patterns  = ["diff-*"]
    allowed_actions = ["read", "write", "create_index"]
  }
}

resource "opensearch_user" "diff_import" {
  username    = local.diff_import_es_username
  password    = random_string.opensearch_1_diff_import.result
  description = "Service account for the diff_import_from_sqs cron job on opensearch-1.rpkilog.dev"
  depends_on  = [terraform_data.opensearch_1_ready]
}

resource "opensearch_roles_mapping" "diff_import" {
  role_name  = opensearch_role.diff_import.role_name
  users      = [opensearch_user.diff_import.username]
  depends_on = [terraform_data.opensearch_1_ready]
}

resource "opensearch_dashboard_object" "diff_index_pattern" {
  tenant_name = ""
  body = jsonencode([
    {
      _id = "index-pattern:diff-*"
      _source = {
        type = "index-pattern"
        "index-pattern" = {
          title         = "diff-*"
          timeFieldName = "observation_timestamp"
        }
      }
    }
  ])
  depends_on = [terraform_data.opensearch_1_ready]
}

resource "opensearch_index_template" "diff" {
  name       = "diff"
  depends_on = [terraform_data.opensearch_1_ready]
  body = jsonencode({
    index_patterns : ["diff-*"],
    template : {
      settings : {
        index : {
          number_of_shards : "1",
          number_of_replicas : "0",
        }
      }
      mappings : {
        properties : {
          observation_timestamp : { type : "date", format : "strict_date_time_no_millis" },
          verb : { type : "keyword" },
          prefix : { type : "ip_range" },
          maxLength : { type : "integer" },
          asn : { type : "long" },
          ta : { type : "keyword" },
          old_expires : { type : "date", format : "strict_date_time_no_millis" },
          new_expires : { type : "date", format : "strict_date_time_no_millis" },
          old_roa : { type : "object" },
          new_roa : { type : "object" },
        }
      }
    }
  })
}

provider "opensearch" {
  url      = "https://${aws_route53_record.opensearch_1_A.fqdn}:9200"
  insecure = true
  username = "admin"
  password = random_password.opensearch_1_admin.result
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

module "userdata_opensearch_1" {
  source                     = "../../module/opensearch_1_userdata"
  console_password_plaintext = nonsensitive(random_password.opensearch_1_console.result)
  fqdn                       = "opensearch-1.rpkilog.dev"
  opensearch_admin_password  = nonsensitive(random_password.opensearch_1_admin.result)
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

resource "opensearch_cluster_settings" "opensearch_1" {
  search_default_search_timeout = "30s"
}

resource "opensearch_index_template" "diff" {
  name = "diff"
  body = jsonencode({
    index_patterns : ["diff-*"],
    template : {
      settings : {
        index : {
          number_of_shards : 1,
          number_of_replicas : 0,
        }
      }
      mappings : {
        properties : {
          observation_timestamp : { type : "date", format : "strict_date_time_no_millis" },
          verb                  : { type : "keyword" },
          prefix                : { type : "ip_range" },
          maxLength             : { type : "integer" },
          asn                   : { type : "long" },
          ta                    : { type : "keyword" },
          old_expires           : { type : "date", format : "strict_date_time_no_millis" },
          new_expires           : { type : "date", format : "strict_date_time_no_millis" },
          old_roa               : { type : "object" },
          new_roa               : { type : "object" },
        }
      }
    }
  })
}

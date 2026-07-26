# Dev MariaDB for the snapshot-tracking database (GH-81).  RDS in prod; an incus VM here.
# MariaDB data lives on the VM's root filesystem — the dataset is modest and dev disk is cheap.

locals {
  mariadb_1_admin_username     = "rpkilog_admin"
  mariadb_1_developer_username = "developer"
  mariadb_1_database_name      = "rpkilog"
}

resource "random_password" "mariadb_1_console" {
  length  = 14
  lower   = true
  numeric = true
  special = false
  upper   = true
}

resource "random_password" "mariadb_1_admin" {
  length  = 24
  lower   = true
  numeric = true
  special = false
  upper   = true
}

resource "random_password" "mariadb_1_developer" {
  length  = 24
  lower   = true
  numeric = true
  special = false
  upper   = true
}

output "mariadb_1_console_password" {
  description = "mariadb-1 VM console login password for the jsw user"
  value       = nonsensitive(random_password.mariadb_1_console.result)
}

output "mariadb_1_admin_username" {
  description = "MariaDB admin (dev access) username on mariadb-1.rpkilog.dev"
  value       = local.mariadb_1_admin_username
}

output "mariadb_1_admin_password" {
  description = "MariaDB admin (dev access) password on mariadb-1.rpkilog.dev"
  value       = nonsensitive(random_password.mariadb_1_admin.result)
}

output "mariadb_1_endpoint" {
  description = "mariadb-1 dev MariaDB hostname (consumed by the sql-* mise tasks)"
  value       = aws_route53_record.mariadb_1_A.fqdn
}

module "userdata_mariadb_1" {
  source                     = "../../module/mariadb_userdata"
  console_password_plaintext = nonsensitive(random_password.mariadb_1_console.result)
  db_admin_username          = local.mariadb_1_admin_username
  db_admin_password          = nonsensitive(random_password.mariadb_1_admin.result)
  fqdn                       = "mariadb-1.rpkilog.dev"
}

# https://registry.terraform.io/providers/lxc/incus/latest/docs/resources/instance
resource "incus_instance" "mariadb_1" {
  name  = "mariadb-1"
  type  = "virtual-machine"
  image = "images:ubuntu/24.04/cloud"
  config = {
    "boot.autostart"       = true
    "boot.autostart.delay" = 150
    # 2 vCPU, no core pinning (a bare count rather than a pinned cpuset like "10,11").
    "limits.cpu"     = "2"
    "limits.memory"  = "2GB"
    "user.user-data" = module.userdata_mariadb_1.userdata
  }
  wait_for {
    type = "ipv4"
  }
}

resource "aws_route53_record" "mariadb_1_A" {
  zone_id = data.aws_route53_zone.rpkilog_dev.zone_id
  name    = "mariadb-1"
  type    = "A"
  ttl     = 300
  records = [incus_instance.mariadb_1.ipv4_address]
}

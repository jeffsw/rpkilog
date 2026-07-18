# The database-layer resources reach MariaDB over a static DNS endpoint, so Terraform has no
# automatic ordering against the VM. terraform_data.mariadb_1_ready is the single hinge: every DB
# resource is ordered after it and replaced with it. The hinge itself is replaced only by the
# replace-mariadb-1 mise task (alongside the VM), cascading a full, correctly ordered rebuild of
# the database layer; in-place VM updates (user-data, limits.*) deliberately do not cascade.

# Readiness gate. cloud-init starts mariadb-server -- opening port 3306 -- before its per-once
# script creates the admin user, so a bare TCP probe would pass too early; polling with the atlas
# CLI succeeds only once admin auth works. Server-level URL (no database) because the rpkilog
# schema does not exist yet at gate time.
resource "terraform_data" "mariadb_1_ready" {
  # Ordered after the instance; replaced only via the replace-mariadb-1 mise task, so in-place
  # instance updates never cascade a rebuild of the database layer (see the header comment).
  depends_on = [incus_instance.mariadb_1]

  provisioner "local-exec" {
    # Password via env, never argv.
    environment = {
      ADMIN_URL = "maria://${local.mariadb_1_admin_username}:${urlencode(random_password.mariadb_1_admin.result)}@mariadb-1.rpkilog.dev:3306/"
    }
    command = <<-EOT
      for i in $(seq 1 60); do
        if atlas schema inspect --url "$ADMIN_URL" >/dev/null 2>&1; then
          echo "mariadb-1 admin connection OK"
          exit 0
        fi
        echo "waiting for mariadb-1 admin connection (attempt $i/60)..."
        sleep 10
      done
      echo "timed out waiting for mariadb-1 admin connection" >&2
      exit 1
    EOT
  }
}

# `CREATE DATABASE ...`. Ordered after, and replaced with, the readiness gate.
resource "mysql_database" "rpkilog" {
  name = local.mariadb_1_database_name
  lifecycle {
    replace_triggered_by = [terraform_data.mariadb_1_ready]
  }
}

# Developer DB user: fully privileged, reachable from the VM (localhost socket) and from the
# 192.168.0.0/16 dev LAN -- trusted dev networks only.
resource "mysql_user" "developer" {
  for_each           = toset(["localhost", "192.168.%"])
  user               = local.mariadb_1_developer_username
  host               = each.value
  plaintext_password = random_password.mariadb_1_developer.result
  lifecycle {
    replace_triggered_by = [terraform_data.mariadb_1_ready]
  }
}

# GRANT ALL PRIVILEGES ON *.* ... WITH GRANT OPTION, one per (user, host)
resource "mysql_grant" "developer" {
  for_each   = mysql_user.developer
  user       = each.value.user
  host       = each.value.host
  database   = "*"
  privileges = ["ALL PRIVILEGES"]
  grant      = true
  lifecycle {
    replace_triggered_by = [terraform_data.mariadb_1_ready]
  }
}

# manages the database schema
module "sqldb_schema" {
  source = "../../module/sqldb_schema"

  db_host     = aws_route53_record.mariadb_1_A.fqdn
  db_user     = local.mariadb_1_admin_username
  db_password = random_password.mariadb_1_admin.result
  db_schema   = mysql_database.rpkilog.name
  # changes when the VM is recreated, re-running the migration on the fresh, empty database
  db_server_token = terraform_data.mariadb_1_ready.id
}

output "mariadb_1_developer_username" {
  description = "MariaDB developer user (fully privileged; reachable from the VM and the 192.168.0.0/16 LAN)."
  value       = local.mariadb_1_developer_username
}

output "mariadb_1_developer_password" {
  description = "Password for the Terraform-managed MariaDB developer user."
  value       = nonsensitive(random_password.mariadb_1_developer.result)
}

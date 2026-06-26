# The database-layer resources (the rpkilog database, the developer user/grants, and the schema
# migration) reach MariaDB over a static DNS endpoint, so Terraform has no automatic ordering
# against the VM and would not notice a VM replace wiping the data. terraform_data.mariadb_1_ready
# below is the single hinge: it waits for the (re)created VM's MariaDB to accept admin connections,
# and every DB resource is ordered after it and replaced with it (via lifecycle.replace_triggered_by,
# or the migration's db_server_token). So `terraform apply -replace=incus_instance.mariadb_1`
# cascades to a full, correctly ordered rebuild of the database layer -- nothing to enumerate in the
# replace-mariadb-1.rpkilog.dev task, and the same gate removes the need to -target on first apply.

# Readiness gate. cloud-init starts mariadb-server -- opening port 3306 -- before its per-once
# script creates the admin user, so a bare TCP probe would pass too early. We poll with the atlas
# CLI (on PATH via mise, and our DB tool anyway), which succeeds only once admin auth works. A
# server-level URL (no database) is used because the rpkilog schema does not exist yet at gate time.
# triggers_replace on the instance id re-runs the wait whenever the VM is replaced and makes this
# the single resource the replace cascades from.
resource "terraform_data" "mariadb_1_ready" {
  # Re-run the readiness wait whenever the VM is replaced. incus_instance exposes no
  # replacement-stable id to feed triggers_replace, so trigger on the resource itself; this also
  # orders the gate after the instance.
  lifecycle {
    replace_triggered_by = [incus_instance.mariadb_1]
  }

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

# Developer DB user, managed by Terraform rather than cloud-init (which owns only the admin user).
# Fully privileged and reachable both from the VM itself (localhost socket) and from the
# 192.168.0.0/16 dev LAN. '192.168.%' means any workstation on that LAN with these credentials has
# full privileges -- trusted dev networks only.
resource "mysql_user" "developer" {
  for_each           = toset(["localhost", "192.168.%"])
  user               = local.mariadb_1_developer_username
  host               = each.value
  plaintext_password = random_password.mariadb_1_developer.result
  lifecycle {
    replace_triggered_by = [terraform_data.mariadb_1_ready]
  }
}

# GRANT ALL PRIVILEGES ON *.* ... WITH GRANT OPTION, one per (user, host). Ordered after the users
# via the mysql_user.developer reference; replaced with the gate like the rest of the DB layer.
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
  # Changes when the VM (hence the database) is recreated, re-running the migration on the fresh,
  # empty database -- a wipe loses the atlas_schema_revisions history along with the data.
  db_server_token = terraform_data.mariadb_1_ready.id
}

output "mariadb_1_developer_username" {
  description = "MariaDB developer user (fully privileged; reachable from the VM and the 192.168.0.0/16 LAN). Managed by Terraform via the petoju/mysql resources above."
  value       = local.mariadb_1_developer_username
}

output "mariadb_1_developer_password" {
  description = "Password for the Terraform-managed MariaDB developer user."
  value       = nonsensitive(random_password.mariadb_1_developer.result)
}

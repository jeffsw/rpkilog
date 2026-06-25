terraform {
  required_version = ">= 1.15"
  required_providers {
    atlas = {
      source  = "ariga/atlas"
      version = "~> 0.10.3"
    }
  }
}

# Atlas connection URL. urlencode() guards against reserved characters in the credentials; the
# `maria://` scheme selects the MariaDB dialect. The atlas provider shells out to the pinned
# `atlas` CLI (see .mise.toml), which must be on PATH wherever Terraform runs.
locals {
  migration_dir = "file://${path.module}/migrations"
  atlas_url = format(
    "maria://%s:%s@%s:%d/%s",
    urlencode(var.db_user),
    urlencode(var.db_password),
    var.db_host,
    var.db_port,
    var.db_schema,
  )
}

# Reads the migration directory and the live database to compute migration status (current /
# next / latest applied version). Drives the resource below so a plan shows pending migrations.
data "atlas_migration" "snapshot_db" {
  dir = local.migration_dir
  url = local.atlas_url
}

# Applies every pending migration up to the latest version in the directory. Idempotent: when
# the database is already at `latest`, there is nothing to apply.
resource "atlas_migration" "snapshot_db" {
  dir     = local.migration_dir
  url     = local.atlas_url
  version = data.atlas_migration.snapshot_db.latest
}

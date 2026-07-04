terraform {
  required_version = ">= 1.15"
}

# Atlas connection URL passed to the `atlas` CLI. urlencode() guards against reserved characters in
# the credentials; the `maria://` scheme selects the MariaDB dialect.
#
# Migrations are applied by shelling out to the pinned Atlas Community CLI (see .mise.toml) rather
# than the ariga/atlas Terraform provider: the provider cannot parse the Community Edition's
# version banner and fails before it ever connects.
locals {
  migration_dir = "file://migrations"
  atlas_url = format(
    "maria://%s:%s@%s:%d/%s",
    urlencode(var.db_user),
    urlencode(var.db_password),
    var.db_host,
    var.db_port,
    var.db_schema,
  )

  # latest migration version in the directory: the filename prefix before the first underscore
  latest_migration_version = element(
    reverse(sort([for f in fileset("${path.module}/migrations", "*.sql") : split("_", f)[0]])),
    0,
  )
}

# Applies every pending migration. `atlas migrate apply` is idempotent -- already-applied versions
# are skipped -- and records progress in the atlas_schema_revisions table. atlas.sum is rehashed on
# every migration change, so its digest is the natural replace trigger.
resource "terraform_data" "sqldb_migrate" {
  triggers_replace = [
    filesha256("${path.module}/migrations/atlas.sum"),
    # re-run when the target database server is (re)created, wiping the atlas_schema_revisions history
    var.db_server_token,
  ]

  provisioner "local-exec" {
    # working_dir scopes the relative `file://migrations` URL to the module directory.
    working_dir = path.module
    command     = "atlas migrate apply --dir ${local.migration_dir} --url \"$ATLAS_URL\""
    # Pass the URL (which embeds the password) via the environment, never argv, so the secret does
    # not appear in the process list.
    environment = {
      ATLAS_URL = local.atlas_url
    }
  }
}

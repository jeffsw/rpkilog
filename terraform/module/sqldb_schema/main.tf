terraform {
  required_version = ">= 1.15"
}

# Atlas connection URL passed to the `atlas` CLI. urlencode() guards against reserved characters in
# the credentials; the `maria://` scheme selects the MariaDB dialect.
#
# Schema changes are applied by shelling out to the pinned Atlas Community CLI (see .mise.toml)
# rather than the ariga/atlas Terraform provider. That provider's version check cannot parse the
# Community Edition's `atlas community ... version v1.2.0` banner -- it requires the official
# build's `atlas version v...` line and fails with "unexpected output format" before it ever
# connects -- and no released provider version fixes this. The CLI is the same binary the provider
# would have driven, so the versioned-migrations workflow is unchanged.
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

  # Latest migration version in the directory: the filename prefix before the first underscore
  # (e.g. "20260625000000"). `atlas migrate apply` brings the database up to this version.
  latest_migration_version = element(
    reverse(sort([for f in fileset("${path.module}/migrations", "*.sql") : split("_", f)[0]])),
    0,
  )
}

# Applies every pending migration up to the latest version in the directory. `atlas migrate apply`
# is idempotent -- already-applied versions are skipped -- and records progress in the
# atlas_schema_revisions table, exactly as the provider's atlas_migration resource did.
#
# Re-runs whenever the migration set changes: atlas.sum is rehashed (`atlas migrate hash`) on every
# migration change, so its digest is the natural replace trigger. atlas migrate apply also verifies
# the directory against atlas.sum, so a stale sum fails loudly rather than applying silently.
resource "terraform_data" "sqldb_migrate" {
  triggers_replace = [
    filesha256("${path.module}/migrations/atlas.sum"),
    # Re-run when the target database server is (re)created (e.g. a dev VM replace): a wiped server
    # loses the atlas_schema_revisions history along with the data, so the schema must be reapplied.
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

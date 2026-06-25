# `CREATE DATABASE ...`
resource "mysql_database" "rpkilog" {
  name = local.mariadb_1_database_name
}

# manages the database schema
module "snapshot_db_schema" {
  source = "../../module/snapshot_db_schema"

  db_host     = aws_route53_record.mariadb_1_A.fqdn
  db_user     = local.mariadb_1_admin_username
  db_password = random_password.mariadb_1_admin.result
  db_schema   = mysql_database.rpkilog.name
}

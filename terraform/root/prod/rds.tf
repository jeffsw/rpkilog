# Prod MariaDB (RDS) for the snapshot-tracking database (GH-81).  Dev runs an incus VM instead --
# see terraform/root/dev/mariadb_1.tf and sqldb.tf, which this mirrors at the user/database layer.
#
# TLS: RDS cannot serve a customer/ACM certificate (there is no API to install one), so clients
# verify in verify-CA mode against AWS's RDS CA bundle
# (https://truststore.pki.rds.amazonaws.com/us-east-1/us-east-1-bundle.pem): chain of trust is
# checked but not hostname, because the server cert names only the *.rds.amazonaws.com endpoint,
# not our mariadb-1.rpkilog.com CNAME.

locals {
  mariadb1_cloudwatch_log_exports = ["error", "iam-db-auth-error", "slowquery"]
  mariadb1_database_name          = "rpkilog"
  rds_availability_zones          = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

data "aws_vpc" "main" {
  id = "vpc-017778d8fedbe2ee7"
}

# Subnets are discovered by filter, never hard-coded by ID; add filters as placement needs evolve.
data "aws_subnets" "mariadb1" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.main.id]
  }
  filter {
    name   = "availability-zone"
    values = local.rds_availability_zones
  }
}

resource "aws_db_subnet_group" "mariadb1" {
  name       = "rds-public"
  subnet_ids = data.aws_subnets.mariadb1.ids
}

# Two Security Groups are attached to the instance, split by who manages the rules:
#   - db_tf_managed: rules managed purely by Terraform (the standalone rule resources below)
#   - db_cli_managed: created by Terraform, but its rules are managed exclusively by the
#     rpkilog-database-security-group CLI, which selects it by its applies_to + cli_managed
#     tags.  Terraform declares no rules for it, so the two never fight over a rule.
moved {
  from = aws_security_group.mariadb_1
  to   = aws_security_group.db_tf_managed
}

resource "aws_security_group" "db_tf_managed" {
  name        = "db_tf_managed"
  description = "rpkilog database access; rules managed by Terraform"
  vpc_id      = data.aws_vpc.main.id
  tags = {
    applies_to = "internet_database"
  }
  # Renaming a Security Group replaces it; create the new group first so the RDS instance can be
  # moved over before the old group is destroyed.
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "db_cli_managed" {
  name        = "db_cli_managed"
  description = "rpkilog database access; rules managed by rpkilog-database-security-group CLI"
  vpc_id      = data.aws_vpc.main.id
  tags = {
    applies_to  = "internet_database"
    cli_managed = "True"
  }
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "mariadb1_from_vpc" {
  security_group_id = aws_security_group.db_tf_managed.id
  description       = "from local vpc"
  cidr_ipv4         = data.aws_vpc.main.cidr_block
  ip_protocol       = "tcp"
  from_port         = 3306
  to_port           = 3306
}

resource "aws_vpc_security_group_ingress_rule" "mariadb1_from_rpkiclient" {
  security_group_id = aws_security_group.db_tf_managed.id
  description       = "rpkiclient linode (rpkiclient.rpkilog.com)"
  cidr_ipv4         = "${one(linode_instance.rpkiclient.ipv4)}/32"
  ip_protocol       = "tcp"
  from_port         = 3306
  to_port           = 3306
}

resource "aws_db_parameter_group" "mariadb1" {
  name   = "mariadb-1"
  family = "mariadb11.8"

  # facilitate cloudwatch logging
  parameter {
    name  = "log_output"
    value = "FILE"
  }
  parameter {
    name  = "log_slow_query"
    value = "1"
  }

  # require TLS for all clients, both password & IAM authenticated
  parameter {
    name  = "require_secure_transport"
    value = "1"
  }
}

# Pre-created so retention is Terraform-managed; RDS otherwise auto-creates these groups with
# retention never-expire.  Names must match /aws/rds/instance/<identifier>/<log>.
resource "aws_cloudwatch_log_group" "mariadb1" {
  for_each          = toset(local.mariadb1_cloudwatch_log_exports)
  name              = "/aws/rds/instance/mariadb-1/${each.value}"
  retention_in_days = 90
}

resource "aws_db_instance" "mariadb1" {
  identifier                          = "mariadb-1"
  allocated_storage                   = 20
  backup_retention_period             = 35
  ca_cert_identifier                  = "rds-ca-rsa2048-g1"
  copy_tags_to_snapshot               = true
  db_name                             = local.mariadb1_database_name
  db_subnet_group_name                = aws_db_subnet_group.mariadb1.name
  deletion_protection                 = false
  enabled_cloudwatch_logs_exports     = local.mariadb1_cloudwatch_log_exports
  engine                              = "mariadb"
  engine_version                      = "11.8.8"
  final_snapshot_identifier           = "mariadb-1-final"
  iam_database_authentication_enabled = true
  instance_class                      = "db.t4g.micro"
  max_allocated_storage               = 20
  multi_az                            = false
  parameter_group_name                = aws_db_parameter_group.mariadb1.name
  publicly_accessible                 = true
  storage_type                        = "gp3"
  vpc_security_group_ids = [
    aws_security_group.db_tf_managed.id,
    aws_security_group.db_cli_managed.id,
  ]

  # rds_master password will be stored in Secrets Manager and automatically rotated
  username                    = "rds_master"
  manage_master_user_password = true

  depends_on = [aws_cloudwatch_log_group.mariadb1]
}

resource "aws_route53_record" "mariadb_1_CNAME" {
  zone_id = data.aws_route53_zone.rpkilog_tld.id
  name    = "mariadb-1"
  type    = "CNAME"
  ttl     = 300
  records = [aws_db_instance.mariadb1.address]
}

data "aws_secretsmanager_secret_version" "mariadb1_master" {
  secret_id = aws_db_instance.mariadb1.master_user_secret[0].secret_arn
}

resource "random_password" "mariadb1_admin" {
  length  = 24
  lower   = true
  numeric = true
  special = false
  upper   = true
}

# Static-password admin for Atlas/terraform/deployment usage (the rotating master stays out of
# day-to-day tooling).
resource "mysql_user" "mariadb1_admin" {
  user               = "admin"
  host               = "%"
  plaintext_password = random_password.mariadb1_admin.result
}

resource "mysql_grant" "mariadb1_admin" {
  user       = mysql_user.mariadb1_admin.user
  host       = mysql_user.mariadb1_admin.host
  database   = local.mariadb1_database_name
  privileges = ["ALL PRIVILEGES"]
  grant      = true
}

# Developer logs in with a short-lived IAM auth token (aws rds generate-db-auth-token) instead of
# a password; the caller also needs rds-db:connect IAM permission for this instance + user.
resource "mysql_user" "mariadb1_developer" {
  user        = "developer"
  host        = "%"
  auth_plugin = "AWSAuthenticationPlugin"
}

resource "mysql_grant" "mariadb1_developer" {
  user       = mysql_user.mariadb1_developer.user
  host       = mysql_user.mariadb1_developer.host
  database   = local.mariadb1_database_name
  privileges = ["ALL PRIVILEGES"]
  grant      = true
}

output "mariadb1_endpoint" {
  description = "mariadb-1 RDS endpoint hostname (also aliased as mariadb-1.rpkilog.com)"
  type        = string
  value       = aws_db_instance.mariadb1.address
}

output "mariadb1_admin_username" {
  description = "MariaDB admin (Atlas/terraform/deployment) username on mariadb-1.rpkilog.com"
  type        = string
  value       = mysql_user.mariadb1_admin.user
}

output "mariadb1_admin_password" {
  description = "MariaDB admin (Atlas/terraform/deployment) password on mariadb-1.rpkilog.com"
  type        = string
  value       = nonsensitive(random_password.mariadb1_admin.result)
}

output "mariadb1_developer_username" {
  description = "MariaDB developer user; authenticates via IAM auth token, no password"
  type        = string
  value       = mysql_user.mariadb1_developer.user
}

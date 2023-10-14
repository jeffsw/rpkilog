terraform {
    backend "s3" {
        bucket = "rpkilog-terraform"
        dynamodb_table = "rpkilog-terraform"
        key = "main"
        region = "us-east-1"
    }
    required_providers {
        aws = {
            source = "hashicorp/aws"
        }
        opensearch = {
            source = "opensearch-project/opensearch"
        }
    }
}

variable "rpkilog_idp_google_client_id" {
    description = "Client ID used to identify ourselves to Google for federated auth"
    type = string
}

variable "rpkilog_idp_google_client_secret" {
    description = "Secret used to authenticate ourselves to Google for federated auth"
    type = string
    sensitive = true
}

variable "aws_subnet_ids" {
    description = "List of AWS subnet IDs"
    type = set(string)
    default = [
        "subnet-052d585f76f551e79",
        "subnet-0ba4127fc7ffa146e",
        "subnet-0774b9b19bf6f3fc4",
        "subnet-056f4cd1a33e2e5ac",
        "subnet-0fa104bced02ea8dc",
        "subnet-046b1d24b6e34d4d8"
    ]
}

provider "aws" {
    region = "us-east-1"
    default_tags {
        tags = {
            tf_managed = "main"
        }
    }
}

provider "opensearch" {
    # This provider is quite fragile and buggy.  It requires aws_profile & aws_region even if AWS_PROFILE
    # environment variable is set.
    url = "https://es-prod.rpkilog.com:443"
    aws_assume_role_arn = "arn:aws:iam::054500078560:role/es_superuser"
    aws_profile = "rpkilog"
    aws_region = "us-east-1"
    healthcheck = true
}

##############################
# Caller
data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

##############################
# SSH key-pairs

resource "aws_key_pair" "jeffsw" {
    key_name = "jeffsw-boomer"
    tags = {
        user = "jeffsw"
    }
    public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC4k8nVaS9Ns+8jZ1C97eUcOvkFw6NOXS8e4xxG6XEH1l9PDluOCxAqgCvdKxX9ZhFvwW1SCSWuN95WrM7u/9p0flOX7DZFYld053ClWxMZZ4ZtKj8XWnmDU4LLXSmUWaKddW9pHZHvxfEFu+wCcnUiJM4NgS4owfaIGC3IOIXVrxsoNuoKyTQS9pRa5+3sMC3rHK8oWPkleJGO+cs8AxuetRtHS/ZHwshsyI27ROC/nIxZ7ZeKXf3g/jxEpbxI9LNFnocuUmeoNpndBFYND1ujwiHZvoWxx4ByiTRDNJDHJWdnJpz8rOmnoHeHFqV8F/I5CRG9Dh7aq5vd9LWdrkqb jeffsw6@gmail.com boomer 2013-05-28"
}

##############################
# Certificates
# This needs to be manually created.
# When ready to create certs as part of terraform workflow, see this helpful example:
# https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/acm_certificate_validation
resource "aws_acm_certificate" "api_rpkilog_com" {
    domain_name = "api.rpkilog.com"
    validation_method = "DNS"
    lifecycle {
        create_before_destroy = true
    }
}

resource "aws_acm_certificate_validation" "api_rpkilog_com" {
    # Waits for certificate validation
    certificate_arn = aws_acm_certificate.api_rpkilog_com.arn
    validation_record_fqdns = [
        for record in aws_route53_record.validate_acm_for_api_rpkilog_com : record.fqdn
    ]
}

data "aws_acm_certificate" "es_prod" {
    domain = "es-prod.rpkilog.com"
    statuses = [ "ISSUED" ]
}

data "aws_acm_certificate" "rpkilog_com" {
    domain = "rpkilog.com"
    statuses = [ "ISSUED" ]
}

##############################
# IAM roles
data "aws_iam_policy" "AmazonAPIGatewayPushToCloudWatchLogs" {
    name = "AmazonAPIGatewayPushToCloudWatchLogs"
    #arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_iam_role" "apigw_logging_accountwide_role" {
    # If a terraform apply error like "CloudWatch Logs role ARN must be set in account settings to enable logging"
    # even though it is set by this resource, retry the apply operation after a minute.
    # It seems like terraform thinks the modification is complete even though it isn't.  Probably an AWS
    # race condition.
    name = "apigw_logging_accountwide_role"
    assume_role_policy = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowApiGwToAssumeThisRole",
            "Effect": "Allow",
            "Principal": {
                "Service": "apigateway.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}
POLICY
    managed_policy_arns = [
        data.aws_iam_policy.AmazonAPIGatewayPushToCloudWatchLogs.arn
    ]
}

resource "aws_iam_role" "ec2_cron1" {
    name = "ec2_cron1"
    assume_role_policy = file("aws_iam/ec2_generic_assume_role.json")
    inline_policy {
        name = "ec2_cron1"
        policy = file("aws_iam/ec2_cron1.json")
    }
}

data "aws_iam_policy" "AmazonOpenSearchServiceCognitoAccess" {
    name = "AmazonOpenSearchServiceCognitoAccess"
}

resource "aws_iam_role" "es_superuser" {
    name = "es_superuser"
    description = "ElasticSearch superuser"
    assume_role_policy = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "AWS": "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
            },
            "Action": "sts:AssumeRole"
        },
        {
            "Effect": "Allow",
            "Principal": {
                "Federated": "cognito-identity.amazonaws.com"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    "cognito-identity.amazonaws.com:aud": "${aws_cognito_identity_pool.es.id}"
                },
                "ForAnyValue:StringLike": {
                    "cognito-identity.amazonaws.com:amr": "authenticated"
                }
            }
        }
    ]
}
POLICY
    inline_policy {
        name = "es_superuser"
        policy = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "es:ESHttp*"
            ],
            "Resource": [
                "arn:aws:es:*:*:*"
            ]
        }
    ]
}
POLICY
    }
    depends_on = [
        aws_cognito_identity_pool.es
    ]
}

resource "aws_iam_role" "es_master" {
    name = "es_master"
    assume_role_policy = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "AWS": "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
            },
            "Action": "sts:AssumeRole"
        },
        {
            "Effect": "Allow",
            "Principal": {
                "Federated": "cognito-identity.amazonaws.com"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    "cognito-identity.amazonaws.com:aud": "${aws_cognito_identity_pool.es.id}"
                },
                "ForAnyValue:StringLike": {
                    "cognito-identity.amazonaws.com:amr": "authenticated"
                }
            }
        },
        {
            "Action": "sts:AssumeRole",
            "Principal": {
                "Service": "lambda.amazonaws.com"
            },
            "Effect": "Allow"
        }
    ]
}
POLICY
    inline_policy {
        name = "es_master"
        policy = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "es:ESHttp*"
            ],
            "Resource": [
                "arn:aws:es:*:*:*"
            ]
        },
        {
            "Sid": "Log",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": [
                "arn:aws:logs:*:*:log-group:/aws/lambda/hapi",
                "arn:aws:logs:*:*:log-group:/aws/lambda/hapi:log-stream:*"
            ]
        }
    ]
}
POLICY
    }
    depends_on = [
        aws_cognito_identity_pool.es
    ]
}
resource "aws_iam_role" "anonymous_web" {
    name = "anonymous_web"
    assume_role_policy = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {
            "Federated": "cognito-identity.amazonaws.com"
        },
        "Action": "sts:AssumeRoleWithWebIdentity",
        "Condition": {
            "StringEquals": {
                "cognito-identity.amazonaws.com:aud": "${aws_cognito_identity_pool.es.id}"
            },
            "ForAnyValue:StringLike": {
                "cognito-identity.amazonaws.com:amr": "unauthenticated"
            }
        }
    }]
}
POLICY
    inline_policy {
        name = "anonymous_web"
        policy = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "es:ESHttp*"
            ],
            "Resource": [
                "arn:aws:es:*:*:*"
            ]
        }
    ]
}
POLICY
    }
    depends_on = [
        aws_cognito_identity_pool.es
    ]
}

resource "aws_iam_role" "authenticated_web" {
    name = "authenticated_web"
    assume_role_policy = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {
            "Federated": "cognito-identity.amazonaws.com"
        },
        "Action": "sts:AssumeRoleWithWebIdentity",
        "Condition": {
            "StringEquals": {
                "cognito-identity.amazonaws.com:aud": "${aws_cognito_identity_pool.es.id}"
            },
            "ForAnyValue:StringLike": {
                "cognito-identity.amazonaws.com:amr": "authenticated"
            }
        }
    }]
}
POLICY
    inline_policy {
        name = "authenticated_web"
        policy = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "es:ESHttp*"
            ],
            "Resource": [
                "arn:aws:es:*:*:*"
            ]
        }
    ]
}
POLICY
    }
    depends_on = [
        aws_cognito_identity_pool.es
    ]
}

resource "aws_iam_role" "es_cognito" {
    name = "es_cognito"
    description = "ElasticSearch/OpenSearch runs as this role.  The policy is a managed policy supplied by AWS."
    managed_policy_arns = [
        data.aws_iam_policy.AmazonOpenSearchServiceCognitoAccess.arn
    ]
    assume_role_policy = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "es.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}
POLICY
}

resource "aws_iam_role" "lambda_archive_site_crawler" {
    name = "lambda_archive_site_crawler"
    assume_role_policy = file("aws_iam/lambda_generic_assume_role_policy.json")
    inline_policy {
        name = "lambda_archive_site_crawler"
        policy = file("aws_iam/lambda_archive_site_crawler.json")
    }
}

resource "aws_iam_role" "lambda_snapshot_ingest" {
    name = "lambda_snapshot_ingest"
    assume_role_policy = file("aws_iam/lambda_generic_assume_role_policy.json")
    inline_policy {
        name = "lambda_snapshot_ingest"
        policy = file("aws_iam/lambda_snapshot_ingest-policy.json")
    }
}

resource "aws_iam_role" "lambda_vrp_cache_diff" {
    name = "lambda_vrp_cache_diff"
    assume_role_policy = file("aws_iam/lambda_generic_assume_role_policy.json")
    inline_policy {
        name = "lambda_vrp_cache_diff"
        policy = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:GetObjectTagging",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::rpkilog-snapshot-summary",
                "arn:aws:s3:::rpkilog-snapshot-summary/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:GetObjectTagging",
                "s3:ListBucket",
                "s3:PutObject",
                "s3:PutObjectAcl",
                "s3:PutObjectRetention",
                "s3:PutObjectTagging"
            ],
            "Resource": [
                "arn:aws:s3:::rpkilog-diff",
                "arn:aws:s3:::rpkilog-diff/*"
            ]
        },
        {
            "Sid": "DeadLetterQueue",
            "Effect": "Allow",
            "Action": [
                "sqs:SendMessage"
            ],
            "Resource": [
                "${aws_sqs_queue.lambda_dlq_for_vrp_cache_diff.arn}"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": [
                "arn:aws:logs:*:*:*"
            ]
        }
    ]
}
POLICY
    }
}

resource "aws_iam_role" "lambda_diff_import" {
    name = "lambda_diff_import"
    assume_role_policy = file("aws_iam/lambda_generic_assume_role_policy.json")
    inline_policy {
        name = "lambda_diff_import"
        policy = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "S3Read",
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:GetObjectTagging",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::rpkilog-diff",
                "arn:aws:s3:::rpkilog-diff/*"
            ]
        },
        {
            "Sid": "ES",
            "Effect": "Allow",
            "Action": [
                "es:ESHttp*"
            ],
            "Resource": [
                "arn:aws:es:*:*:*"
            ]
        },
        {
            "Sid": "Log",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": [
                "arn:aws:logs:*:*:*"
            ]
        }
    ]
}
POLICY
    }
}

##############################
# IAM users
resource "aws_iam_user" "jeffsw" {
    name = "jeffsw"
}

resource "aws_iam_user" "es_master" {
    name = "es_master"
}

##############################
# IAM groups
resource "aws_iam_group" "superusers" {
    name = "superusers"
}
resource "aws_iam_group_membership" "superusers" {
    name = "superusers"
    group = aws_iam_group.superusers.name
    users = [
        aws_iam_user.jeffsw.name
    ]
}
resource "aws_iam_group_policy_attachment" "superusers" {
    group = aws_iam_group.superusers.name
    policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

resource "aws_iam_group_policy" "es_master" {
    name = "es_master"
    group = aws_iam_group.es_master.name
    policy = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "sts:AssumeRole",
            "Resource": "arn:aws:iam:::role/es_master"
        }
    ]
}
POLICY
}
resource "aws_iam_group" "es_master" {
    name = "es_master"
}
resource "aws_iam_group_membership" "es_master" {
    name = "es_master"
    group = aws_iam_group.es_master.name
    users = [ aws_iam_user.es_master.name ]
}

##############################
# SNS
resource "aws_sns_topic" "lambda_dead_letter_queue_for_diff" {
    name = "lambda_dead_letter_queue_for_diff"
}

##############################
# SQS
resource "aws_sqs_queue" "lambda_dlq_for_vrp_cache_diff" {
    name = "lambda_dlq_for_vrp_cache_diff"
    max_message_size = 2048
    message_retention_seconds = 1209600 # 14 days
}

##############################
# Cognito
resource "aws_cognito_user_pool" "es" {
    name = "es"
    username_attributes = [ "email" ]
    admin_create_user_config {
        allow_admin_create_user_only = false
    }
}
resource "aws_cognito_user_pool_domain" "es" {
    domain = "rpkilog-es"
    user_pool_id = aws_cognito_user_pool.es.id
}
resource "aws_cognito_user_group" "es_master" {
    name = "es_master"
    user_pool_id = aws_cognito_user_pool.es.id
    description = "Users given AllAccess within ES"
    role_arn = aws_iam_role.es_master.arn
    precedence = 2
}
resource "aws_cognito_user_group" "es_superuser" {
    name = "es_superuser"
    user_pool_id = aws_cognito_user_pool.es.id
    role_arn = aws_iam_role.es_superuser.arn
    precedence = 1
}

resource "aws_cognito_identity_provider" "google" {
    user_pool_id = aws_cognito_user_pool.es.id
    provider_name = "Google"
    provider_type = "Google"
    provider_details = {
        authorize_scopes = "email"
        client_id = var.rpkilog_idp_google_client_id
        client_secret = var.rpkilog_idp_google_client_secret
    }
    attribute_mapping = {
        # cognito user pool attribute = google attribute
        email = "email"
        username = "sub"
    }
    lifecycle {
        ignore_changes = [ provider_details ]
    }
}

resource "aws_cognito_managed_user_pool_client" "es_prod" {
    # This has the string "prod" instead of a reference to aws_elasticsearch_domain.prod.domain_name
    # because the reference would create a circular reference
    name_prefix = "AmazonOpenSearchService-prod-${data.aws_region.current.name}-"
    user_pool_id = aws_cognito_user_pool.es.id

    allowed_oauth_flows = [ "code" ]
    allowed_oauth_scopes = [ "aws.cognito.signin.user.admin", "email", "openid", "phone", "profile" ]
    prevent_user_existence_errors = "LEGACY"
    supported_identity_providers = [ "COGNITO", "Google" ]
}

resource "aws_cognito_identity_pool" "es" {
    identity_pool_name = "es"
    allow_unauthenticated_identities = false
    allow_classic_flow = false
    cognito_identity_providers {
        client_id = aws_cognito_managed_user_pool_client.es_prod.id
        provider_name = aws_cognito_user_pool.es.endpoint
        server_side_token_check = true
    }
    lifecycle {
        ignore_changes = [ cognito_identity_providers ]
    }
}
resource "aws_cognito_identity_pool_roles_attachment" "es" {
    identity_pool_id = aws_cognito_identity_pool.es.id
    roles = {
        authenticated = aws_iam_role.authenticated_web.arn
        unauthenticated = aws_iam_role.anonymous_web.arn
    }
    role_mapping {
        identity_provider = "${aws_cognito_user_pool.es.endpoint}:${aws_cognito_managed_user_pool_client.es_prod.id}"
        ambiguous_role_resolution = "AuthenticatedRole"
        type = "Token"
    }
}

resource "aws_cognito_user" "internal_jeffsw6_at_gmail_dot_com" {
    user_pool_id = aws_cognito_user_pool.es.id
    username = "4a0d8508-1278-4ed5-a9a9-68729ce4ce26"
    attributes = {
        # TODO add a tf_managed attribute to the user pool schema?
        # see https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cognito_user_pool#schema
        #tf_managed = "main"
        email = "jeffsw6@gmail.com"
        email_verified = true
        sub = "4a0d8508-1278-4ed5-a9a9-68729ce4ce26"
    }
}

resource "aws_cognito_user_in_group" "internal_jeffsw6_at_gmail_dot_com__es_superuser" {
    user_pool_id = aws_cognito_user_pool.es.id
    group_name = aws_cognito_user_group.es_superuser.name
    username = aws_cognito_user.internal_jeffsw6_at_gmail_dot_com.username
}

##############################
# VPCs
resource "aws_default_vpc" "default" {
}

##############################
# Get default security group of default VPC
resource "aws_default_security_group" "default" {
    vpc_id = aws_default_vpc.default.id
}

##############################
# Security Groups
resource "aws_security_group" "https_allow" {
    name = "https_allow"
    description = "Allow HTTPS traffic from anywhere."
    vpc_id = aws_default_vpc.default.id
    egress {
        from_port = 0
        to_port = 0
        protocol = "-1"
        cidr_blocks = ["0.0.0.0/0"]
        ipv6_cidr_blocks = ["::/0"]
    }
    ingress {
        description = "HTTPS"
        cidr_blocks = [ "0.0.0.0/0" ]
        ipv6_cidr_blocks = [ "::/0" ]
        from_port = 0
        protocol = "tcp"
        to_port = 443
    }
}

##############################
# VPC Gateway Endpoint so Lambda-in-VPC can access S3
# Alternatives to this are a NAT Gateway or an Interface VPC Endpoint
# However, this older VPC Gateway Endpoint has no associated usage costs.
resource "aws_vpc_endpoint" "default_vpc_s3_endpoint" {
    vpc_id = aws_default_vpc.default.id
    service_name = "com.amazonaws.us-east-1.s3"
    vpc_endpoint_type = "Gateway"
    route_table_ids = [ aws_default_vpc.default.default_route_table_id ]
}

##############################
# s3 buckets
resource "aws_s3_bucket" "rpkilog_artifact" {
    bucket = "rpkilog-artifact"
}

resource "aws_s3_bucket" "rpkilog_snapshot" {
    bucket = "rpkilog-snapshot"
}

resource "aws_s3_bucket" "rpkilog_snapshot_summary" {
    bucket = "rpkilog-snapshot-summary"
}

resource "aws_s3_bucket_acl" "private" {
    for_each = toset([
        aws_s3_bucket.rpkilog_artifact.id,
        aws_s3_bucket.rpkilog_snapshot.id,
        aws_s3_bucket.rpkilog_snapshot_summary.id,
    ])
    bucket = each.value
    acl = "private"
}

resource "aws_s3_bucket" "rpkilog_diff" {
    bucket = "rpkilog-diff"
}

resource "aws_s3_bucket_acl" "public_read" {
    for_each = toset([
        aws_s3_bucket.rpkilog_diff.id,
        aws_s3_bucket.rpkilog_www.id,
    ])
    bucket = each.value
    acl = "public-read"
}

resource "aws_s3_bucket" "rpkilog_www" {
    bucket = "rpkilog-www"
}

resource "aws_s3_bucket_lifecycle_configuration" "snapshot" {
    bucket = aws_s3_bucket.rpkilog_snapshot.id
    rule {
        id = "1"
        abort_incomplete_multipart_upload {
            days_after_initiation = 2
        }
        expiration {
            days = 40
        }
        status = "Enabled"
    }
}

resource "aws_s3_bucket_policy" "rpkilog_www" {
    bucket = aws_s3_bucket.rpkilog_www.id
    policy = <<EOF
        {
            "Version": "2008-10-17",
            "Statement": [
                {
                    "Sid": "AllowPublicRead",
                    "Effect": "Allow",
                    "Principal": {"AWS": "*"},
                    "Action": [
                        "s3:GetObject"
                    ],
                    "Resource": [
                        "arn:aws:s3:::rpkilog-www/*"
                    ]
                }
            ]
        }
    EOF
}

resource "aws_s3_bucket_website_configuration" "rpkilog_www" {
    bucket = aws_s3_bucket.rpkilog_www.bucket
    index_document {
        suffix = "index.html"
    }
}

##############################
# lambda functions & permissions

# Moved into cron1 EC2 VM
# resource "aws_lambda_function" "archive_site_crawler" {
#     function_name = "archive_site_crawler"
#     filename = "misc/terraform_lambda_placeholder_python.zip"
#     role = aws_iam_role.lambda_archive_site_crawler.arn
#     runtime = "python3.11"
#     handler = "rpkilog.ArchiveSiteCrawler.aws_lambda_entry_point"
#     memory_size = 256
#     timeout = 240
#     environment {
#         variables = {
#             s3_snapshot_bucket_name = aws_s3_bucket.rpkilog_snapshot.id
#             s3_snapshot_summary_bucket_name = aws_s3_bucket.rpkilog_snapshot_summary.id
#             site_root = "http://josephine.sobornost.net/josephine.sobornost.net/rpkidata/"
#             job_max_downloads = 1
#         }
#     }
#     lifecycle {
#         # Never update the lambda deployment package.  We use another tool for that, not Terraform.
#         ignore_changes = [ filename ]
#     }
# }

resource "aws_lambda_function" "vrp_cache_diff" {
    function_name = "vrp_cache_diff"
    #TERRAFORM_FIRST needs an empty zip file here to succeed.
    #Once we have setup a CI/CD pipeline from our git repo, this might be fixable.
    #filename = "misc/terraform_lambda_placeholder_python.zip"
    s3_bucket = "rpkilog-artifact"
    s3_key = "lambda_vrp_cache_diff.zip"
    role = aws_iam_role.lambda_vrp_cache_diff.arn
    runtime = "python3.11"
    handler = "rpkilog.vrp_diff.aws_lambda_entry_point"
    memory_size = 1769
    timeout = 300
    environment {
        variables = {
            snapshot_summary_bucket = aws_s3_bucket.rpkilog_snapshot_summary.id
            diff_bucket = aws_s3_bucket.rpkilog_diff.id
        }
    }
    dead_letter_config {
        target_arn = aws_sqs_queue.lambda_dlq_for_vrp_cache_diff.arn
    }
    lifecycle {
        # Never update the lambda deployment package.  We use another tool for that, not Terraform.
        ignore_changes = [ filename ]
    }
}
resource "aws_lambda_permission" "vrp_cache_diff" {
    statement_id = "AllowExecutionFromS3Bucket"
    action = "lambda:InvokeFunction"
    function_name = aws_lambda_function.vrp_cache_diff.id
    principal = "s3.amazonaws.com"
    source_arn = aws_s3_bucket.rpkilog_snapshot_summary.arn
}
resource "aws_lambda_function_event_invoke_config" "vrp_cache_diff" {
    function_name = aws_lambda_function.vrp_cache_diff.function_name
    maximum_retry_attempts = 0
}

resource "aws_lambda_function" "diff_import" {
    function_name = "diff_import"
    s3_bucket = "rpkilog-artifact"
    s3_key = "lambda_diff_import.zip"
    role = aws_iam_role.lambda_diff_import.arn
    runtime = "python3.11"
    handler = "rpkilog.vrp_diff.aws_lambda_entry_point_import"
    memory_size = 256
    timeout = 300
    environment {
        variables = {
            es_endpoint = aws_elasticsearch_domain.prod.endpoint
        }
    }
    lifecycle {
        ignore_changes = [ filename ]
    }
}
resource "aws_lambda_permission" "diff_import" {
    statement_id = "AllowExecutionFromS3Bucket"
    action = "lambda:InvokeFunction"
    function_name = aws_lambda_function.diff_import.function_name
    principal = "s3.amazonaws.com"
    source_arn = aws_s3_bucket.rpkilog_diff.arn
}
resource "aws_lambda_function_event_invoke_config" "diff_import" {
    function_name = aws_lambda_function.diff_import.function_name
    maximum_retry_attempts = 0
}

##############################
# begin lambda: hapi
# hapi can be invoked by anyone from the web like https://<aws-generated>.lambda-url.<region>.on.aws
resource "aws_lambda_function" "hapi" {
    function_name = "hapi"
    s3_bucket = "rpkilog-artifact"
    s3_key = "lambda_hapi.zip"
    #TODO: try changing to anonymous_web role.  Eventually, create separate role.
    role = aws_iam_role.es_master.arn
    runtime = "python3.11"
    handler = "rpkilog.hapi.aws_lambda_entry_point"
    memory_size = 512
    timeout = 30
    environment {
        variables = {
            RPKILOG_ES_HOST = "es-prod.rpkilog.com"
            es_endpoint = aws_elasticsearch_domain.prod.endpoint
        }
    }
    lifecycle {
        ignore_changes = [ filename ]
    }
}
#FIXME: Correct permissions issues.  Currently, it is too permissive.
#       See https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway.html#apigateway-permissions
resource "aws_lambda_permission" "hapi_by_apigw" {
    # Allow APIGW to invoke the hapi lambda
    function_name = aws_lambda_function.hapi.function_name
    statement_id = "AllowApiGateway"
    action = "lambda:invokeFunction"
    principal = "apigateway.amazonaws.com"
}
resource "aws_lambda_permission" "hapi" {
    # Allow function URL to invoke the hapi lambda
    function_name = aws_lambda_function.hapi.function_name
    statement_id = "AllowExecutionFromWeb"
    action = "lambda:InvokeFunction"
    #FIXME: This should be something like lambda.amazonaws.com, not "*"
    principal = "*"
}
resource "aws_lambda_function_url" "hapi" {
    function_name = aws_lambda_function.hapi.function_name
    authorization_type = "NONE"
    cors {
        allow_credentials = true
        allow_methods = [ "*" ]
        allow_origins = [ "*" ]
        max_age = 600
    }
}
# end lambda: hapi
##############################

##############################
# s3 bucket notifications
resource "aws_s3_bucket_notification" "vrp_cache_diff" {
    bucket = aws_s3_bucket.rpkilog_snapshot_summary.id
    lambda_function {
        lambda_function_arn = aws_lambda_function.vrp_cache_diff.arn
        events = [ "s3:ObjectCreated:*" ]
    }
    depends_on = [
        aws_lambda_permission.vrp_cache_diff
    ]
}

resource "aws_s3_bucket_notification" "vrp_diff_import" {
    bucket = aws_s3_bucket.rpkilog_diff.id
    lambda_function {
        lambda_function_arn = aws_lambda_function.diff_import.arn
        events = [ "s3:ObjectCreated:*" ]
    }
    depends_on = [
        aws_lambda_permission.diff_import
    ]
}

##############################
# EC2 Instance Profiles
resource "aws_iam_instance_profile" "cron1" {
    name = "cron1"
    role = aws_iam_role.ec2_cron1.name
}

##############################
# EC2 AMIs
data "aws_ami" "ubuntu_x86" {
    owners = ["099720109477"] # Canonical official Ubuntu AMIs
    most_recent = true
    filter {
        name = "name"
        values = [
            "ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*"
        ]
    }
    filter {
        name = "root-device-type"
        values = [ "ebs" ]
    }
    filter {
        name = "virtualization-type"
        values = [ "hvm" ]
    }
}

data "aws_ami" "rpkilog_ubuntu2004" {
    owners = ["054500078560"] # rpkilog account
    most_recent = true
    filter {
        name = "name"
        values = [
            "rpkilog"
        ]
    }
    filter {
        name = "root-device-type"
        values = [ "ebs" ]
    }
    filter {
        name = "virtualization-type"
        values = [ "hvm" ]
    }
}

##############################
# EC2 Security Groups
resource "aws_security_group" "util_vm" {
    name = "util_vm"
    description = "Allow SSH access"
    ingress {
        from_port = 0
        to_port = 22
        protocol = "tcp"
        cidr_blocks = ["0.0.0.0/0"]
        ipv6_cidr_blocks = ["::/0"]
    }
    egress {
        from_port = 0
        to_port = 0
        protocol = "-1"
        cidr_blocks = ["0.0.0.0/0"]
        ipv6_cidr_blocks = ["::/0"]
    }
}

##############################
# EC2 Instances

# This EC2 instance is setup to be capable of running cron jobs similar to our lambda jobs.
# See #2 for details: https://github.com/jeffsw/rpkilog/issues/2
resource "aws_instance" "cron1" {
    tags = {
        Name = "cron1"
    }
    instance_type = "t3.small"
    iam_instance_profile = aws_iam_instance_profile.cron1.name
    ami = data.aws_ami.rpkilog_ubuntu2004.id
    key_name = "jeffsw-boomer"
    user_data = <<EOF
#!/bin/bash
echo cron1 > /etc/hostname
hostname cron1
EOF
    vpc_security_group_ids = [
        aws_security_group.util_vm.id
    ]
    lifecycle {
        ignore_changes = [ user_data ]
    }
}

##############################
# ElasticSearch / OpenSearch
# Managing ES with Terraform is quite buggy.  Went through several permutations of config before working
# around this issue: https://github.com/hashicorp/terraform-provider-aws/issues/13552

#This configuration is intended for IAM ES-API auth and Cognito Dashboards/Kibana auth
resource "aws_elasticsearch_domain" "prod" {
    domain_name = "prod"
    elasticsearch_version = "OpenSearch_2.9"
    # I'm worried Principal: AWS should be "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
    # to avoid granting access to random public, but maybe that's why we have advanced_security_options?
    access_policies = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": { "AWS": "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" },
            "Action": [
                "es:ESHttp*"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Principal": { "AWS": "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" },
            "Action": [
                "*"
            ],
            "Resource": "*"
        }
    ]
}
POLICY
    advanced_security_options {
        enabled = true
        internal_user_database_enabled = false
        master_user_options {
            master_user_arn = aws_iam_role.es_master.arn
        }
    }
    cluster_config {
        # Instance types: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/supported-instance-types.html
        instance_type = "t3.medium.elasticsearch"
        instance_count = 1
        zone_awareness_enabled = false
    }
    cognito_options {
        enabled = true
        user_pool_id = aws_cognito_user_pool.es.id
        identity_pool_id = aws_cognito_identity_pool.es.id
        role_arn = aws_iam_role.es_cognito.arn
    }
    domain_endpoint_options {
        custom_endpoint_enabled = true
        custom_endpoint = "es-prod.rpkilog.com"
        custom_endpoint_certificate_arn = data.aws_acm_certificate.es_prod.arn
        enforce_https = true
        # AWS API error w/o tls_security_policy because tf seemed to set it to an empty string
        tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
    }
    ebs_options {
        ebs_enabled = true
        volume_size = 200
        volume_type = "gp3" # gp3 not supported by current version of aws_elasticsearch_domain
    }
    encrypt_at_rest {
        enabled = true
    }
    lifecycle {
        #WORKAROUND AWS provider 4.49.0 doesn't recognize ebs_options.iops = 3000 is a default.
        ignore_changes = [ ebs_options["iops"] ]
    }
    node_to_node_encryption {
        enabled = true
    }
    snapshot_options {
        automated_snapshot_start_hour = 4
    }
    depends_on = [
        aws_cognito_identity_pool.es,
        aws_cognito_user_pool.es
    ]
}

//noinspection MissingProperty
resource "opensearch_role" "anonymous" {
    #name = "anonymous" # pycharm demands `name` but documentation wants `role_name`.  Added a noinspection.
    role_name = "anonymous"
    cluster_permissions = [
        "cluster_composite_ops_ro",
        "cluster_monitor"
    ]
    index_permissions {
        index_patterns = [ "diff-*" ]
        allowed_actions = [ "indices_monitor", "read" ]
    }
    index_permissions {
        index_patterns = [ "*" ]
        allowed_actions = [ "indices_monitor", "read" ]
    }
    tenant_permissions {
        tenant_patterns = [ "global_tenant" ]
        allowed_actions = [ "kibana_all_read" ]
    }
    depends_on = [ aws_elasticsearch_domain.prod ]
}

resource "opensearch_roles_mapping" "all_access" {
    role_name = "all_access"
    users = [
        # TODO: add a resource and replace this with a reference to it
        "arn:aws:iam::054500078560:user/jeffsw6@gmail.com",
    ]
    backend_roles = [
        aws_iam_role.ec2_cron1.arn,
        aws_iam_role.es_superuser.arn,
    ]
    depends_on = [ aws_elasticsearch_domain.prod ]
}

resource "opensearch_roles_mapping" "anonymous" {
    role_name = "anonymous"
    backend_roles = [
        # TODO replace with references
        "arn:aws:iam::054500078560:role/anonymous_web",
        "arn:aws:iam::054500078560:role/es_master",
    ]
    depends_on = [ aws_elasticsearch_domain.prod ]
}

resource "opensearch_roles_mapping" "logstash" {
    role_name = "logstash"
    backend_roles = [
        # TODO replace with references
        "arn:aws:iam::054500078560:role/lambda_diff_import"
    ]
    depends_on = [ aws_elasticsearch_domain.prod ]
}

resource "opensearch_roles_mapping" "security_manager" {
    role_name = "security_manager"
    backend_roles = [
        # TODO replace with references
        "arn:aws:iam::054500078560:role/es_superuser"
    ]
    depends_on = [ aws_elasticsearch_domain.prod ]
}

##############################
# Route53
resource "aws_route53_zone" "rpkilog_com" {
    name = "rpkilog.com"
}

resource "aws_route53_record" "cron1" {
    zone_id = aws_route53_zone.rpkilog_com.zone_id
    name = "cron1.rpkilog.com"
    type = "A"
    ttl = 300
    records = [
        aws_instance.cron1.public_ip
    ]
}

resource "aws_route53_record" "es_prod" {
    zone_id = aws_route53_zone.rpkilog_com.zone_id
    name = "es-prod.rpkilog.com"
    type = "CNAME"
    ttl = 300
    records = [ aws_elasticsearch_domain.prod.endpoint ]
}

resource "aws_route53_record" "rpkilog_com" {
    zone_id = aws_route53_zone.rpkilog_com.zone_id
    name = "rpkilog.com"
    type = "A"
    alias {
        name = aws_cloudfront_distribution.rpkilog_com.domain_name
        zone_id = aws_cloudfront_distribution.rpkilog_com.hosted_zone_id
        evaluate_target_health = false
    }
}

resource "aws_route53_record" "validate_acm_for_api_rpkilog_com" {
    # Validates the ACM certificate requested for api.rpkilog.com
    # See docs on DNS Validation with Route 53
    # https://registry.terraform.io/providers/hashicorp/aws/4.49.0/docs/resources/acm_certificate_validation
    for_each = {
        for dvo in aws_acm_certificate.api_rpkilog_com.domain_validation_options : dvo.domain_name => {
            name   = dvo.resource_record_name
            record = dvo.resource_record_value
            type   = dvo.resource_record_type
        }
    }
    allow_overwrite = true
    name = each.value.name
    records = [ each.value.record ]
    ttl = 300
    type = each.value.type
    zone_id = aws_route53_zone.rpkilog_com.zone_id
}

resource "aws_route53_record" "api_rpkilog_com" {
    zone_id = aws_route53_zone.rpkilog_com.zone_id
    name = "api.rpkilog.com"
    type = "A"
    alias {
        evaluate_target_health = false
        # If changing APIGW from REGIONAL to EDGE, the below should change from regional_ to cloudfront_.
        name = aws_api_gateway_domain_name.api_rpkilog_com.regional_domain_name
        zone_id = aws_api_gateway_domain_name.api_rpkilog_com.regional_zone_id
    }
}

##############################
# Cloudfront

resource "aws_cloudfront_distribution" "rpkilog_com" {
    aliases = ["rpkilog.com"]
    enabled = true
    default_cache_behavior {
        allowed_methods = ["GET", "HEAD", "OPTIONS"]
        cached_methods = ["GET", "HEAD"]
        default_ttl = 300
        forwarded_values {
            query_string = false
            cookies {
                forward = "none"
            }
        }
        max_ttl = 300
        response_headers_policy_id = aws_cloudfront_response_headers_policy.policy1.id
        target_origin_id = "s3.us-east-1"
        viewer_protocol_policy = "redirect-to-https"
    }
    default_root_object = "index.html"
    is_ipv6_enabled = true
    origin {
        domain_name = aws_s3_bucket.rpkilog_www.bucket_regional_domain_name
        origin_id = "s3.us-east-1"
    }
    restrictions {
        geo_restriction {
            restriction_type = "none"
        }
    }
    retain_on_delete = true
    viewer_certificate {
        acm_certificate_arn = data.aws_acm_certificate.rpkilog_com.arn
        ssl_support_method = "sni-only"
    }
}

resource "aws_cloudfront_response_headers_policy" "policy1" {
    name = "policy1"
    comment = "Only allow content from same-origin, rpkilog.com, *.rpkilog.com"
    security_headers_config {
        content_security_policy {
            # see also https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP
            content_security_policy = "default-src 'self' rpkilog.com *.rpkilog.com"
            override = false
        }
    }
}

# API Gateway requires this bit of account-wide config for logging
resource "aws_api_gateway_account" "apigw_account" {
    cloudwatch_role_arn = aws_iam_role.apigw_logging_accountwide_role.arn
}

##############################
# APIGW gateway itself, domain name, stage ("/unstable" only, for now), and similar
# The resource-paths (/history) and integrations are a bit further down

resource "aws_api_gateway_domain_name" "api_rpkilog_com" {
    domain_name = aws_acm_certificate.api_rpkilog_com.domain_name
    regional_certificate_arn = aws_acm_certificate_validation.api_rpkilog_com.certificate_arn
    endpoint_configuration {
        # Using REGIONAL instead of EDGE for simplicity
        types = [ "REGIONAL" ]
    }
}

resource "aws_api_gateway_rest_api" "public_api" {
    name = "public_api"
    description = "RPKILog Public API"
    endpoint_configuration {
        # Using REGIONAL instead of EDGE for simplicity
        # https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-api-endpoint-types.html
        types = [ "REGIONAL" ]
    }
}

resource "aws_api_gateway_method_settings" "unstable" {
    rest_api_id = aws_api_gateway_rest_api.public_api.id
    stage_name = "unstable"
    method_path = "*/*"
    settings {
        logging_level = "INFO"
        metrics_enabled = true
    }
    #TODO: throttling_rate_limit (requests/sec) & throttling_burst_limit can be set here
    # https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_method_settings
    # https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-create-usage-plans-with-console.html#api-gateway-usage-plan-create
    depends_on = [
        aws_api_gateway_deployment.public_api,
        aws_api_gateway_stage.unstable
    ]
}

# In the AWS WWW Console, navigate to APIGW -> Custom domain names -> api.rpkilog.com -> API mappings
# to understand how this applies.  Effectively, it maps api.rpkilog.com/unstable to aws_api_gateway_stage.unstable.
resource "aws_api_gateway_base_path_mapping" "public_api" {
    api_id = aws_api_gateway_rest_api.public_api.id
    base_path = "unstable"
    domain_name = aws_api_gateway_domain_name.api_rpkilog_com.domain_name
    stage_name = aws_api_gateway_stage.unstable.stage_name
}

# APIGW resource-paths/methods/integrations are defined below

resource "aws_api_gateway_resource" "unstable_history" {
    # resource for querying the VRP history records e.g. api.rpkilog.com/unstable/history
    #FIXME: how does it get connected to the stage?
    rest_api_id = aws_api_gateway_rest_api.public_api.id
    parent_id = aws_api_gateway_rest_api.public_api.root_resource_id
    path_part = "history"
}

resource "aws_api_gateway_method" "unstable_history_GET" {
    rest_api_id = aws_api_gateway_resource.unstable_history.rest_api_id
    resource_id = aws_api_gateway_resource.unstable_history.id
    http_method = "GET"
    authorization = "NONE"
}

resource "aws_api_gateway_integration" "hapi" {
    rest_api_id = aws_api_gateway_resource.unstable_history.rest_api_id
    resource_id = aws_api_gateway_resource.unstable_history.id
    http_method = "GET"
    # Terraform documentation says use POST when invoking a lambda.  Only supported method.
    integration_http_method = "POST"
    type = "AWS_PROXY"
    uri = aws_lambda_function.hapi.invoke_arn
}

# APIGW deployment
resource "aws_api_gateway_deployment" "public_api" {
    rest_api_id = aws_api_gateway_rest_api.public_api.id
    lifecycle {
        create_before_destroy = true
    }
    triggers = {
        redeployment = sha1(jsonencode([
            aws_api_gateway_resource.unstable_history,
            aws_api_gateway_method.unstable_history_GET,
            aws_api_gateway_integration.hapi,
        ]))
    }
}

# APIGW stage

resource "aws_api_gateway_stage" "unstable" {
    deployment_id = aws_api_gateway_deployment.public_api.id
    rest_api_id = aws_api_gateway_rest_api.public_api.id
    stage_name = "unstable"
}

# APIGW end
##############################

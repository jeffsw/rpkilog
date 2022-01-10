terraform {
    required_providers {
        aws = {
            source = "hashicorp/aws"
        }
    }
}

provider "aws" {
    region = "us-east-1"
    default_tags {
        tags = {
            tf_managed = "main"
        }
    }
}

provider "aws" {
    region = "eu-central-1"
    alias = "eu-central-1"
    default_tags {
        tags = {
            tf_managed = "main"
        }
    }
}

##############################
# Caller
data "aws_caller_identity" "current" {}

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
data "aws_acm_certificate" "es_prod" {
    domain = "es-prod.rpkilog.com"
    statuses = [ "ISSUED" ]
}

##############################
# IAM roles
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
        }
    ]
}
POLICY
    }
    depends_on = [
        aws_cognito_identity_pool.es
    ]
}
resource "aws_iam_role" "es_limited" {
    name = "es_limited"
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
        name = "es_limited"
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
                "arn:aws:s3:::rpkilog-snapshot-summary",
                "arn:aws:s3:::rpkilog-snapshot-summary/*"
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

resource "aws_iam_user" "es_limited" {
    name = "es_limited"
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

resource "aws_iam_group_policy" "es_limited" {
    name = "es_limited"
    group = aws_iam_group.es_limited.name
    policy = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "sts:AssumeRole",
            "Resource": "arn:aws:iam:::role/es_limited"
        }
    ]
}
POLICY
}
resource "aws_iam_group" "es_limited" {
    name = "es_limited"
}
resource "aws_iam_group_membership" "es_limited" {
    name = "es_limited"
    group = aws_iam_group.es_limited.name
    users = [ aws_iam_user.es_limited.name ]
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
        allow_admin_create_user_only = true
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
}

resource "aws_cognito_user_pool_client" "es" {
    name = "es"
    user_pool_id = aws_cognito_user_pool.es.id
    # access_token_validity = 86400
    # id_token_validity = 86400
    # refresh_token_validity = 30
    allowed_oauth_flows = [ "code" ]
    allowed_oauth_scopes = [
        "email",
        "openid",
        "phone",
        "profile",
    ]
    prevent_user_existence_errors = "LEGACY"
    supported_identity_providers = [ "COGNITO" ]
}
resource "aws_cognito_identity_pool" "es" {
    identity_pool_name = "es"
    allow_unauthenticated_identities = false
    allow_classic_flow = false
    cognito_identity_providers {
        client_id = aws_cognito_user_pool_client.es.id
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
        authenticated = aws_iam_role.es_master.arn
        unauthenticated = aws_iam_role.es_limited.arn
    }
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
# Get subnets of default VPC
data "aws_subnet_ids" "default" {
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
resource "aws_security_group" "allow_nfs" {
    name = "allow_nfs"
    description = "Allow NFS traffic.  This is for EFS Mount Targets."
    vpc_id = aws_default_vpc.default.id
    egress {
        from_port = 0
        to_port = 0
        protocol = "-1"
        cidr_blocks = ["0.0.0.0/0"]
        ipv6_cidr_blocks = ["::/0"]
    }
    ingress {
        description = "NFS"
        cidr_blocks = [ "0.0.0.0/0" ]
        ipv6_cidr_blocks = [ "::/0" ]
        from_port = 2049
        protocol = "tcp"
        to_port = 2049
        self = true
    }
    ingress {
        description = "NFS"
        cidr_blocks = [ "0.0.0.0/0" ]
        ipv6_cidr_blocks = [ "::/0" ]
        from_port = 2049
        protocol = "udp"
        to_port = 2049
        self = true
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
# EFS filesystems, access points, mount targets
#Terraform produces spurious "changes made outside of Terraform" whenever the amount of data stored in
#an EFS filesystem changes between terraform invocations.  Ignore these spurious notices.
#See also: https://github.com/hashicorp/terraform/issues/28803
resource "aws_efs_file_system" "rpki_archive" {
    creation_token = "rpki_archive"
}

resource "aws_efs_access_point" "rpki_archive" {
    file_system_id = aws_efs_file_system.rpki_archive.id
    posix_user {
        uid = 0
        gid = 0
    }
    root_directory {
        path = "/"
        creation_info {
            owner_gid = 0
            owner_uid = 0
            permissions = 777
        }
    }
}

resource "aws_efs_mount_target" "rpki_archive" {
    for_each = data.aws_subnet_ids.default.ids
    file_system_id = aws_efs_file_system.rpki_archive.id
    subnet_id = each.value
    security_groups = [ aws_security_group.allow_nfs.id ]
}

##############################
# s3 buckets
resource "aws_s3_bucket" "rpkilog_artifact" {
    bucket = "rpkilog-artifact"
    acl = "private"
}

resource "aws_s3_bucket" "rpkilog_snapshot" {
    bucket = "rpkilog-snapshot"
    acl = "private"
}

resource "aws_s3_bucket" "rpkilog_snapshot_summary" {
    bucket = "rpkilog-snapshot-summary"
    acl = "private"
}

resource "aws_s3_bucket" "rpkilog_diff" {
    bucket = "rpkilog-diff"
    acl = "public-read"
}

##############################
# lambda functions & permissions

#Temporarily moved into cron1 EC2 VM
# resource "aws_lambda_function" "archive_site_crawler" {
#     # Uncomment to deploy to AWS near the archive josephine.sobornost.net
#     # I found running in us-east-1 fast enough, and it's probably cheaper than downloading in eu than
#     # uploading to a remote S3 bucket
#     #provider = aws.eu-central-1
#     function_name = "archive_site_crawler"
#     filename = "misc/terraform_lambda_placeholder_python.zip"
#     role = aws_iam_role.lambda_archive_site_crawler.arn
#     runtime = "python3.9"
#     handler = "rpkilog.ArchiveSiteCrawler.aws_lambda_entry_point"
#     memory_size = 256
#     timeout = 240
#     environment {
#         variables = {
#             s3_snapshot_bucket_name = aws_s3_bucket.rpkilog_snapshot.id
#             s3_snapshot_summary_bucket_name = aws_s3_bucket.rpkilog_snapshot_summary.id
#             site_root = "http://josephine.sobornost.net/josephine.sobornost.net/rpkidata/"
#             job_max_downloads = 2
#         }
#     }
#     #TODO: add file_system_config
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
    runtime = "python3.9"
    handler = "rpkilog.vrp_diff.aws_lambda_entry_point"
    memory_size = 1769
    timeout = 300
    environment {
        variables = {
            snapshot_summary_bucket = aws_s3_bucket.rpkilog_snapshot_summary.id
            diff_bucket = aws_s3_bucket.rpkilog_diff.id
        }
    }
    # file_system_config {
    #     arn = aws_efs_access_point.rpki_archive.arn
    #     local_mount_path = "/mnt/rpki_archive"
    # }
    # vpc_config {
    #     subnet_ids = [ for x in data.aws_subnet_ids.default.ids : x ]
    #     security_group_ids = [ aws_default_security_group.default.id ]
    # }
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
    runtime = "python3.9"
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
    function_name = aws_lambda_function.diff_import.id
    principal = "s3.amazonaws.com"
    source_arn = aws_s3_bucket.rpkilog_diff.arn
}
resource "aws_lambda_function_event_invoke_config" "diff_import" {
    function_name = aws_lambda_function.diff_import.function_name
    maximum_retry_attempts = 0
}

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

# DISABLED while developing & troubleshooting the pipeline.  Don't want it automatically importing yet.
# resource "aws_s3_bucket_notification" "vrp_diff_import" {
#     bucket = aws_s3_bucket.rpkilog_diff.id
#     lambda_function {
#         lambda_function_arn = aws_lambda_function.diff_import.arn
#         events = [ "s3:ObjectCreated:*" ]
#     }
#     depends_on = [
#         aws_lambda_permission.diff_import
#     ]
# }

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
    elasticsearch_version = "7.10"
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
        volume_size = 10
        volume_type = "gp2" # gp3 not supported by current version of aws_elasticsearch_domain
    }
    encrypt_at_rest {
        enabled = true
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

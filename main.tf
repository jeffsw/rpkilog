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
# SSH key-pairs

resource "aws_key_pair" "jeffsw" {
    key_name = "jeffsw-boomer"
    tags = {
        tf_managed = "main"
        user = "jeffsw"
    }
    public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC4k8nVaS9Ns+8jZ1C97eUcOvkFw6NOXS8e4xxG6XEH1l9PDluOCxAqgCvdKxX9ZhFvwW1SCSWuN95WrM7u/9p0flOX7DZFYld053ClWxMZZ4ZtKj8XWnmDU4LLXSmUWaKddW9pHZHvxfEFu+wCcnUiJM4NgS4owfaIGC3IOIXVrxsoNuoKyTQS9pRa5+3sMC3rHK8oWPkleJGO+cs8AxuetRtHS/ZHwshsyI27ROC/nIxZ7ZeKXf3g/jxEpbxI9LNFnocuUmeoNpndBFYND1ujwiHZvoWxx4ByiTRDNJDHJWdnJpz8rOmnoHeHFqV8F/I5CRG9Dh7aq5vd9LWdrkqb jeffsw6@gmail.com boomer 2013-05-28"
}

##############################
# IAM roles

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

##############################
# VPCs

resource "aws_default_vpc" "default" {
}

##############################
# EFS filesystems

resource "aws_efs_file_system" "rpki_archive" {
    creation_token = "rpki_archive"

}
#TODO: EFS mount targets in each subnet

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

resource "aws_lambda_function" "archive_site_crawler" {
    # Uncomment to deploy to AWS near the archive josephine.sobornost.net
    # I found running in us-east-1 fast enough, and it's probably cheaper than downloading in eu than
    # uploading to a remote S3 bucket
    #provider = aws.eu-central-1
    function_name = "archive_site_crawler"
    filename = "misc/terraform_lambda_placeholder_python.zip"
    role = aws_iam_role.lambda_archive_site_crawler.arn
    runtime = "python3.9"
    handler = "rpkilog.ArchiveSiteCrawler.aws_lambda_entry_point"
    memory_size = 256
    environment {
        variables = {
            s3_snapshot_bucket_name = aws_s3_bucket.rpkilog_snapshot.id
            s3_snapshot_summary_bucket_name = aws_s3_bucket.rpkilog_snapshot_summary.id
            site_root = "http://josephine.sobornost.net/josephine.sobornost.net/rpkidata/"
            job_max_downloads = 2
        }
    }
    #TODO: add file_system_config
    lifecycle {
        # Never update the lambda deployment package.  We use another tool for that, not Terraform.
        ignore_changes = [ filename ]
    }
}

resource "aws_lambda_function" "snapshot_ingest" {
    function_name = "snapshot_ingest"
    filename = "misc/terraform_lambda_placeholder_python.zip"
    role = aws_iam_role.lambda_snapshot_ingest.arn
    runtime = "python3.9"
    handler = "rpkilog.IngestTar.aws_lambda_entry_point"
    memory_size = 1024
    environment {
        variables = {
            snapshot_bucket = aws_s3_bucket.rpkilog_snapshot.id
            snapshot_summary_bucket = aws_s3_bucket.rpkilog_snapshot_summary.id
        }
    }
    #TODO: add file_system_config.
    # See https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_function
    # under heading Lambda File Systems
    lifecycle {
        # Never update the lambda deployment package.  We use another tool for that, not Terraform.
        ignore_changes = [ filename ]
    }
}
resource "aws_lambda_permission" "snapshot_ingest" {
    statement_id = "AllowExecutionFromS3Bucket"
    action = "lambda:InvokeFunction"
    function_name = aws_lambda_function.snapshot_ingest.id
    principal = "s3.amazonaws.com"
    source_arn = aws_s3_bucket.rpkilog_snapshot.arn
}

##############################
# s3 bucket notifications

resource "aws_s3_bucket_notification" "snapshot_ingest" {
    bucket = aws_s3_bucket.rpkilog_snapshot.id
    lambda_function {
        lambda_function_arn = aws_lambda_function.snapshot_ingest.arn
        events = [ "s3:ObjectCreated:*" ]
        #filter_prefix = "/incoming"
    }
    depends_on = [
        aws_lambda_permission.snapshot_ingest
    ]
}

##############################
# EC2 AMIs, Security Groups, and Instances

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

resource "aws_instance" "util1" {
    instance_type = "t3.nano"
    ami = data.aws_ami.ubuntu_x86.id
    key_name = "jeffsw-boomer"
    user_data = file("vm_provisioner/util.sh")
    vpc_security_group_ids = [
        aws_security_group.util_vm.id
    ]
}

resource "aws_route53_zone" "rpkilog_com" {
    name = "rpkilog.com"
}

resource "aws_route53_record" "util1" {
    zone_id = aws_route53_zone.rpkilog_com.zone_id
    name = "util1.rpkilog.com"
    type = "A"
    ttl = 300
    records = [
        aws_instance.util1.public_ip
    ]
}

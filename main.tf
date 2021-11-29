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

##############################
# IAM roles

resource "aws_iam_role" "lambda_snapshot_ingest" {
    name = "lambda_snapshot_ingest"
    assume_role_policy = file("aws_iam/lambda_snapshot_ingest-assumerolepolicy.json")
    inline_policy {
        name = "lambda_snapshot_ingest"
        policy = file("aws_iam/lambda_snapshot_ingest-policy.json")
    }
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
        filter_prefix = "/incoming"
    }
    depends_on = [
        aws_lambda_permission.snapshot_ingest
    ]
}

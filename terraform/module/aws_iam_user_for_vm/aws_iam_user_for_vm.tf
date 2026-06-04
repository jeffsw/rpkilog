terraform {
  required_version = ">= 1.15"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    shell = {
      source  = "scottwinkler/shell"
      version = "~> 1.7"
    }
  }
}

variable "name" {
  description = "name of the aws_iam_user created and managed by the module"
  type        = string
  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,52}$", var.name))
    error_message = "name must be 1-52 characters and may only contain alphanumeric characters or: + = , . @ _ -"
  }
}

variable "sts_token_duration" {
  description = "duration (seconds) of the temporary STS token returned by the module for your user-data"
  type        = number
  default     = 900
  validation {
    condition     = floor(var.sts_token_duration) == var.sts_token_duration && var.sts_token_duration >= 900 && var.sts_token_duration <= 43200
    error_message = "sts_token_duration must be an integer between 900 and 43200 (inclusive)"
  }
}

variable "triggers" {
  description = "Map of values that, when changed, cause the STS token to be regenerated. Pass the ID of the associated VM to tie the token lifecycle to the VM."
  type        = map(string)
  default     = {}
}

data "aws_caller_identity" "mod_scope" {}

#####
# role for passing temporary credentials through user-data

resource "aws_iam_role" "key_manager" {
  name = "${var.name}_key_manager"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.mod_scope.account_id}:root"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "key_manager" {
  name = "${var.name}_key_manager"
  role = aws_iam_role.key_manager.id
  policy = jsonencode({
    Version : "2012-10-17"
    Statement : [
      {
        Sid : "ManageAccessKeys",
        Effect : "Allow",
        Action : [
          "iam:CreateAccessKey",
          "iam:DeleteAccessKey",
          "iam:ListAccessKeys",
          "iam:GetAccessKeyLastUsed"
        ],
        Resource : "arn:aws:iam::${data.aws_caller_identity.mod_scope.account_id}:user/${var.name}"
      },
      {
        Sid : "GetUserInfo",
        Effect : "Allow",
        Action : [
          "iam:GetUser"
        ],
        Resource : "arn:aws:iam::${data.aws_caller_identity.mod_scope.account_id}:user/${var.name}"
      }
    ]
  })
}

#####
# STS token stored in state for passing into user-data; only regenerated when triggers change

resource "shell_script" "key_manager_sts_token" {
  lifecycle_commands {
    create = <<-EOT
      set -o pipefail
      SESSION_SUFFIX=$(openssl rand -hex 8 | head -c 15)
      # IAM roles take a few seconds to propagate after creation. Sleep before the first
      # attempt and retry up to 10 times.
      for i in $(seq 1 10); do
        sleep 10
        if output=$(aws sts assume-role \
            --role-arn ${aws_iam_role.key_manager.arn} \
            --role-session-name ${substr(var.name, 0, 48)}_$SESSION_SUFFIX \
            --duration-seconds ${var.sts_token_duration} \
            | jq '.Credentials + .AssumedRoleUser'); then
          printf '%s\n' "$output"
          exit 0
        fi
      done
      exit 1
    EOT
    delete = ":"
  }

  triggers   = var.triggers
  depends_on = [aws_iam_role_policy.key_manager]
}

output "key_manager" {
  value = {
    AccessKeyId     = shell_script.key_manager_sts_token.output["AccessKeyId"]
    SecretAccessKey = shell_script.key_manager_sts_token.output["SecretAccessKey"]
    SessionToken    = shell_script.key_manager_sts_token.output["SessionToken"]
    Expiration      = shell_script.key_manager_sts_token.output["Expiration"]
    AssumedRoleId   = shell_script.key_manager_sts_token.output["AssumedRoleId"]
    Arn             = shell_script.key_manager_sts_token.output["Arn"]
  }
  type = object({
    AccessKeyId     = string
    SecretAccessKey = string
    SessionToken    = string
    Expiration      = string
    AssumedRoleId   = string
    Arn             = string
  })
  description = "flattened map of .Credentials and .AssumedRoleUser from aws sts assume-role; includes AccessKeyId, SecretAccessKey, SessionToken, Expiration, AssumedRoleId, and Arn"
}

#####
# persistent user whose API key will be rotated by the temporary role upon VM start-up

resource "aws_iam_user" "user" {
  name = var.name
  # User's IAM key is managed outside Terraform by the VM cloud-init process.  Even so, allow destruction.
  force_destroy = true
}

output "user" {
  value       = aws_iam_user.user
  description = "aws_iam_user resource managed by this module"
}

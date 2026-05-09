# At VM creation time we pass a temporary 20-minute STS token to the VM via user-data.
# That token uses the rpkiclient_key_manager_{dev} to rotate API keys on the *other* user managed in
# this file, vm_rpkiclient_key_manager_{dev}.
# The result is, although rpkiclient_key_manager's token is stored in the Terraform state, it's only
# valid for 20 minutes.
resource "aws_iam_policy" "rpkiclient_key_manager" {
  name = "rpkiclient_key_manager_${terraform.workspace}"
  policy = jsonencode({
    Version: "2012-10-17"
    Statement: [
      {
        Sid: "ManageAccessKeysForRpkiclientUploaderDev",
        Effect: "Allow",
        Action: [
          "iam:CreateAccessKey",
          "iam:DeleteAccessKey",
          "iam:ListAccessKeys",
          "iam:UpdateAccessKey",
          "iam:GetAccessKeyLastUsed"
        ],
        Resource: "arn:aws:iam::${data.aws_caller_identity.main.account_id}:user/rpkiclient_uploader_dev"
      },
      {
        Sid: "GetUserInfo",
        Effect: "Allow",
        Action: [
          "iam:GetUser"
        ],
        Resource: "arn:aws:iam::${data.aws_caller_identity.main.account_id}:user/rpkiclient_uploader_dev"
      }
    ]
  })
}

resource "aws_iam_role" "vm_rpkiclient_key_manager" {
  name = "vm_rpkiclient_key_manager_${terraform.workspace}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.main.account_id}:root"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachments_exclusive" "vm_rpkiclient_key_manager" {
  role_name   = aws_iam_role.vm_rpkiclient_key_manager.name
  policy_arns = [aws_iam_policy.rpkiclient_key_manager.arn]
}

resource "aws_iam_user" "rpkiclient_uploader" {
  name = "rpkiclient_uploader_${terraform.workspace}"
}

resource "aws_iam_policy" "rpkiclient_uploader" {
  name = "rpkiclient_uploader_${terraform.workspace}"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "s3:ListBucket",
          "s3:PutObject",
          "s3:PutObjectAcl",
          "s3:PutObjectRetention",
          "s3:PutObjectTagging",
        ],
        Resource = [
          data.aws_s3_bucket.snapshot_summary.arn,
          "${data.aws_s3_bucket.snapshot_summary.arn}/*",
        ]
      }
    ]
  })
}

resource "aws_iam_user_policy_attachment" "rpkiclient_uploader" {
  user = aws_iam_user.rpkiclient_uploader.name
  policy_arn = aws_iam_policy.rpkiclient_uploader.arn
}

resource "aws_iam_access_key" "rpkiclient_uploader" {
  user = aws_iam_user.rpkiclient_uploader.name
}

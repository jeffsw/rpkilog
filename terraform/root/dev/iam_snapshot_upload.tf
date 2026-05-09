# ⚠️ This user will be created with no API keys or password.  It's necessary to MANUALLY create an API
# secret-key, then re-invoke this Terraform workspace with var.rpkiclient_uploader_iam_secret_key, to
# complete provisioning of all resources.  Prior to that, the default value will allow provisioning the
# VMs & software setup.
#
# 🚀 To fix this, we should use a local exec provisioner to create an ephemeral GPG key, then use that
# key and the Terraform IAM user api key GPG feature to get an encrypted key, and pass both the GPG key
# and encrypted API key to the rpkiclient instance.
# The main question about this approach is how to avoid replacing the key every time Terraform runs.
# Make sure neither key ends up in state or git.
# This will also require templating the cloud-init user-data so the key(s) can get to it.
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

# Requires AWS credentials with IAM write permissions and sts:AssumeRole.
# Run with: terraform test
provider "aws" {
  default_tags {
    tags = {
      tf_managed = "terraform_module_test rpkilog/terraform/module/aws_iam_user_for_vm/tests/e2e.tftest.hcl"
    }
  }
}
provider "external" {}
provider "random" {}

run "creates_iam_resources_and_sts_token" {
  command = apply
  variables {
    name = "test_rpkilog_module_aws_iam_user_for_vm"
  }

  assert {
    condition     = aws_iam_user.user.name == "test_rpkilog_module_aws_iam_user_for_vm"
    error_message = "IAM user name does not match input variable"
  }

  assert {
    condition     = aws_iam_role.key_manager.name == "test_rpkilog_module_aws_iam_user_for_vm_key_manager"
    error_message = "key manager role name should be <name>_key_manager"
  }

  assert {
    condition     = length(data.external.key_manager_sts_token.result["AccessKeyId"]) > 0
    error_message = "sts assume-role did not return an AccessKeyId"
  }

  assert {
    condition     = length(data.external.key_manager_sts_token.result["SessionToken"]) > 0
    error_message = "sts assume-role did not return a SessionToken"
  }
}
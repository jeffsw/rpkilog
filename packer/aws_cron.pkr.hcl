# This packer file can build an amd64 or arm64 AMI.
# Invoke it like below; the default is arch=amd64.
#   packer build -var arch=arm64 rpkilog.pkr.hcl

packer {
  required_plugins {
    amazon = {
      version = ">= 1.3.4"
      source  = "github.com/hashicorp/amazon"
    }
  }
}

variable "arch" {
  type = string
  default = "amd64"
  validation {
    condition = var.arch == "amd64" || var.arch == "arm64"
    error_message = "The arch variable must be amd64 or arm64."
  }
}

# This is the instance type used for building the AMI.  It does not dictate what instance type is
# usable by instances created from the AMI.
variable "builder_instance_type" {
  type = map(string)
  default = {
    "amd64" = "t3.large"
    "arm64" = "t4g.large"
  }
}

source "amazon-ebs" "rpkilog" {
  ami_name      = "rpkilog-24-${var.arch}"
  force_deregister = true
  force_delete_snapshot = true
  instance_type = var.builder_instance_type[var.arch]
  region        = "us-east-1"
  source_ami_filter {
    filters = {
      name                = "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-${var.arch}-server-*"
      architecture        = lookup({"amd64"="x86_64", "arm64"="arm64"}, var.arch, "none")
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["amazon"] # Canonical official Ubuntu AMIs
  }
  ssh_username = "ubuntu"
}

build {
  name = "rpkilog-24-${var.arch}"
  sources = [
    "source.amazon-ebs.rpkilog"
  ]
  # Wait for cloud-init.  See also: https://www.packer.io/docs/debugging#issues-installing-ubuntu-packages
  provisioner "shell" {
    inline = [ "cloud-init status --wait" ]
  }
  provisioner "shell" {
    execute_command = "echo 'packer' | sudo -S sh -c '{{ .Vars }} {{ .Path }}'"
    scripts = [
        "aws_cron.sh"
    ]
  }
}

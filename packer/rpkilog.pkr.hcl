packer {
  required_plugins {
    amazon = {
      version = ">= 1.0.4"
      source  = "github.com/hashicorp/amazon"
    }
  }
}

source "amazon-ebs" "rpkilog" {
  ami_name      = "rpkilog-22"
  force_deregister = true
  force_delete_snapshot = true
  instance_type = "t3.small"
  region        = "us-east-1"
  source_ami_filter {
    filters = {
      name                = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["amazon"] # Canonical official Ubuntu AMIs
  }
  ssh_username = "ubuntu"
}

build {
  name = "rpkilog-22"
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
        "rpkilog.sh"
    ]
  }
}

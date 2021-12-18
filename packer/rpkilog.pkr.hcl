packer {
  required_plugins {
    amazon = {
      version = ">= 1.0.4"
      source  = "github.com/hashicorp/amazon"
    }
  }
}

source "amazon-ebs" "rpkilog" {
  ami_name      = "rpkilog"
  instance_type = "t3.small"
  region        = "us-east-1"
  source_ami_filter {
    filters = {
      name                = "ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["099720109477"] # Canonical official Ubuntu AMIs
  }
  ssh_username = "ubuntu"
}

build {
  name = "rpkilog"
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

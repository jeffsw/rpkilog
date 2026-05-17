# Invoke this like:
#   packer build linode_routinator.pkr.hcl
# This requires the linode-cli to be installed AND CONFIGURED with its token.
# On MacOS: brew install linode-cli THEN RUN IT to configure it.

packer {
  required_plugins {
    linode = {
      version = ">= 1"
      source = "github.com/linode/linode"
    }
  }
}

source "linode" "rpkilog_rpkiclient" {
  image = "linode/ubuntu24.04"
  image_description = "rpkilog_rpkiclient"
  image_label = "rpkilog_rpkiclient"
  instance_tags = ["rpkilog"]
  # 2 vCPU  4 GB  80 GB  $0.05/hr-ish  see `linode-cli linodes types` or https://api.linode.com/v4/linode/types
  instance_type = "g6-standard-2"
  region = "us-southeast"
  ssh_username = "root"
}

build {
  sources = [
    "source.linode.rpkilog_rpkiclient"
  ]

  # Wait for cloud-init.  See also: https://www.packer.io/docs/debugging#issues-installing-ubuntu-packages
  provisioner "shell" {
    inline = [ "cloud-init status --wait" ]
  }
  provisioner "shell" {
    scripts = [
      "linode_routinator.sh"
    ]
    expect_disconnect = true
    environment_vars = [
      "DEBIAN_FRONTEND=noninteractive"
    ]
  }
  ##########
  # KLUDGE: packer's linode plugin doesn't resize the temporary VM's disk on its own :(
  provisioner "shell-local" {
    scripts = ["linode_disk_resizer.sh"]
    env = {
      LINODE_NODE_ID = build.ID
    }
  }
  # KLUDGE end
  ##########
}

terraform {
  required_providers {
    incus = {
      source = "lxc/incus"
      version = "1.0.2"
    }
  }
}

provider "incus" {
  remote {
    name = "router26a"
  }
}

data "incus_storage_pool" "default" {
  name = "default"
}

resource "incus_storage_volume" "rpkiclient_1_volume_1" {
  name = "rpkiclient-1-volume-1"
  pool = data.incus_storage_pool.default.name
}

# https://registry.terraform.io/providers/lxc/incus/latest/docs/resources/instance
resource "incus_instance" "rpkiclient_1" {
  name = "rpkiclient-1"
  type = "virtual-machine"
  image = "images:ubuntu/24.04/cloud"
  config = {
    # https://linuxcontainers.org/incus/docs/main/reference/instance_options/
    "boot.autostart" = true
    "boot.autostart.delay" = 60
    "limits.cpu" = "10,11"
    "limits.memory" = "8GB"
    "user.user-data" = file("rpkiclient_1.yml")
  }
  device {
    name = "volume1"
    type = "disk"
    properties = {
      path = "/data"
      source = incus_storage_volume.rpkiclient_1_volume_1.name
      pool = data.incus_storage_pool.default.name
      required = true
    }
  }
}

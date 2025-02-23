#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

linode-cli linodes shutdown ${LINODE_NODE_ID}

sleep 20

LINODE_DISK_DATA="$(linode-cli --json linodes disks-list ${LINODE_NODE_ID})"
echo json data: ${LINODE_DISK_DATA}

LINODE_DISK_ID="$(echo ${LINODE_DISK_DATA} | jq '.[] | select(.filesystem == "ext4").id')"
echo disk id: ${LINODE_DISK_ID}

linode-cli linodes disk-resize ${LINODE_NODE_ID} ${LINODE_DISK_ID} --size 8000

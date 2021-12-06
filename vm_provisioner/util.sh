#!/bin/bash
echo "rpkilog-util1" > /etc/hostname
hostname "rpkilog-util1"

apt-get update
apt-get -y install \
    python3-pip \


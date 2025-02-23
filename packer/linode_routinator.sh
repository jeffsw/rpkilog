#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

ARCH=$(uname --machine)
VENV_DIR=/opt/rpkilog/venv/

if [[ ${ARCH} != "x86_64" ]]; then
    echo "routinator packages are only available for x86_64 as of 2025-02-22 when this script created"
    echo "see https://routinator.docs.nlnetlabs.nl/en/stable/installation.html"
    exit 1
fi

##############################
# OS packages and apt
apt-get -y update
apt-get -y upgrade
apt-get -y install \
  binutils \
  curl \
  git \
  gnupg \
  ipython3 \
  nfs-common \
  plocate \
  python3-bcdoc \
  python3-boto3 \
  python3-botocore \
  python3-full \
  python3-pip \
  unzip \
  zip \

##############################
# human users
adduser --uid 2000 --disabled-password jsw
adduser jsw sudo
echo "jsw        ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/rpkilog_config
chmod 0400 /etc/sudoers.d/rpkilog_config

##############################
# ssh
mkdir -p /etc/ssh/sshd_config.d
chmod 0755 /etc/ssh/sshd_config.d
echo "AuthorizedKeysFile /etc/ssh/authorized_keys/%u" >> /etc/ssh/sshd_config.d/authorizedkeysfile.conf
mkdir /etc/ssh/authorized_keys
chmod 0755 /etc/ssh/authorized_keys
pushd /etc/ssh/authorized_keys
curl -o jsw https://github.com/jeffsw.keys
chmod 0644 /etc/ssh/authorized_keys/*
popd

##############################
# Python
mkdir -p ${VENV_DIR}
python3 -m venv ${VENV_DIR}
${VENV_DIR}/bin/pip install \
  botocore \
  boto3 \
  bcdoc \

##############################
# AWS CLI
pushd /usr/local/src
if [[ ${ARCH} = "x86_64" ]]; then
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
elif [[ ${ARCH} = "aarch64" ]]; then
    curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"
else
    echo "Expecting uname --machine output to be x86_64 or aarch64 but it is ${ARCH}"
    exit 1
fi
unzip awscliv2.zip
./aws/install
popd

##############################
# rpkilog python from github
${VENV_DIR}/bin/pip3 install "git+https://github.com/jeffsw/rpkilog.git#subdirectory=python/rpkilog"

##############################
# routinator; see https://routinator.docs.nlnetlabs.nl/en/stable/installation.html
curl -fsSL https://packages.nlnetlabs.nl/aptkey.asc | gpg --dearmor -o /usr/share/keyrings/nlnetlabs-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/nlnetlabs-archive-keyring.gpg] https://packages.nlnetlabs.nl/linux/ubuntu $(lsb_release -cs) main" > /etc/apt/sources.list.d/nlnetlabs.list
apt-get -y update
apt-get -y install routinator
systemctl stop routinator
sleep 5
{ systemctl status routinator ; systemctl_status_exit_code=$?; } || true
case ${systemctl_status_exit_code} in
  3) echo "routinator installed but not running, as intended" ;;
  *) echo "routinator should not be running or malfunctioned; review above systemctl output" ; exit 1 ;;
esac

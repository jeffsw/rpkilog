#!/bin/bash -e

ARCH=$(uname --machine)

##############################
# OS packages and apt
apt-get -y update
apt-get -y upgrade
apt-get -y install \
  binutils \
  curl \
  git \
  ipython3 \
  mlocate \
  nfs-common \
  python3-pip \
  unzip \
  zip \

##############################
# Python
pip3 install \
  botocore \
  boto3 \
  bcdoc \

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
# human users
adduser --uid 2000 --disabled-password jsw
adduser jsw admin
adduser jsw sudo
echo "jsw        ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/rpkilog_config
chmod 0400 /etc/sudoers.d/rpkilog_config

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
pip3 install "git+https://github.com/jeffsw/rpkilog.git#subdirectory=python/rpkilog"

##############################
# crawler
groupadd crawler --gid 500
adduser --uid 500 --gid 500 --disabled-password crawler
cat <<EOF > /etc/cron.d/crawler
# Uncommon on production cron runner VM.  Commented in packer provisioner so job won't run on
# VMs in the image build process or on other types of VM.
#5,15,25,35,45,55 * * * * crawler rpkilog-archive-site-crawler \
--s3-snapshot-bucket-name rpkilog-snapshot \
--s3-snapshot-summary-bucket-name rpkilog-snapshot-summary \
--site-root http://josephine.sobornost.net/josephine.sobornost.net/rpkidata/ \
--job-max-runtime 300 \
--job-max-downloads 1 \

EOF

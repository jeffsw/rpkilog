#!/bin/bash -e

##############################
# OS packages and apt
apt-get -y update
apt-get -y upgrade
apt-get -y install \
  binutils \
  curl \
  git \
  nfs-common \
  python3-pip \

##############################
# Python
pip3 install \
  botocore \

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
# AWS EFS
git clone https://github.com/aws/efs-utils /usr/local/src/aws-efs-utils
pushd /usr/local/src/aws-efs-utils
./build-deb.sh
apt-get -y install ./build/amazon-efs-utils*deb
popd
mkdir /rpki_archive
echo "fs-092450c25ba029d1b.efs.us-east-1.amazonaws.com:/ /rpki_archive nfs4 nfsvers=4,rsize=1048576,wsize=1048576,hard,timeo=60,noresvport 0 2" >> /etc/fstab

##############################
# rpkilog python from github
pip3 install "git+https://github.com/jeffsw/rpkilog.git#subdirectory=python/rpkilog"

##############################
# crawler
groupadd crawler --gid 500
adduser --uid 500 --gid 500 --disabled-password crawler
cat <<EOF > /etc/cron.d/crawler
#5,15,25,35,45,55 * * * * crawler \
rpkilog-archive-site-crawler \
--s3-snapshot-bucket-name rpkilog-snapshot \
--s3-snapshot-summary-bucket-name rpkilog-snapshot-summary \
--site-root http://josephine.sobornost.net/josephine.sobornost.net/rpkidata/ \
--job-max-runtime 500 \
--job-max-downloads 1 \

EOF

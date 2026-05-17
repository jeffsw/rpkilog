#!/bin/bash -e
#
# common script likely to be copied to /var/lib/cloud/scripts/per-once/100-rpki-client.sh
# or otherwise run once upon a new VM's first boot
#
ARCH=$(uname --machine)
INSTALL_BRANCH=main
VENV_DIR=/opt/rpkilog/venv/

##############################
# Python
mkdir -p ${VENV_DIR}
python3 -m venv ${VENV_DIR}
${VENV_DIR}/bin/pip install \
  botocore \
  boto3 \
  bcdoc \
  ipython \

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
${VENV_DIR}/bin/pip3 install "git+https://github.com/jeffsw/rpkilog.git@${INSTALL_BRANCH}#subdirectory=python/rpkilog"

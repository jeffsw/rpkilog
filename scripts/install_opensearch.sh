#!/bin/bash -e
#
# Install and start a single-node OpenSearch 2.x container using Docker.
# Expected to run as a cloud-init per-once script on the opensearch-1 VM.
#
# Requires OPENSEARCH_INITIAL_ADMIN_PASSWORD to be set in the environment before calling.
# Uses host networking; /data/opensearch on the VM is mounted into the container for persistence.
#

# JVM heap size applied as both initial (-Xms) and maximum (-Xmx) to avoid heap resizing at runtime.
# -Xms: initial heap allocated at JVM startup.
# -Xmx: maximum heap the JVM may grow to.
# Setting both equal pins the heap at a fixed size.
# Recommended: ~50% of system RAM, not exceeding 32g (JVM compressed OOP pointer limit).
# This VM has 32 GB RAM, so 16g is appropriate.
OPENSEARCH_HEAP_SIZE=16g

DATA_DIR=/data/opensearch

mkdir -p "${DATA_DIR}"
# OpenSearch runs as uid 1000 (opensearch) inside the container; match ownership on the host
chown -R 1000:1000 "${DATA_DIR}"

docker run \
  --name opensearch \
  --restart unless-stopped \
  --network host \
  --volume "${DATA_DIR}:/usr/share/opensearch/data" \
  --env "discovery.type=single-node" \
  --env "OPENSEARCH_JAVA_OPTS=-Xms${OPENSEARCH_HEAP_SIZE} -Xmx${OPENSEARCH_HEAP_SIZE}" \
  --env "OPENSEARCH_INITIAL_ADMIN_PASSWORD=${OPENSEARCH_INITIAL_ADMIN_PASSWORD}" \
  --detach \
  opensearchproject/opensearch:2

# Dashboards connects to OpenSearch via HTTPS (the default TLS config in the opensearch:2 image).
# OPENSEARCH_SSL_VERIFICATIONMODE=none skips cert verification for the self-signed cert.
# If Dashboards starts before OpenSearch is ready, --restart unless-stopped will retry automatically.
docker run \
  --name opensearch-dashboards \
  --restart unless-stopped \
  --network host \
  --env "OPENSEARCH_HOSTS=https://localhost:9200" \
  --env "OPENSEARCH_USERNAME=admin" \
  --env "OPENSEARCH_PASSWORD=${OPENSEARCH_INITIAL_ADMIN_PASSWORD}" \
  --env "OPENSEARCH_SSL_VERIFICATIONMODE=none" \
  --detach \
  opensearchproject/opensearch-dashboards:2
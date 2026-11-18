#!/usr/bin/env bash
# Build (and optionally push) the Horus Workbench runtime images.
#
#   HORUS_REGISTRY=docker.io/<account> runtimes/build.sh          # build only
#   HORUS_REGISTRY=docker.io/<account> runtimes/build.sh --push   # build and push
#
# The images are linux/amd64, because Workbench nodes are x86. On Apple Silicon
# the build runs under emulation and is slow.
# After pushing, an admin registers each image in Workbench: Site Administration
# -> Runtime Catalog -> Add Runtime, using the full tag printed below.
set -euo pipefail

: "${HORUS_REGISTRY:?set HORUS_REGISTRY, e.g. docker.io/<account>}"
VERSION="${HORUS_RUNTIME_VERSION:-1.0.0}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PUSH=""
[[ "${1:-}" == "--push" ]] && PUSH="--push"

for rt in node memgraph; do
  tag="${HORUS_REGISTRY}/horus-${rt}-runtime:${VERSION}"
  echo "==> ${tag}"
  docker buildx build --platform linux/amd64 ${PUSH:---load} -t "${tag}" "${HERE}/${rt}"
done
echo "done. Images: ${HORUS_REGISTRY}/horus-{node,memgraph}-runtime:${VERSION}"

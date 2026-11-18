# Horus Node 22 runtime for Cloudera AI Workbench.
#
# Cloudera's PBJ Workbench Python runtime (which satisfies the Workbench runtime
# contract) plus Node.js 22. Used by the Horus Applications that run Node: the
# UI (Next.js), the intel resolver and the tile server.
#
# Rebuilt from the build history of the OSIRIS image
# christopheraburns/osiris-node-runtime:1.0.1, whose Dockerfile was never
# committed. Build with runtimes/build.sh.
FROM docker.repository.cloudera.com/cloudera/cdsw/ml-runtime-pbj-workbench-python3.12-standard:2026.04.1-b7

USER root

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && node --version && npm --version \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Runtime metadata: env vars AND matching labels. The edition must not reuse a
# Cloudera-reserved name ("Standard", ...).
ENV ML_RUNTIME_EDITION="Horus Node 22" \
    ML_RUNTIME_SHORT_VERSION="1.0" \
    ML_RUNTIME_MAINTENANCE_VERSION="0" \
    ML_RUNTIME_FULL_VERSION="1.0.0" \
    ML_RUNTIME_DESCRIPTION="PBJ Workbench Python 3.12 with Node.js 22 for the Horus applications"

LABEL com.cloudera.ml.runtime.edition="Horus Node 22" \
      com.cloudera.ml.runtime.short-version="1.0" \
      com.cloudera.ml.runtime.maintenance-version="0" \
      com.cloudera.ml.runtime.full-version="1.0.0" \
      com.cloudera.ml.runtime.description="PBJ Workbench Python 3.12 with Node.js 22 for the Horus applications"

# Back to the Workbench runtime user. Never leave the image as root.
USER 8536

# Horus Memgraph runtime for Cloudera AI Workbench.
#
# Cloudera's PBJ Workbench Python runtime plus an embedded Memgraph graph
# database and the Python packages for its HTTP shim
# (services/memgraph/app.py). Ported from OSIRIS memgraph/dockerfile
# (image christopheraburns/osiris-memgraph-runtime:1.0.2). Build with
# runtimes/build.sh.
FROM docker.repository.cloudera.com/cloudera/cdsw/ml-runtime-pbj-workbench-python3.11-standard:2026.04.1-b7

USER root

# Memgraph from its Ubuntu .deb, version pinned.
ARG MEMGRAPH_VERSION=3.11.0
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates libatomic1 \
 && curl -fL -o /tmp/memgraph.deb \
      "https://download.memgraph.com/memgraph/v${MEMGRAPH_VERSION}/ubuntu-24.04/memgraph_${MEMGRAPH_VERSION}-1_amd64.deb" \
 && apt-get install -y --no-install-recommends /tmp/memgraph.deb \
 && rm -f /tmp/memgraph.deb \
 && test -x /usr/lib/memgraph/memgraph \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Bolt driver and web server for the HTTP shim and the graph loader.
RUN pip install --no-cache-dir neo4j fastapi uvicorn

# Runtime metadata: env vars AND matching labels. The edition must not reuse a
# Cloudera-reserved name.
ENV ML_RUNTIME_EDITOR="PBJ Workbench" \
    ML_RUNTIME_KERNEL="Python 3.11" \
    ML_RUNTIME_EDITION="Horus Memgraph" \
    ML_RUNTIME_SHORT_VERSION="1.0" \
    ML_RUNTIME_MAINTENANCE_VERSION="0" \
    ML_RUNTIME_FULL_VERSION="1.0.0" \
    ML_RUNTIME_DESCRIPTION="PBJ Workbench Python 3.11 with embedded Memgraph ${MEMGRAPH_VERSION}" \
    ML_RUNTIME_METADATA_VERSION="2"

LABEL com.cloudera.ml.runtime.editor="PBJ Workbench" \
      com.cloudera.ml.runtime.kernel="Python 3.11" \
      com.cloudera.ml.runtime.edition="Horus Memgraph" \
      com.cloudera.ml.runtime.short-version="1.0" \
      com.cloudera.ml.runtime.maintenance-version="0" \
      com.cloudera.ml.runtime.full-version="1.0.0" \
      com.cloudera.ml.runtime.description="PBJ Workbench Python 3.11 with embedded Memgraph ${MEMGRAPH_VERSION}" \
      com.cloudera.ml.runtime.runtime-metadata-version="2"

# Back to the Workbench runtime user (uid 8536). Never leave the image as root.
USER 8536

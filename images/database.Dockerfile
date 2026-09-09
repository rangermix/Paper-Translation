# syntax=docker/dockerfile:1.7
FROM postgres:15-trixie@sha256:9b1d34adbce1dd07ee6e94b4a2cf698884b89bd44a6c9c12f5da8f3acbfe4957
ARG SOURCE_COMMIT=uncommitted
LABEL org.opencontainers.image.title="Personal library PostgreSQL 15" org.opencontainers.image.revision=$SOURCE_COMMIT
# Build-time security updates are recorded in the resulting immutable image.
# Runtime is always uid999; the root-only gosu privilege-switch branch is unused.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && rm /usr/local/bin/gosu \
    && mkdir -p /usr/local/share/library-release \
    && dpkg-query -W -f='${Package}\t${Version}\n' > /usr/local/share/library-release/system-packages.tsv
ARG SOURCE_TREE_SHA256=unrecorded
LABEL dev.bilingual-library.source-tree-sha256=$SOURCE_TREE_SHA256
USER 999:999

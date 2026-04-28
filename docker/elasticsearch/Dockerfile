# Multi-arch Elasticsearch with the analysis-icu plugin (multilingual tokenization).
#
# Why this exists:
# OpenAleph publishes a custom Elasticsearch image (ghcr.io/openaleph/elasticsearch:9)
# but only as linux/amd64. On Apple Silicon Docker Desktop, that image runs under
# Rosetta and fails to start because Elasticsearch 9.x tries to install a seccomp
# syscall filter and the kernel-translation layer doesn't expose it
# ("CONFIG_SECCOMP not compiled into kernel").
#
# This Dockerfile uses Elastic's official multi-arch image (which has a native
# arm64 build, no emulation, no seccomp issue) and installs the analysis-icu
# plugin that OpenAleph relies on for multilingual indexing.
#
# Pin the version to the major version OpenAleph expects (9.x).

FROM docker.elastic.co/elasticsearch/elasticsearch:9.0.0

# Install analysis-icu (Unicode tokenization, used by OpenAleph for multilingual)
RUN bin/elasticsearch-plugin install --batch analysis-icu

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

# OpenAleph's index mappings reference a person-name synonyms file. The official
# Elastic image doesn't ship it, so aleph-init silently fails to create indices
# (every API query then returns 500 with index_not_found_exception). Mirror what
# openaleph/openaleph-search's official ES Dockerfile does: pull OpenSanctions'
# rigour name dataset and strip the rewrite RHS to leave bare synonym groups.
ADD --chmod=644 https://raw.githubusercontent.com/opensanctions/rigour/refs/heads/main/rust/data/names/person_names.txt /tmp/person_names.txt
RUN sed 's/ => .*//' /tmp/person_names.txt > /usr/share/elasticsearch/config/person_name_synonyms.txt

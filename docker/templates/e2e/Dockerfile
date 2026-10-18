# soothe-nano ArcBox E2E guest template (docs/arcbox-backend.md §12 image prerequisites).
#
# Minimal guest image for the E2E suite (tests/integration/test_arcbox_e2e.py).
# Ships a working python3 + the POSIX tool set that BaseSandbox-derived file
# tools and the shell toolkit rely on. The daemon's default template has no
# python3; this template fills that gap.
#
# Uses the lacogito base image (same registry namespace as ../flowjet).
#
# Build and register with the local ArcBox daemon:
#   abctl sandbox template build soothe-nano-e2e \
#       --from-dockerfile docker/templates/e2e/Dockerfile
#
# Override the template in tests via ARCBOX_E2E_TEMPLATE=soothe-nano-e2e.

ARG PYTHON_BASE=registry.cn-hangzhou.aliyuncs.com/lacogito/python:3.12-bookworm

FROM ${PYTHON_BASE}

LABEL org.opencontainers.image.title="soothe-nano ArcBox E2E Guest" \
    org.opencontainers.image.description="Minimal guest for ArcBox E2E tests — python3 + POSIX coreutils + setsid + procps" \
    org.opencontainers.image.source="https://github.com/mirasoth/soothe-nano"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Aliyun mirror for apt (network-restricted environments; same pattern as
# ../flowjet Dockerfile.base). Installs the tool set the code paths use:
#   - util-linux  — setsid (background process-group reaping)
#   - procps      — /bin/kill with `kill -- -PGID` semantics
#   - coreutils   — nohup, tail, head, cat, mv, rm, mkdir, ls, …
#   - findutils   — find
#   - grep        — grep
#   - sed         — sed
#   - ca-certificates — TLS roots for any outbound HTTPS from the guest
RUN sed -i 's|http://deb.debian.org|http://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        util-linux \
        procps \
        coreutils \
        findutils \
        grep \
        sed \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /workspace
WORKDIR /workspace

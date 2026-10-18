# syntax=docker/dockerfile:1
# soothe-nano ArcBox production guest template.
#
# Formal guest image for real ArcBox sandbox sessions. Extends the E2E
# prerequisites (python3 + POSIX coreutils + setsid + procps) with a non-root
# runtime user and a workspace layout suitable for long-lived agent sessions.
#
# Uses the lacogito base image (same registry namespace as ../flowjet).
#
# Build and register with the local ArcBox daemon:
#   abctl sandbox template build soothe-nano-prod \
#       --from-dockerfile docker/templates/prod/Dockerfile
#
# Integration layers (e.g. flowjet session manager) select this template when
# creating sandboxes for production agent runs. The backend connects to an
# already-running sandbox by id — see docs/arcbox-backend.md §2.

ARG PYTHON_BASE=registry.cn-hangzhou.aliyuncs.com/lacogito/python:3.12-bookworm

FROM ${PYTHON_BASE}

LABEL org.opencontainers.image.title="soothe-nano ArcBox Production Guest" \
    org.opencontainers.image.description="Production guest for ArcBox sandbox sessions — python3 + POSIX coreutils + non-root runtime" \
    org.opencontainers.image.source="https://github.com/mirasoth/soothe-nano"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Aliyun mirror for apt (network-restricted environments; same pattern as
# ../flowjet Dockerfile.base). Tool set required by the sandbox code paths:
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

# Non-root runtime user. The ArcBox backend never injects model API keys into
# the guest (RFC §9); the user exists only for least-privilege process
# isolation inside the VM.
RUN useradd --create-home --system nano \
    && mkdir -p /workspace \
    && chown -R nano:nano /workspace

USER nano
WORKDIR /workspace

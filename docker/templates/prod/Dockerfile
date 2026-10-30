# soothe-nano ArcBox production guest template.
#
# The guest image for real ArcBox sandbox sessions and the E2E suite
# (tests/integration/test_arcbox_e2e.py). Ships python3 + POSIX coreutils +
# setsid + procps and a workspace layout suitable for long-lived agent
# sessions. ArcBox runs the guest as root by default; no USER directive is set.
#
# Uses the lacogito base image (same registry namespace as ../flowjet).
#
# CI publishes this image on release as
# registry.cn-hangzhou.aliyuncs.com/lacogito/soothe-nano-vm-prod
# (.github/workflows/docker-base.yml); pull it instead of building locally.
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
    org.opencontainers.image.description="Production guest for ArcBox sandbox sessions — python3 + POSIX coreutils" \
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

# ArcBox runs the guest as root by default; the backend never injects model API
# keys into the guest (docs/arcbox-backend.md §11), so a non-root USER directive
# is unnecessary and is not set here.
RUN mkdir -p /workspace
WORKDIR /workspace

# Reserved disk headroom for agent turns. The ArcBox rootfs formatter grows a
# template's disk capacity to fit its content, so without this pad every
# sandbox would be born nearly full (~100 MB slack). The sparse pad grows the
# template capacity to content + 3 GiB; flowjet deletes it once per freshly
# created sandbox (`sandbox.reserved_pad_path`, before the min_free_bytes
# watermark probe), converting the reserved capacity into free space. Sizing:
# the pad IS the headroom — raise it (and the template rebuild) together with
# the watermark in the consuming deployment.
RUN truncate -s 3G /pad.img

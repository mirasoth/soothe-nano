# soothe-nano ArcBox E2E guest template (RFC §12.4-2 image prerequisites).
#
# Build and register with the local ArcBox daemon:
#
#   abctl sandbox template build soothe-nano-e2e \
#       --from-dockerfile scripts/arcbox-e2e-template.Dockerfile
#
# The E2E suite (tests/integration/test_arcbox_e2e.py) selects this template
# by default (override via ARCBOX_E2E_TEMPLATE). Guest prerequisites:
#   - python3 — working interpreter; ALL BaseSandbox-derived file tools
#     (read/edit/glob/grep/ls/preflight) run `python3 -c` stdlib scripts
#   - POSIX sh + GNU coreutils (nohup/tail/head/cat/mv/…)
#   - util-linux (setsid — background process-group reaping)
#   - procps (/bin/kill with `kill -- -PGID` semantics)
# Note: the daemon's default template has no python3, and the
# flowjet-arcbox draft template's python3 is a broken wrapper (circular
# symlinks) — see RFC §11 status notes (2026-10-18).
FROM python:3.12-slim-bookworm

RUN apt-get update \
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

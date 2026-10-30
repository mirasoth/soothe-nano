"""Operation security implementation for workspace + tool execution.

RFC-LOOP-030 risk tiering: every rule carries a severity
(`critical` / `high` / `medium`). Evaluation maps severity through
`SecurityConfig.hard_deny_severities` (default `{"critical"}`, uniform for
all downstream consumers): a hit inside the hard set denies as before; a
sub-critical hit — or any hit at all when the set is explicitly empty
(sandbox posture) — returns a `risk_hint` decision carrying `rule_id` +
`severity`. Enforcement points without a judgment layer treat `risk_hint`
as allow-with-audit (the guard logs a warning when it mints one);
judgment-capable hosts (soothe) consume the hint as dynamic-routing input.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soothe_nano.protocols.operation_security import (
    OperationSecurityContext,
    OperationSecurityDecision,
    OperationSecurityProtocol,
    OperationSecurityRequest,
    RuleSeverity,
)
from soothe_nano.utils import expand_path
from soothe_nano.workspace.workspace_paths import WorkspacePaths

logger = logging.getLogger(__name__)

# Command-position anchor for single-word tool rules (su, apt, brew, ...):
# matches the first token of the command or of any sub-command in a
# compound (`cd x && su root`), so mentions inside arguments do not produce
# spurious hints.
_CMD_POSITION = r"(?:^|[;&|]\s*)"

# (pattern, rule_id, severity). First match wins — more specific patterns
# (rm_root, sudo_rm_rf, dd_block_device_write, chmod_root) must precede
# their general counterparts (rm_rf, sudo, dd, chmod -R).
_BANNED_COMMAND_PATTERNS: tuple[tuple[str, str, RuleSeverity], ...] = (
    # --- critical: irreversible system destruction ---
    # Negative lookbehind `(?<!git\s)` keeps ``git rm -r`` (a repo-index
    # operation that cannot delete arbitrary filesystem paths) out of the
    # destructive-``rm`` net while still catching standalone ``rm -rf /``,
    # ``cd x && rm -r y`` and ``bash -c "rm -rf /"``.
    (r"(?<!git\s)rm\s+-rf\s+/", "command.dangerous.rm_root", "critical"),
    (r"(?<!git\s)rm\s+-rf\b", "command.dangerous.rm_rf", "high"),
    (r"(?<!git\s)rm\s+-r\b", "command.dangerous.rm_r", "high"),
    (r"sudo\s+rm\s+-rf", "command.dangerous.sudo_rm_rf", "critical"),
    (r"mkfs(\.|$)", "command.dangerous.mkfs", "critical"),
    (r"\bdd\b[^;&|\n]*\bof=/dev/", "command.dangerous.dd_block_device_write", "critical"),
    (r"dd\s+if=", "command.dangerous.dd", "high"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "command.dangerous.fork_bomb", "critical"),
    (r"(curl|wget).*\|\s*(sh|bash)", "command.dangerous.pipe_to_shell", "critical"),
    (
        r">\s*/(etc|bin|sbin|usr|System|Library)(/|$)",
        "command.dangerous.system_path_redirect",
        "critical",
    ),
    (
        r"tee\s+/((etc|bin|sbin|usr|System|Library)(/|$))",
        "command.dangerous.system_path_tee",
        "critical",
    ),
    (r"chmod\s+-R\s+777\s+/", "command.dangerous.chmod_root", "critical"),
    (r"chown\s+-R\s+.+\s+/", "command.dangerous.chown_root", "critical"),
    # --- critical: daemon self-protection ---
    (r"\bpkill\b[^\n]*\bsoothe", "command.dangerous.pkill_soothe", "critical"),
    (r"\bkillall\b[^\n]*\bsoothe", "command.dangerous.killall_soothe", "critical"),
    (r"\bsoothed\s+(stop|restart)\b", "command.dangerous.soothed_lifecycle", "critical"),
    # Bare `kill <pid>` of the live daemon (port / pidfile resolved via hooks below).
    # Also block shell idioms that resolve the daemon PID then kill it.
    (r"\bkill\b[^\n]*\b8765\b", "command.dangerous.kill_daemon_port", "critical"),
    (r"\bkill\b[^\n]*soothed\.pid", "command.dangerous.kill_soothed_pidfile", "critical"),
    (r"\bkill\b[^\n]*\bpgrep\b[^\n]*\bsoothe", "command.dangerous.kill_pgrep_soothe", "critical"),
    # --- high: consequential but recoverable ---
    (r"sudo\s", "command.dangerous.sudo", "high"),
    (r"shred\b", "command.dangerous.shred", "high"),
    (r"chmod\s+777\b", "command.dangerous.chmod_777", "high"),
    (r"git\s+push\s+(-f|--force)\b", "command.dangerous.git_force_push", "high"),
    # --- high: restricted operations migrated from the soothe host deny
    # list (RFC-LOOP-030 §4.4). Unanchored whole-string search makes these
    # strictly more conservative than the host's every-subcommand-must-match
    # semantics. ---
    (_CMD_POSITION + r"su(\s|$)", "command.restricted.su", "high"),
    (_CMD_POSITION + r"doas(\s|$)", "command.restricted.doas", "high"),
    (r"\bchmod\s+-[a-zA-Z]*R", "command.restricted.chmod_recursive", "high"),
    (r"\bchown\s+-[a-zA-Z]*R", "command.restricted.chown_recursive", "high"),
    (r"\bchgrp\s+-[a-zA-Z]*R", "command.restricted.chgrp_recursive", "high"),
    (_CMD_POSITION + r"fdisk\b", "command.restricted.fdisk", "high"),
    (_CMD_POSITION + r"diskutil\b", "command.restricted.diskutil", "high"),
    (_CMD_POSITION + r"shutdown\b", "command.restricted.shutdown", "high"),
    (_CMD_POSITION + r"reboot\b", "command.restricted.reboot", "high"),
    (_CMD_POSITION + r"halt\b", "command.restricted.halt", "high"),
    (_CMD_POSITION + r"apt-get\b", "command.restricted.apt_get", "high"),
    (_CMD_POSITION + r"apt\b", "command.restricted.apt", "high"),
    (_CMD_POSITION + r"brew\b", "command.restricted.brew", "high"),
    (
        _CMD_POSITION + r"npm\s+(?:install|i)\s+(?:-[a-zA-Z]*g\b|--global\b)",
        "command.restricted.npm_global_install",
        "high",
    ),
)

# `kill [-signal…] <pid>…` fragments (not killall). Used to consult protected-kill hooks.
_KILL_INVOCATION_RE = re.compile(
    r"(?:^|[;&|\n])\s*kill\b(?!\s*all\b)(?P<args>[^\n;&|]*)",
    re.IGNORECASE,
)

_HARD_DENY_DEFAULT: frozenset[str] = frozenset({"critical"})
"""Posture default: only critical rules hard-deny (RFC-LOOP-030).

Applies when the security config carries no `hard_deny_severities` value at
all. An explicitly empty value means the opposite — no severity hard-denies
and every rule hit becomes an audited `risk_hint` — so `None` (unset) and
`()/[]` (opt-out) are deliberately kept distinct.
"""


def _hard_deny_severities(context: OperationSecurityContext) -> frozenset[str]:
    """Resolve the hard-deny severity set from the security config."""
    raw = getattr(context.security_config, "hard_deny_severities", None)
    if raw is None:
        return _HARD_DENY_DEFAULT
    return frozenset(str(item).strip().lower() for item in raw if str(item).strip())


def _deny_or_hint(
    hard: frozenset[str],
    *,
    rule_id: str,
    severity: RuleSeverity,
    reason: str,
) -> OperationSecurityDecision:
    """Map a rule hit through the hard-deny set: deny, or audited hint."""
    if severity in hard:
        return OperationSecurityDecision(
            verdict="deny",
            reason=reason,
            rule_id=rule_id,
            severity=severity,
        )
    logger.warning(
        "[operation_security] risk_hint rule=%s severity=%s: %s",
        rule_id,
        severity,
        reason,
    )
    return OperationSecurityDecision(
        verdict="risk_hint",
        reason=reason,
        rule_id=rule_id,
        severity=severity,
    )


def dangerous_command_rule_id(command: str) -> str | None:
    """Return the ``rule_id`` for the first banned pattern ``command`` matches, or ``None``."""
    if not command:
        return None
    for pattern, rule_id, _severity in _BANNED_COMMAND_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return rule_id
    return None


# Rule families: approving one rule in a family suppresses all rules in that
# family for the rest of the loop (e.g. approving ``rm -rf /`` also suppresses
# ``rm -rf <folder>``).
_RULE_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset(
        {
            "command.dangerous.rm_root",
            "command.dangerous.rm_rf",
            "command.dangerous.rm_r",
            "command.dangerous.sudo_rm_rf",
        }
    ),
    frozenset(
        {
            "command.dangerous.dd",
            "command.dangerous.dd_block_device_write",
        }
    ),
)


def rule_family(rule_id: str) -> frozenset[str]:
    """Return all rule ids in the same family as ``rule_id`` (inclusive)."""
    for family in _RULE_FAMILIES:
        if rule_id in family:
            return family
    return frozenset({rule_id})


def command_approved_by_allowlist(
    command: str,
    rule_id: str | None,
    allowlist: list[Any] | None,
) -> bool:
    """True when a human already approved this exact command or rule family.

    Mirrors the allowlist semantics the ``ToolApprovalPipeline`` uses at the
    pre-execution gate: an exact ``(tool=run_command, signature=command)``
    record OR a ``{"rule": <rule_id>}`` record whose family covers ``rule_id``
    means the operator consented, so the tool's own security gate must not
    re-deny the command it already escalated.
    """
    if not allowlist:
        return False
    cmd = (command or "").strip()
    approved_rules = rule_family(rule_id) if rule_id else frozenset()
    for rec in allowlist:
        if isinstance(rec, Mapping):
            if (
                str(rec.get("tool") or "") == "run_command"
                and cmd
                and str(rec.get("signature") or "") == cmd
            ):
                return True
            rule = str(rec.get("rule") or "")
            if rule and rule in approved_rules:
                return True
    return False


_SENSITIVE_SYSTEM_PATH_PATTERNS: tuple[str, ...] = (
    "/etc/**",
    "/bin/**",
    "/sbin/**",
    "/usr/**",
    "/System/**",
    "/Library/**",
    "/private/etc/**",
)

# Filesystem rule severities per operation kind: (read, write). Operator-
# configured matches (denied_path / allowed_path_miss / denied_filetype)
# stay critical; boundary and component rules are operation-kind aware
# (RFC-LOOP-030 §4.2).
_FS_RULE_SEVERITY: dict[str, tuple[RuleSeverity, RuleSeverity]] = {
    "filesystem.dangerous_component": ("medium", "high"),
    "filesystem.sensitive_system_path": ("medium", "critical"),
    "filesystem.workspace_boundary": ("high", "critical"),
    "filesystem.denied_path": ("critical", "critical"),
    "filesystem.allowed_path_miss": ("critical", "critical"),
    "filesystem.denied_filetype": ("critical", "critical"),
}


class WorkspaceToolOperationSecurity(OperationSecurityProtocol):
    """Evaluate workspace filesystem and execution command security."""

    # Bypass-immune dangerous path components — checked before security_config
    # so they fire even when no SecurityConfig is wired. Mirrors the
    # DANGEROUS_COMPONENTS set in path_security.py's PathValidator, kept in
    # sync so both layers enforce the same boundaries.
    _DANGEROUS_PATH_COMPONENTS: frozenset[str] = frozenset(
        {
            ".git",
            ".svn",
            ".hg",
            ".vscode",
            ".idea",
            ".claude",
            ".bashrc",
            ".bash_profile",
            ".zshrc",
            ".zprofile",
            ".profile",
            ".gitconfig",
            ".gitmodules",
            ".ripgreprc",
            ".mcp.json",
            ".claude.json",
        }
    )

    def _check_filesystem(
        self,
        context: OperationSecurityContext,
        target_path: str,
        operation_kind: str = "filesystem_write",
    ) -> OperationSecurityDecision:
        file_path = target_path.strip()
        if not file_path:
            return OperationSecurityDecision(verdict="allow", reason="No file path specified")

        hard = _hard_deny_severities(context)
        is_write = operation_kind == "filesystem_write"

        def _fs_decision(rule_id: str, reason: str) -> OperationSecurityDecision:
            read_sev, write_sev = _FS_RULE_SEVERITY[rule_id]
            return _deny_or_hint(
                hard,
                rule_id=rule_id,
                severity=write_sev if is_write else read_sev,
                reason=reason,
            )

        # Bypass-immune dangerous path check — runs regardless of security_config
        # so that sensitive paths (.git/, .bashrc, .vscode/, etc.) are always
        # evaluated, even when no SecurityConfig is provided.
        resolved_path = expand_path(file_path)
        for part in Path(resolved_path).parts:
            if part in self._DANGEROUS_PATH_COMPONENTS:
                return _fs_decision(
                    "filesystem.dangerous_component",
                    f"Path '{file_path}' contains dangerous component '{part}'",
                )

        security = context.security_config
        if security is None:
            return OperationSecurityDecision(verdict="allow", reason="No security config")

        workspace_root: Path | None = None
        if context.workspace and str(context.workspace).strip():
            workspace_root = expand_path(str(context.workspace).strip())

        # Relative tool paths resolve against the workspace root — the same
        # anchor the file-tool backends (NormalizedPathBackend) use — not the
        # process CWD. Without this, a bare relative path like
        # "working/notes.md" lands outside the workspace boundary and is
        # denied, even though the tool itself would have written inside the
        # workspace. Traversal inside the anchored path is still caught: the
        # boundary check below judges the resolved path, so
        # "working/../../etc/x" resolves outside and is denied as before.
        anchored_path = file_path
        if workspace_root is not None:
            expanded_raw = os.path.expandvars(file_path)
            raw_candidate = Path(expanded_raw).expanduser()
            if not raw_candidate.is_absolute():
                anchored_path = str(workspace_root / raw_candidate)

        resolved_path = expand_path(anchored_path)
        if (
            workspace_root is not None
            and not security.allow_paths_outside_workspace
            and WorkspacePaths(workspace_root).should_use_virtual_path_resolution(file_path)
        ):
            try:
                resolved_path = WorkspacePaths(
                    workspace_root,
                    virtual_mode=True,
                ).resolve_os_path(file_path)
            except (OSError, ValueError):
                resolved_path = expand_path(file_path)

        bypass_paths = tuple(getattr(security, "whitelist_paths_bypass", []) or [])
        for pattern in bypass_paths:
            expanded_pattern = self._expand_path_pattern(str(pattern))
            if self._path_matches_pattern(resolved_path, expanded_pattern):
                return OperationSecurityDecision(
                    verdict="allow",
                    reason=f"Path '{file_path}' allowed by whitelist bypass '{pattern}'",
                    rule_id="filesystem.whitelist_bypass",
                )

        for pattern in _SENSITIVE_SYSTEM_PATH_PATTERNS:
            if self._path_matches_pattern(resolved_path, pattern):
                return _fs_decision(
                    "filesystem.sensitive_system_path",
                    f"Path '{file_path}' matches sensitive system pattern '{pattern}'",
                )

        for pattern in security.denied_paths:
            expanded_pattern = self._expand_path_pattern(pattern)
            if self._path_matches_pattern(resolved_path, expanded_pattern):
                return _fs_decision(
                    "filesystem.denied_path",
                    f"Path '{file_path}' matches denied pattern '{pattern}'",
                )

        is_allowed = False
        for pattern in security.allowed_paths:
            expanded_pattern = self._expand_path_pattern(pattern)
            if self._path_matches_pattern(resolved_path, expanded_pattern):
                is_allowed = True
                break
        if not is_allowed:
            return _fs_decision(
                "filesystem.allowed_path_miss",
                f"Path '{file_path}' does not match any allowed pattern",
            )

        if workspace_root is not None:
            try:
                resolved_path.relative_to(workspace_root)
            except ValueError:
                if not security.allow_paths_outside_workspace:
                    return _fs_decision(
                        "filesystem.workspace_boundary",
                        f"Path '{file_path}' is outside workspace",
                    )
                if security.require_approval_for_outside_paths:
                    return OperationSecurityDecision(
                        verdict="need_approval",
                        reason=f"Path '{file_path}' is outside workspace and requires approval",
                        rule_id="filesystem.outside_workspace_approval",
                    )

        file_ext = resolved_path.suffix.lower()
        if file_ext in security.denied_file_types:
            return _fs_decision(
                "filesystem.denied_filetype",
                f"File type '{file_ext}' is explicitly denied",
            )
        if file_ext in security.require_approval_for_file_types:
            return OperationSecurityDecision(
                verdict="need_approval",
                reason=f"Access to '{file_ext}' files requires approval",
                rule_id="filesystem.filetype_approval",
            )
        return OperationSecurityDecision(verdict="allow", reason="Filesystem checks passed")

    def _check_command(
        self,
        context: OperationSecurityContext,
        command: str,
    ) -> OperationSecurityDecision:
        command_text = command.strip()
        if not command_text:
            return OperationSecurityDecision(verdict="allow", reason="No command provided")

        for pattern in tuple(getattr(self, "_command_whitelist_patterns", ())):
            if re.search(pattern, command_text, re.IGNORECASE):
                return OperationSecurityDecision(
                    verdict="allow",
                    reason=f"Command allowed by whitelist bypass: {pattern}",
                    rule_id="command.whitelist_bypass",
                )

        hard = _hard_deny_severities(context)
        for pattern, rule_id, severity in _BANNED_COMMAND_PATTERNS:
            if re.search(pattern, command_text, re.IGNORECASE):
                return _deny_or_hint(
                    hard,
                    rule_id=rule_id,
                    severity=severity,
                    reason=f"Command blocked by security rule: {pattern}",
                )

        protected = self._protected_kill_in_shell(command_text, hard)
        if protected is not None:
            return protected

        return OperationSecurityDecision(verdict="allow", reason="Command checks passed")

    @staticmethod
    def _pids_from_kill_args(args: str) -> list[int]:
        """Parse numeric PIDs from `kill` argument text (skip signal tokens)."""
        pids: list[int] = []
        tokens = args.split()
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token == "-s" and i + 1 < len(tokens):
                i += 2
                continue
            if token.startswith("-"):
                # Signal form: -9, -TERM, -SIGKILL — not a PID.
                i += 1
                continue
            if token.isdigit():
                pids.append(int(token))
            i += 1
        return pids

    def _protected_kill_in_shell(
        self, command: str, hard: frozenset[str]
    ) -> OperationSecurityDecision | None:
        """Deny `kill <pid>` when a protected-kill hook refuses the PID.

        Closes the gap where agents bypass `kill_process` via `run_command`
        `kill 12345` against the live daemon / self / parent.
        """
        # Lazy import avoids a cycle: execution.py imports this module.
        from soothe_nano.toolkits.shell import _protected_kill_refusal

        for match in _KILL_INVOCATION_RE.finditer(command):
            for pid in self._pids_from_kill_args(match.group("args") or ""):
                refusal = _protected_kill_refusal(pid)
                if refusal:
                    return _deny_or_hint(
                        hard,
                        rule_id="command.dangerous.kill_protected_pid",
                        severity="critical",
                        reason=refusal,
                    )
        return None

    def evaluate(
        self, request: OperationSecurityRequest, context: OperationSecurityContext
    ) -> OperationSecurityDecision:
        self._command_whitelist_patterns = tuple(
            getattr(context.security_config, "whitelist_commands_bypass", []) or []
        )
        if request.operation_kind in {"filesystem_read", "filesystem_write"}:
            if request.target_path:
                return self._check_filesystem(context, request.target_path, request.operation_kind)
            return OperationSecurityDecision(verdict="allow", reason="No filesystem path provided")
        if request.operation_kind == "shell_execute" and request.command:
            return self._check_command(context, request.command)
        return OperationSecurityDecision(
            verdict="allow", reason="No operation security rule matched"
        )

    def _expand_path_pattern(self, pattern: str) -> str:
        if pattern.startswith("~"):
            return str(Path(pattern).expanduser())
        return pattern

    def _path_matches_pattern(self, path: Path, pattern: str) -> bool:
        path_str = str(path)
        return fnmatch.fnmatch(path_str, pattern) or path_str.startswith(pattern.rstrip("*"))


def build_operation_security_request(
    tool_name: str,
    tool_args: dict[str, Any],
) -> OperationSecurityRequest:
    """Build an `OperationSecurityRequest` from a tool name + args.

    Uses `is_policy_filesystem_tool` / `extract_filesystem_path_for_policy`
    from `soothe_nano.tools.metadata` to classify the operation kind and
    extract the target path.
    """
    from soothe_nano.protocols.operation_security import OperationKind
    from soothe_nano.tools.metadata import (
        extract_filesystem_path_for_policy,
        get_tool_meta,
        is_policy_filesystem_tool,
    )

    meta = get_tool_meta(tool_name)
    operation_kind: OperationKind = "generic"
    target_path: str | None = None
    command: str | None = None

    if is_policy_filesystem_tool(tool_name):
        target_path = extract_filesystem_path_for_policy(tool_name, tool_args)
        if meta and meta.outcome_type == "file_write":
            operation_kind = "filesystem_write"
        else:
            operation_kind = "filesystem_read"
    elif meta and meta.category == "shell":
        command_value = tool_args.get("command") or tool_args.get("cmd")
        if command_value is not None:
            command = str(command_value)
            operation_kind = "shell_execute"
        elif tool_name == "run_python":
            operation_kind = "python_execute"

    return OperationSecurityRequest(
        action_type="tool_call",
        tool_name=tool_name,
        tool_args=tool_args,
        operation_kind=operation_kind,
        target_path=target_path,
        command=command,
    )

"""Operation security implementation for workspace + tool execution."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soothe_nano._rust_compat import (
    dangerous_command_rule_id_rust as dangerous_command_rule_id,
)
from soothe_nano._rust_compat import (
    rule_family_rust as rule_family,
)
from soothe_nano._rust_compat import (
    rust_command_approved_by_allowlist,
    rust_find_dangerous_path_component,
    rust_glob_match,
    rust_kill_invocation_pids,
)
from soothe_nano.protocols.operation_security import (
    OperationSecurityContext,
    OperationSecurityDecision,
    OperationSecurityProtocol,
    OperationSecurityRequest,
)
from soothe_nano.utils import expand_path
from soothe_nano.workspace.workspace_paths import (
    resolve_backend_os_path,
    should_use_virtual_path_resolution,
)

# `kill [-signal…] <pid>…` fragments (not killall). Used to consult protected-kill hooks.
_KILL_INVOCATION_RE = re.compile(
    r"(?:^|[;&|\n])\s*kill\b(?!\s*all\b)(?P<args>[^\n;&|]*)",
    re.IGNORECASE,
)


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
    # Rust fast-path: delegate the full check to the Rust implementation.
    rust_result = rust_command_approved_by_allowlist(command, rule_id, allowlist)
    if rust_result is not None:
        return rust_result
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
        self, context: OperationSecurityContext, target_path: str
    ) -> OperationSecurityDecision:
        file_path = target_path.strip()
        if not file_path:
            return OperationSecurityDecision(verdict="allow", reason="No file path specified")

        # Bypass-immune dangerous path check — runs regardless of security_config
        # so that sensitive paths (.git/, .bashrc, .vscode/, etc.) are always
        # blocked, even when no SecurityConfig is provided.
        # Rust fast-path: delegate the dangerous component lookup to Rust.
        rust_component = rust_find_dangerous_path_component(file_path)
        if rust_component is not None:
            return OperationSecurityDecision(
                verdict="deny",
                reason=f"Path '{file_path}' contains dangerous component '{rust_component}'",
                rule_id="filesystem.dangerous_component",
            )
        resolved_path = expand_path(file_path)
        for part in Path(resolved_path).parts:
            if part in self._DANGEROUS_PATH_COMPONENTS:
                return OperationSecurityDecision(
                    verdict="deny",
                    reason=f"Path '{file_path}' contains dangerous component '{part}'",
                    rule_id="filesystem.dangerous_component",
                )

        security = context.security_config
        if security is None:
            return OperationSecurityDecision(verdict="allow", reason="No security config")

        workspace_root: Path | None = None
        if context.workspace and str(context.workspace).strip():
            workspace_root = expand_path(str(context.workspace).strip())

        resolved_path = expand_path(file_path)
        if (
            workspace_root is not None
            and not security.allow_paths_outside_workspace
            and should_use_virtual_path_resolution(file_path, workspace_root)
        ):
            try:
                resolved_path = resolve_backend_os_path(
                    file_path,
                    workspace=workspace_root,
                    virtual_mode=True,
                )
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
            # Rust fast-path: delegate glob matching to Rust when available.
            rust_match = rust_glob_match(pattern, str(resolved_path))
            if rust_match is not None:
                if rust_match:
                    return OperationSecurityDecision(
                        verdict="deny",
                        reason=f"Path '{file_path}' matches sensitive system pattern '{pattern}'",
                        rule_id="filesystem.sensitive_system_path",
                    )
                continue
            if self._path_matches_pattern(resolved_path, pattern):
                return OperationSecurityDecision(
                    verdict="deny",
                    reason=f"Path '{file_path}' matches sensitive system pattern '{pattern}'",
                    rule_id="filesystem.sensitive_system_path",
                )

        for pattern in security.denied_paths:
            expanded_pattern = self._expand_path_pattern(pattern)
            # Rust fast-path: delegate glob matching to Rust when available.
            rust_match = rust_glob_match(expanded_pattern, str(resolved_path))
            if rust_match is not None:
                if rust_match:
                    return OperationSecurityDecision(
                        verdict="deny",
                        reason=f"Path '{file_path}' matches denied pattern '{pattern}'",
                        rule_id="filesystem.denied_path",
                    )
                continue
            if self._path_matches_pattern(resolved_path, expanded_pattern):
                return OperationSecurityDecision(
                    verdict="deny",
                    reason=f"Path '{file_path}' matches denied pattern '{pattern}'",
                    rule_id="filesystem.denied_path",
                )

        is_allowed = False
        for pattern in security.allowed_paths:
            expanded_pattern = self._expand_path_pattern(pattern)
            # Rust fast-path: delegate glob matching to Rust when available.
            rust_match = rust_glob_match(expanded_pattern, str(resolved_path))
            if rust_match is not None:
                if rust_match:
                    is_allowed = True
                    break
                continue
            if self._path_matches_pattern(resolved_path, expanded_pattern):
                is_allowed = True
                break
        if not is_allowed:
            return OperationSecurityDecision(
                verdict="deny",
                reason=f"Path '{file_path}' does not match any allowed pattern",
                rule_id="filesystem.allowed_path_miss",
            )

        if workspace_root is not None:
            try:
                resolved_path.relative_to(workspace_root)
            except ValueError:
                if not security.allow_paths_outside_workspace:
                    return OperationSecurityDecision(
                        verdict="deny",
                        reason=f"Path '{file_path}' is outside workspace",
                        rule_id="filesystem.workspace_boundary",
                    )
                if security.require_approval_for_outside_paths:
                    return OperationSecurityDecision(
                        verdict="need_approval",
                        reason=f"Path '{file_path}' is outside workspace and requires approval",
                        rule_id="filesystem.outside_workspace_approval",
                    )

        file_ext = resolved_path.suffix.lower()
        if file_ext in security.denied_file_types:
            return OperationSecurityDecision(
                verdict="deny",
                reason=f"File type '{file_ext}' is explicitly denied",
                rule_id="filesystem.denied_filetype",
            )
        if file_ext in security.require_approval_for_file_types:
            return OperationSecurityDecision(
                verdict="need_approval",
                reason=f"Access to '{file_ext}' files requires approval",
                rule_id="filesystem.filetype_approval",
            )
        return OperationSecurityDecision(verdict="allow", reason="Filesystem checks passed")

    def _check_command(self, command: str) -> OperationSecurityDecision:
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

        rule_id = dangerous_command_rule_id(command_text)
        if rule_id is not None:
            return OperationSecurityDecision(
                verdict="deny",
                reason=f"Command blocked by security rule: {rule_id}",
                rule_id=rule_id,
            )

        protected = self._protected_kill_in_shell(command_text)
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

    def _protected_kill_in_shell(self, command: str) -> OperationSecurityDecision | None:
        """Deny `kill <pid>` when a protected-kill hook refuses the PID.

        Closes the gap where agents bypass `kill_process` via `run_command`
        `kill 12345` against the live daemon / self / parent.
        """
        # Lazy import avoids a cycle: execution.py imports this module.
        from soothe_nano.toolkits.execution import _protected_kill_refusal

        # Rust fast-path: delegate kill invocation PID extraction to Rust.
        rust_pids = rust_kill_invocation_pids(command)
        if rust_pids is not None:
            for pid in rust_pids:
                refusal = _protected_kill_refusal(pid)
                if refusal:
                    return OperationSecurityDecision(
                        verdict="deny",
                        reason=refusal,
                        rule_id="command.dangerous.kill_protected_pid",
                    )
            return None

        for match in _KILL_INVOCATION_RE.finditer(command):
            for pid in self._pids_from_kill_args(match.group("args") or ""):
                refusal = _protected_kill_refusal(pid)
                if refusal:
                    return OperationSecurityDecision(
                        verdict="deny",
                        reason=refusal,
                        rule_id="command.dangerous.kill_protected_pid",
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
                return self._check_filesystem(context, request.target_path)
            return OperationSecurityDecision(verdict="allow", reason="No filesystem path provided")
        if request.operation_kind == "shell_execute" and request.command:
            return self._check_command(request.command)
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
    elif meta and meta.category == "execution":
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

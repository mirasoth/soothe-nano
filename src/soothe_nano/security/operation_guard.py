"""Operation security implementation for workspace + tool execution."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from soothe_sdk.protocols.operation_security import (
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

_BANNED_COMMAND_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"rm\s+-rf\s+/", "command.dangerous.rm_root"),
    (r"rm\s+-rf\b", "command.dangerous.rm_rf"),
    (r"rm\s+-r\b", "command.dangerous.rm_r"),
    (r"sudo\s+rm\s+-rf", "command.dangerous.sudo_rm_rf"),
    (r"sudo\s", "command.dangerous.sudo"),
    (r"mkfs(\.|$)", "command.dangerous.mkfs"),
    (r"dd\s+if=", "command.dangerous.dd"),
    (r"dd\s+of=/dev/", "command.dangerous.dd_block_device_write"),
    (r"shred\b", "command.dangerous.shred"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "command.dangerous.fork_bomb"),
    (r"(curl|wget).*\|\s*(sh|bash)", "command.dangerous.pipe_to_shell"),
    (r">\s*/(etc|bin|sbin|usr|System|Library)(/|$)", "command.dangerous.system_path_redirect"),
    (r"tee\s+/((etc|bin|sbin|usr|System|Library)(/|$))", "command.dangerous.system_path_tee"),
    (r"chmod\s+-R\s+777\s+/", "command.dangerous.chmod_root"),
    (r"chmod\s+777\b", "command.dangerous.chmod_777"),
    (r"chown\s+-R\s+.+\s+/", "command.dangerous.chown_root"),
    (r"git\s+push\s+(-f|--force)\b", "command.dangerous.git_force_push"),
    (r"\bpkill\b[^\n]*\bsoothe", "command.dangerous.pkill_soothe"),
    (r"\bkillall\b[^\n]*\bsoothe", "command.dangerous.killall_soothe"),
    (r"\bsoothed\s+(stop|restart)\b", "command.dangerous.soothed_lifecycle"),
    # Bare `kill <pid>` of the live daemon (port / pidfile resolved via hooks below).
    # Also block shell idioms that resolve the daemon PID then kill it.
    (r"\bkill\b[^\n]*\b8765\b", "command.dangerous.kill_daemon_port"),
    (r"\bkill\b[^\n]*soothed\.pid", "command.dangerous.kill_soothed_pidfile"),
    (r"\bkill\b[^\n]*\bpgrep\b[^\n]*\bsoothe", "command.dangerous.kill_pgrep_soothe"),
)

# `kill [-signal…] <pid>…` fragments (not killall). Used to consult protected-kill hooks.
_KILL_INVOCATION_RE = re.compile(
    r"(?:^|[;&|\n])\s*kill\b(?!\s*all\b)(?P<args>[^\n;&|]*)",
    re.IGNORECASE,
)

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
            if self._path_matches_pattern(resolved_path, pattern):
                return OperationSecurityDecision(
                    verdict="deny",
                    reason=f"Path '{file_path}' matches sensitive system pattern '{pattern}'",
                    rule_id="filesystem.sensitive_system_path",
                )

        for pattern in security.denied_paths:
            expanded_pattern = self._expand_path_pattern(pattern)
            if self._path_matches_pattern(resolved_path, expanded_pattern):
                return OperationSecurityDecision(
                    verdict="deny",
                    reason=f"Path '{file_path}' matches denied pattern '{pattern}'",
                    rule_id="filesystem.denied_path",
                )

        is_allowed = False
        for pattern in security.allowed_paths:
            expanded_pattern = self._expand_path_pattern(pattern)
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

        for pattern, rule_id in _BANNED_COMMAND_PATTERNS:
            if re.search(pattern, command_text, re.IGNORECASE):
                return OperationSecurityDecision(
                    verdict="deny",
                    reason=f"Command blocked by security rule: {pattern}",
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
    from `soothe_sdk.tools.metadata` to classify the operation kind and
    extract the target path.
    """
    from soothe_sdk.protocols.operation_security import OperationKind
    from soothe_sdk.tools.metadata import (
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

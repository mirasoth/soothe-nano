"""Vision tools follow the shared operation-security read path.

`analyze_image` / `extract_text_from_image` are registered with
`path_arg_keys` and `outcome_type="file_read"`, so the operation-security
middleware classifies them as filesystem reads and enforces the same policy
chain as `file_ops` tools — including the workspace boundary governed by
`security.allow_paths_outside_workspace`. The toolkit itself does no
boundary checking.
"""

from __future__ import annotations

from pathlib import Path

from soothe_nano.config.models import SecurityConfig
from soothe_nano.protocols.operation_security import OperationSecurityContext
from soothe_nano.security.operation_guard import (
    WorkspaceToolOperationSecurity,
    build_operation_security_request,
)
from soothe_nano.tools.metadata import is_policy_filesystem_tool


def _ctx(ws: Path, *, allow_outside: bool) -> OperationSecurityContext:
    return OperationSecurityContext(
        thread_id="t1",
        workspace=str(ws),
        security_config=SecurityConfig(allow_paths_outside_workspace=allow_outside),
    )


def test_vision_tools_classified_as_policy_filesystem_reads() -> None:
    assert is_policy_filesystem_tool("analyze_image")
    assert is_policy_filesystem_tool("extract_text_from_image")


def test_request_extracts_image_path_as_filesystem_read() -> None:
    request = build_operation_security_request(
        "analyze_image", {"image_path": "input/attachments/a.png"}
    )
    assert request.target_path == "input/attachments/a.png"
    assert request.operation_kind == "filesystem_read"


def test_outside_image_path_flagged_by_default(tmp_path: Path) -> None:
    """Default policy flags outside reads as risk_hint (approval flow)."""
    ws = tmp_path / "repo"
    ws.mkdir()
    outside = tmp_path / "media" / "secret.png"
    outside.parent.mkdir()
    outside.write_bytes(b"\x89PNG\r\n\x1a\n")

    ev = WorkspaceToolOperationSecurity()
    decision = ev.evaluate(
        build_operation_security_request("analyze_image", {"image_path": str(outside)}),
        _ctx(ws, allow_outside=False),
    )
    assert decision.verdict == "risk_hint"
    assert decision.rule_id == "filesystem.workspace_boundary"


def test_outside_image_path_needs_approval_with_flag(tmp_path: Path) -> None:
    """`allow_paths_outside_workspace=True` alone still requires approval."""
    ws = tmp_path / "repo"
    ws.mkdir()
    outside = tmp_path / "media" / "photo.png"
    outside.parent.mkdir()
    outside.write_bytes(b"\x89PNG\r\n\x1a\n")

    ev = WorkspaceToolOperationSecurity()
    decision = ev.evaluate(
        build_operation_security_request("analyze_image", {"image_path": str(outside)}),
        _ctx(ws, allow_outside=True),
    )
    assert decision.verdict == "need_approval"


def test_outside_image_path_allowed_with_flag_no_approval_gate(tmp_path: Path) -> None:
    ws = tmp_path / "repo"
    ws.mkdir()
    outside = tmp_path / "media" / "photo.png"
    outside.parent.mkdir()
    outside.write_bytes(b"\x89PNG\r\n\x1a\n")

    ctx = OperationSecurityContext(
        thread_id="t1",
        workspace=str(ws),
        security_config=SecurityConfig(
            allow_paths_outside_workspace=True,
            require_approval_for_outside_paths=False,
        ),
    )
    ev = WorkspaceToolOperationSecurity()
    decision = ev.evaluate(
        build_operation_security_request("analyze_image", {"image_path": str(outside)}),
        ctx,
    )
    assert decision.verdict == "allow"


def test_inside_image_path_allowed_by_default(tmp_path: Path) -> None:
    ws = tmp_path / "repo"
    ws.mkdir()
    ev = WorkspaceToolOperationSecurity()
    decision = ev.evaluate(
        build_operation_security_request(
            "analyze_image", {"image_path": "input/attachments/a.png"}
        ),
        _ctx(ws, allow_outside=False),
    )
    assert decision.verdict == "allow"

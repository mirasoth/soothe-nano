"""Unit tests for kill_process self/parent protection and host hooks."""

from __future__ import annotations

import os
import signal

from soothe_nano.toolkits.execution import (
    KillProcessTool,
    _kill_process_tree,
    _protected_kill_refusal,
    clear_protected_kill_hooks,
    register_protected_kill_hook,
)


def test_kill_process_refuses_self_pid() -> None:
    tool = KillProcessTool()
    result = tool._run(os.getpid())
    assert "refusing to kill" in result
    assert "current agent process" in result


def test_protected_kill_hook_is_consulted() -> None:
    clear_protected_kill_hooks()

    def refuse_4242(pid: int) -> str | None:
        if pid == 4242:
            return "Error: refusing to kill PID 4242 — host hook"
        return None

    unregister = register_protected_kill_hook(refuse_4242)
    try:
        assert _protected_kill_refusal(4242) == "Error: refusing to kill PID 4242 — host hook"
        tool = KillProcessTool()
        result = tool._run(4242)
        assert "host hook" in result
    finally:
        unregister()
        clear_protected_kill_hooks()


def test_protected_kill_hook_unregister() -> None:
    clear_protected_kill_hooks()

    def refuse_99(pid: int) -> str | None:
        return "blocked" if pid == 99 else None

    unregister = register_protected_kill_hook(refuse_99)
    assert _protected_kill_refusal(99) == "blocked"
    unregister()
    assert _protected_kill_refusal(99) is None
    clear_protected_kill_hooks()


def test_kill_process_tree_avoids_killpg_on_own_group(monkeypatch) -> None:
    kills: list[tuple[int, int]] = []

    monkeypatch.setattr("soothe_nano.toolkits.execution.os.getpgid", lambda _pid: 77)
    monkeypatch.setattr(
        "soothe_nano.toolkits.execution.os.kill",
        lambda pid, sig: kills.append((pid, sig)),
    )

    def boom(*_a, **_k):
        raise AssertionError("killpg must not run for own process group")

    monkeypatch.setattr("soothe_nano.toolkits.execution.os.killpg", boom)
    _kill_process_tree(99, sig=signal.SIGTERM)
    assert kills == [(99, signal.SIGTERM)]


def test_kill_process_tree_uses_killpg_for_foreign_group(monkeypatch) -> None:
    killpg_calls: list[tuple[int, int]] = []

    def fake_getpgid(pid: int) -> int:
        return 10 if pid == 0 else 99

    monkeypatch.setattr("soothe_nano.toolkits.execution.os.getpgid", fake_getpgid)
    monkeypatch.setattr(
        "soothe_nano.toolkits.execution.os.killpg",
        lambda pgid, sig: killpg_calls.append((pgid, sig)),
    )
    _kill_process_tree(42, sig=signal.SIGKILL)
    assert killpg_calls == [(99, signal.SIGKILL)]

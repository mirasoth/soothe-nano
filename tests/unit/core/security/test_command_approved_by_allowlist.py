"""Tests for the loop-scoped approval consult in the tool security gate."""

from __future__ import annotations

from soothe_nano.security.operation_guard import command_approved_by_allowlist


def test_exact_signature_match_allows() -> None:
    cmd = "rm -rf build/"
    allowlist = [{"tool": "run_command", "signature": cmd}]
    assert command_approved_by_allowlist(cmd, "command.dangerous.rm_rf", allowlist)


def test_rule_family_override_allows_different_command() -> None:
    # Human approved the rm family via the recorded rule override; a later,
    # different destructive-rm command in the same family must be honored.
    allowlist = [{"rule": "command.dangerous.rm_r"}]
    assert command_approved_by_allowlist("rm -rf dist/", "command.dangerous.rm_rf", allowlist)


def test_unrelated_rule_not_honored() -> None:
    allowlist = [{"rule": "command.dangerous.mkfs"}]
    assert not command_approved_by_allowlist("rm -rf build/", "command.dangerous.rm_rf", allowlist)


def test_no_allowlist_denies() -> None:
    assert not command_approved_by_allowlist("rm -rf build/", "command.dangerous.rm_rf", None)
    assert not command_approved_by_allowlist("rm -rf build/", "command.dangerous.rm_rf", [])


def test_signature_mismatch_not_honored() -> None:
    allowlist = [{"tool": "run_command", "signature": "rm -rf build/"}]
    assert not command_approved_by_allowlist(
        "rm -rf /etc/passwd", "command.dangerous.rm_root", allowlist
    )


def test_garbage_records_ignored() -> None:
    allowlist = [{"tool": "run_command"}, {"signature": "x"}, "nope", None]
    assert not command_approved_by_allowlist("rm -rf build/", "command.dangerous.rm_rf", allowlist)

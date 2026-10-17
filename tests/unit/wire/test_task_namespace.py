"""Unit tests for the unified tool_call_id wire namespace contract."""

from __future__ import annotations

from collections import deque

from soothe_nano.wire.task_namespace import (
    _TASK_SCOPE_SEP,
    _shorten_tool_call_id,
    _task_index_from_task_tool_call_id,
    is_inner_subgraph_task_tool_id,
    is_step_level_task_tool_id,
    is_unified_tool_call_id,
    normalize_main_task_delegation_id,
    normalize_step_task_tool_call_id,
    normalize_unified_tool_call_id,
    parse_unified_tool_call_id,
    prune_bound_pending_namespaces,
    register_task_spawn_for_step,
    resolve_task_parent_lookup,
    resolve_task_scope_for_namespace,
    resolve_task_scope_for_subgraph_tool,
    row_key_for_subgraph_tool,
    scoped_subgraph_tool_key,
    step_level_parent_task_call_id,
    task_scope_step_id,
    task_scope_task_idx,
    try_bind_namespace_from_tool_call_id,
)


def test_parse_canonical_step_level_id() -> None:
    parsed = parse_unified_tool_call_id("GHT_01:s:grep:0")
    assert parsed.step_id == "GHT-01"
    assert parsed.type_code == "s"
    assert parsed.task_idx is None
    assert parsed.tool_info == "grep:0"


def test_parse_task_level_id() -> None:
    parsed = parse_unified_tool_call_id("GHT_01:t2:grep:3")
    assert parsed.step_id == "GHT-01"
    assert parsed.type_code == "t"
    assert parsed.task_idx == 2
    assert parsed.tool_info == "grep:3"


def test_parse_preserves_opaque_provider_ids() -> None:
    # Kimi/OpenAI-style opaque call ids keep the raw id in tool_info.
    parsed = parse_unified_tool_call_id("GHT_01:s:tool-abc123")
    assert parsed.step_id == "GHT-01"
    assert parsed.tool_info == "tool-abc123"
    parsed = parse_unified_tool_call_id("GHT_01:s:call_9f2c")
    assert parsed.tool_info == "call_9f2c"


def test_parse_rejects_non_unified_ids() -> None:
    for raw in ("", "grep:0", "functions.grep:0", "call_9f2c", "GHT-01:s:grep:0"):
        parsed = parse_unified_tool_call_id(raw)
        assert parsed.step_id == ""
        assert parsed.type_code == ""
        assert parsed.task_idx is None
        if raw:
            assert parsed.tool_info == raw
        else:
            assert parsed.tool_info == ""


def test_parse_rejects_invalid_type_segments() -> None:
    for raw in ("GHT_01:x:grep:0", "GHT_01:t:grep:0", "GHT_01:tx:grep:0", "GHT_01:s:"):
        parsed = parse_unified_tool_call_id(raw)
        assert parsed.step_id == ""
        assert parsed.type_code == ""


def test_is_unified_tool_call_id() -> None:
    assert is_unified_tool_call_id("GHT_01:s:grep:0")
    assert is_unified_tool_call_id("GHT_01:t12:grep:3")
    # Opaque provider call-id fragments still count as unified.
    assert is_unified_tool_call_id("GHT_01:s:tool-abc123")
    assert not is_unified_tool_call_id("functions.grep:0")
    assert not is_unified_tool_call_id("GHT-01:s:grep:0")
    assert not is_unified_tool_call_id("")
    assert not is_unified_tool_call_id("GHT_01:s")


def test_normalize_unified_tool_call_id_round_trip() -> None:
    assert normalize_unified_tool_call_id("GHT_01:s:grep:0") == "GHT_01:s:grep:0"
    assert normalize_unified_tool_call_id("GHT_01:t2:grep:3") == "GHT_01:t2:grep:3"
    # Non-unified ids are returned unchanged.
    assert normalize_unified_tool_call_id("functions.grep:0") == "functions.grep:0"
    assert normalize_unified_tool_call_id("") == ""


def test_shorten_tool_call_id() -> None:
    assert _shorten_tool_call_id("GHT_01:s:grep:0") == "grep:0"
    assert _shorten_tool_call_id("functions.grep:0") == "grep:0"
    assert _shorten_tool_call_id("grep:0") == "grep:0"
    assert _shorten_tool_call_id("tool-abc123") == "tool-abc123"


def test_step_vs_inner_task_classification() -> None:
    assert is_step_level_task_tool_id("GHT_01:s:task:0")
    assert not is_step_level_task_tool_id("GHT_01:t1:task:0")
    assert not is_step_level_task_tool_id("GHT_01:s:grep:0")
    assert is_inner_subgraph_task_tool_id("GHT_01:t1:task:0")
    assert not is_inner_subgraph_task_tool_id("GHT_01:s:task:0")
    assert not is_inner_subgraph_task_tool_id("grep:0")


def test_task_index_extraction() -> None:
    assert _task_index_from_task_tool_call_id("GHT_01:s:task:3") == 3
    assert _task_index_from_task_tool_call_id("GHT_01:s:task") == 0
    # Inner subgraph task rows are excluded (dedicated ingest path).
    assert _task_index_from_task_tool_call_id("GHT_01:t2:task:5") is None
    assert _task_index_from_task_tool_call_id("GHT_01:t2:grep:0") == 2
    assert _task_index_from_task_tool_call_id("GHT_01:t1:task:0") is None
    assert _task_index_from_task_tool_call_id("task:2") == 2
    assert _task_index_from_task_tool_call_id("grep:0") is None
    assert _task_index_from_task_tool_call_id("") is None


def test_normalize_main_task_delegation_id() -> None:
    # Inner subgraph task rows pass through untouched.
    assert normalize_main_task_delegation_id("GHT-01", "GHT_01:t1:task:0") == "GHT_01:t1:task:0"
    # Canonical step-level delegation is normalized.
    assert normalize_main_task_delegation_id("GHT-01", "GHT_01:s:task:2") == "GHT_01:s:task:2"
    # Provider stamped a t-prefixed id with an opaque task fragment -> remapped to s.
    assert (
        normalize_main_task_delegation_id("GHT-01", "GHT_01:t3:task-abc", tool_name="task")
        == "GHT_01:s:task:3"
    )
    # Non-task raw ids fall through to the step-scoped task normalization,
    # which defaults unknown fragments to the step's first task slot.
    assert (
        normalize_main_task_delegation_id("GHT-01", "grep:0", tool_name="grep") == "GHT_01:s:task:0"
    )


def test_normalize_step_task_tool_call_id() -> None:
    assert normalize_step_task_tool_call_id("GHT-01", "GHT_01:s:task:0") == "GHT_01:s:task:0"
    # Another step's delegation id must not be remapped.
    assert normalize_step_task_tool_call_id("ABC-02", "GHT_01:s:task:0") == "GHT_01:s:task:0"
    assert normalize_step_task_tool_call_id("GHT-01", "task:1") == "GHT_01:s:task:1"
    # Non-task raw ids default to the step's first task slot.
    assert normalize_step_task_tool_call_id("GHT-01", "grep:0") == "GHT_01:s:task:0"
    assert normalize_step_task_tool_call_id("", "grep:0") == "grep:0"


def test_step_level_parent_task_call_id() -> None:
    assert step_level_parent_task_call_id("GHT-01") == "GHT_01:s:task:0"
    assert step_level_parent_task_call_id("GHT-01", 3) == "GHT_01:s:task:3"


def test_task_scope_helpers() -> None:
    scope = ("GHT_01:s:task:2", "research", "GHT-01")
    assert task_scope_step_id(scope) == "GHT-01"
    assert task_scope_step_id(None) == ""
    assert task_scope_task_idx(scope, "GHT-01") == 2
    assert task_scope_task_idx(None, "GHT-01") == 0
    # Non-task or task-level ids yield 0.
    assert task_scope_task_idx(("GHT_01:s:grep:0", "r", "GHT-01"), "GHT-01") == 0
    assert task_scope_task_idx(("GHT_01:t1:task:0", "r", "GHT-01"), "GHT-01") == 0
    assert task_scope_task_idx(("", "r", "GHT-01"), "GHT-01") == 0


def test_scoped_subgraph_tool_key() -> None:
    # Already-unified task-level ids pass through.
    assert scoped_subgraph_tool_key(("tools:abc",), "GHT_01:t1:grep:0") == "GHT_01:t1:grep:0"
    # No namespace -> shortened provider id.
    assert scoped_subgraph_tool_key((), "grep:0") == "grep:0"
    # With a task scope -> unified task-level id.
    scope = ("GHT_01:s:task:1", "research", "GHT-01")
    assert (
        scoped_subgraph_tool_key(("tools:abc",), "grep:0", task_scope=scope) == "GHT_01:t1:grep:0"
    )
    # Without a scope -> namespace-separator fallback key.
    assert scoped_subgraph_tool_key(("tools:x",), "grep:0") == f"tools:x{_TASK_SCOPE_SEP}grep:0"


def test_row_key_for_subgraph_tool_remaps_wrong_step() -> None:
    scope = ("GHT_01:s:task:0", "research", "GHT-01")
    # Server stamped the wrong step fragment -> remapped via the binding.
    assert (
        row_key_for_subgraph_tool(("tools:x",), "ABC_02:t0:grep:1", task_scope=scope)
        == "GHT_01:t0:grep:1"
    )
    # Matching task-level id is returned as-is.
    assert row_key_for_subgraph_tool(("tools:x",), "GHT_01:t0:grep:1") == "GHT_01:t0:grep:1"
    # Non-unified falls back to scoped keys.
    scope2 = ("GHT_01:s:task:1", "research", "GHT-01")
    assert (
        row_key_for_subgraph_tool(("tools:x",), "grep:2", task_scope=scope2) == "GHT_01:t1:grep:2"
    )


def test_resolve_task_scope_for_subgraph_tool() -> None:
    step_scope = ("GHT_01:s:task:0", "research", "GHT-01")
    # Direct parent lookup via spawns_by_task_id.
    out = resolve_task_scope_for_subgraph_tool(
        "GHT_01:t0:grep:2",
        spawns_by_step={},
        spawns_by_task_id={"GHT_01:s:task:0": step_scope},
    )
    assert out == step_scope
    # Task index 0 resolves via spawns_by_step without the id map.
    assert resolve_task_scope_for_subgraph_tool(
        "GHT_01:t0:grep:2", {"GHT-01": step_scope}, None
    ) == (step_scope)
    # Unmatched task index stays unresolved.
    assert resolve_task_scope_for_subgraph_tool(
        "GHT_01:t5:grep:2", {"GHT-01": step_scope}, None
    ) is (None)
    # Step-level ids resolve via spawns_by_step.
    assert resolve_task_scope_for_subgraph_tool(
        "GHT_01:s:grep:0", {"GHT-01": step_scope}, None
    ) == (step_scope)
    # Raw provider ids cannot resolve.
    assert resolve_task_scope_for_subgraph_tool("grep:0", {"GHT-01": step_scope}, None) is None


def test_try_bind_namespace_from_tool_call_id() -> None:
    scope = ("GHT_01:s:task:0", "research", "GHT-01")
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}
    ns = ("tools", "abc")
    assert try_bind_namespace_from_tool_call_id(bindings, {"GHT-01": scope}, ns, "GHT_01:t0:grep:0")
    assert bindings[ns] == scope
    # Re-binding to the same step is a no-op.
    assert not try_bind_namespace_from_tool_call_id(
        bindings, {"GHT-01": scope}, ns, "GHT_01:t0:other:1"
    )
    # Binding to a different step wins for non-task rows.
    other_scope = ("ABC_02:s:task:0", "research", "ABC-02")
    assert try_bind_namespace_from_tool_call_id(
        bindings, {"ABC-02": other_scope}, ns, "ABC_02:t0:grep:0"
    )
    assert bindings[ns] == other_scope
    # Inner subgraph task rows never bind.
    fresh: dict[tuple[str, ...], tuple[str, str, str]] = {}
    assert not try_bind_namespace_from_tool_call_id(
        fresh, {"GHT-01": scope}, ("tools", "x"), "GHT_01:t1:task:0"
    )
    # Unresolvable ids do not bind.
    assert not try_bind_namespace_from_tool_call_id(
        fresh, {"GHT-01": scope}, ("tools", "y"), "grep:0"
    )


def test_register_task_spawn_for_step() -> None:
    queue: deque[tuple[str, str, str]] = deque()
    spawns_by_step: dict[str, tuple[str, str, str]] = {}
    spawns_by_task_id: dict[str, tuple[str, str, str]] = {}
    bindings: dict[tuple[str, ...], tuple[str, str, str]] = {}

    step_scope = ("GHT_01:s:task:0", "research", "GHT-01")
    register_task_spawn_for_step(
        bindings,
        queue,
        spawns_by_step,
        step_scope,
        spawns_by_task_id=spawns_by_task_id,
    )
    assert queue == deque([step_scope])
    assert spawns_by_step["GHT-01"] == step_scope
    assert spawns_by_task_id["GHT_01:s:task:0"] == step_scope

    # Inner subgraph rows for the same step never overwrite the step-level scope.
    inner_scope = ("GHT_01:t1:task:0", "research", "GHT-01")
    register_task_spawn_for_step(
        bindings,
        queue,
        spawns_by_step,
        inner_scope,
        spawns_by_task_id=spawns_by_task_id,
    )
    assert spawns_by_step["GHT-01"] == step_scope
    assert queue == deque([step_scope, inner_scope])

    # A second step-level delegation with a different task id keeps the first.
    second = ("GHT_01:s:task:1", "research", "GHT-01")
    register_task_spawn_for_step(
        bindings,
        queue,
        spawns_by_step,
        second,
        spawns_by_task_id=spawns_by_task_id,
    )
    assert spawns_by_step["GHT-01"] == step_scope

    # A step-level scope replaces a previously recorded inner row.
    spawns_by_step["ABC-02"] = ("ABC_02:t0:task:0", "research", "ABC-02")
    abc_step = ("ABC_02:s:task:0", "research", "ABC-02")
    register_task_spawn_for_step(bindings, queue, spawns_by_step, abc_step)
    assert spawns_by_step["ABC-02"] == abc_step

    # Scopes without a step id are queued but not indexed.
    no_step = ("grep:0", "research", "")
    register_task_spawn_for_step(bindings, queue, spawns_by_step, no_step)
    assert queue[-1] == no_step


def test_prune_bound_pending_namespaces() -> None:
    bindings = {("tools", "a"): ("GHT_01:s:task:0", "r", "GHT-01")}
    pending = deque([("tools", "a"), ("tools", "b")])
    prune_bound_pending_namespaces(bindings, pending)
    assert pending == deque([("tools", "b")])
    # None pending deque is a no-op.
    prune_bound_pending_namespaces(bindings, None)


def test_resolve_task_scope_for_namespace_longest_prefix() -> None:
    outer = ("outer", "r", "A-01")
    inner = ("inner", "r", "B-02")
    bindings = {("tools",): outer, ("tools", "sub"): inner}
    assert resolve_task_scope_for_namespace(bindings, ("tools", "sub", "x")) == inner
    assert resolve_task_scope_for_namespace(bindings, ("tools", "other")) == outer
    assert resolve_task_scope_for_namespace(bindings, ()) is None


def test_resolve_task_parent_lookup() -> None:
    scope = ("GHT_01:s:task:0", "research", "GHT-01")
    step_cards = {"GHT-01": "step-card"}
    tool_display = {"GHT_01:s:task:0": "task-card"}
    # Task row display wins over the step card.
    parent = resolve_task_parent_lookup(
        scope, step_cards=step_cards, tool_display_by_call_id=tool_display
    )
    assert parent == "task-card"
    assert (
        resolve_task_parent_lookup(scope, step_cards=step_cards, tool_display_by_call_id={})
        == "step-card"
    )
    assert resolve_task_parent_lookup(None, step_cards=step_cards, tool_display_by_call_id={}) is (
        None
    )
    unknown_step = ("X_01:s:task:0", "research", "X-01")
    assert (
        resolve_task_parent_lookup(unknown_step, step_cards=step_cards, tool_display_by_call_id={})
        is None
    )

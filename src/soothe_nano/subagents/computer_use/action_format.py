"""Human-readable computer_use step labels for TUI activity rows."""

from __future__ import annotations

from typing import Any

from soothe_nano.subagents.computer_use._preview import preview_first

# Maps action_type → human-readable tool label
_ACTION_LABELS: dict[str, str] = {
    "screenshot": "Screenshot",
    "click": "Click",
    "double_click": "DblClick",
    "right_click": "RClick",
    "type": "Type",
    "key": "Key",
    "hotkey": "Hotkey",
    "scroll": "Scroll",
    "move": "Move",
    "drag": "Drag",
    "wait": "Wait",
    "done": "Done",
    "complete": "Done",
}


def _as_mapping(obj: Any) -> dict[str, Any] | None:
    """Coerce a pydantic model, dataclass, or dict into a plain dict."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        try:
            dumped = obj.model_dump()
        except Exception:
            dumped = None
        if isinstance(dumped, dict):
            return dumped
    return None


def _detail_from_action(action_type: str, data: dict[str, Any]) -> str:
    """Extract a short human-readable detail string for the action type."""
    if action_type in ("click", "double_click", "right_click", "move", "drag"):
        x = data.get("x")
        y = data.get("y")
        if x is not None and y is not None:
            return f"({x},{y})"
        coordinate = data.get("coordinate")
        if coordinate is not None:
            return preview_first(str(coordinate), 40)
        return preview_first(str(data.get("target") or ""), 60)
    if action_type == "type":
        text = data.get("text") or data.get("input") or ""
        return preview_first(str(text), 80)
    if action_type == "key":
        key = data.get("key") or data.get("keys") or ""
        return preview_first(str(key), 60)
    if action_type == "hotkey":
        keys = data.get("keys") or data.get("combo") or ""
        return preview_first(str(keys), 60)
    if action_type == "scroll":
        direction = data.get("direction") or data.get("dy")
        amount = data.get("amount") or data.get("clicks")
        if direction is not None:
            return f"{direction}"
        if amount is not None:
            return f"{amount}"
        return "page"
    if action_type == "screenshot":
        return preview_first(str(data.get("reason") or "capture"), 80)
    if action_type in ("wait", "done", "complete"):
        return preview_first(str(data.get("reason") or data.get("text") or ""), 80)
    return preview_first(str(data.get("target") or data.get("detail") or ""), 80)


def summarize_computer_step_action(action: Any) -> tuple[str, str]:
    """Return ``(tool_name, args_preview)`` for one computer-use model action.

    Expects ``action`` to be a mapping with at least an ``action_type`` key,
    or a pydantic model with a ``model_dump()`` method.

    Falls back to a truncated ``str(action)`` when the structure is unknown.
    """
    if action is None:
        return "Step", ""

    data = _as_mapping(action)
    if data is None:
        return "Step", preview_first(str(action), 80)

    action_type = str(data.get("action_type") or data.get("type") or "").lower().strip()
    if not action_type:
        # Try common key names as action type
        for key, label in _ACTION_LABELS.items():
            if key in data and data[key] is not None:
                return label, _detail_from_action(key, data)
        return "Step", preview_first(str(action), 80)

    label = _ACTION_LABELS.get(action_type, action_type.capitalize())
    detail = _detail_from_action(action_type, data)
    return label, detail


__all__ = ["summarize_computer_step_action"]

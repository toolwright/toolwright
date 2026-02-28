"""Description optimization and tool filtering for context efficiency.

Reduces tool descriptions to ~80-120 tokens for compact mode, and
filters tools by name glob and risk tier ceiling.
"""

from __future__ import annotations

from fnmatch import fnmatch
from typing import Any

_RISK_LEVELS = ("low", "medium", "high", "critical")


def optimize_description(action: dict[str, Any], *, compact: bool = True) -> str:
    """Optimize a tool description for context efficiency.

    Compact mode produces a terse description with method, path, purpose,
    parameters, and risk annotation. Verbose mode returns the full original.
    """
    original = action.get("description", "")
    method = action.get("method") or "GET"
    path = action.get("path") or "/"
    risk = action.get("risk_tier") or "low"

    if not compact:
        desc = original or f"{method} {path}"
        if risk in ("high", "critical"):
            desc += f" [Risk: {risk}]"
        return desc

    # Compact: method path — truncated purpose — params — risk
    parts = [f"{method} {path}"]

    # Truncate purpose to first sentence or 60 chars
    if original:
        first_sentence = original.split(".")[0].strip()
        if len(first_sentence) > 60:
            first_sentence = first_sentence[:57] + "..."
        parts.append(first_sentence)

    # Parameter names
    schema = action.get("input_schema", {})
    props = schema.get("properties", {})
    if props:
        param_names = sorted(props.keys())[:6]  # cap at 6
        parts.append(f"Params: {', '.join(param_names)}")

    # Risk annotation
    if risk in ("high", "critical"):
        parts.append(f"[Risk: {risk}]")

    return " — ".join(parts)


def filter_actions(
    actions: dict[str, dict[str, Any]],
    *,
    tools_glob: str | None = None,
    max_risk: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Filter actions by name glob pattern and/or risk tier ceiling.

    Args:
        actions: dict of action_name -> action_dict
        tools_glob: fnmatch-style glob pattern for action names
        max_risk: maximum risk tier to include (inclusive)

    Returns:
        Filtered dict of actions.
    """
    if max_risk is not None:
        try:
            ceiling = _RISK_LEVELS.index(max_risk)
        except ValueError:
            ceiling = len(_RISK_LEVELS) - 1
    else:
        ceiling = len(_RISK_LEVELS) - 1

    result = {}
    for name, action in actions.items():
        # Glob filter
        if tools_glob is not None and not fnmatch(name, tools_glob):
            continue
        # Risk ceiling filter
        risk = action.get("risk_tier", "low")
        try:
            risk_idx = _RISK_LEVELS.index(risk)
        except ValueError:
            risk_idx = 0
        if risk_idx > ceiling:
            continue
        result[name] = action
    return result

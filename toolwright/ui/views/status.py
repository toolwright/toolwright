"""Status view — the governance compass.

Renders a compact status panel showing the current state of a toolpack:
lockfile, baseline, drift, verification, pending approvals, and alerts.
Always includes a "Next" action recommendation.

Three renderers:
- ``render_rich`` → Rich Panel (for TTY stderr)
- ``render_plain`` → ASCII text (for pipes, CI, dumb terminals)
- ``render_json`` → dict (for ``--json`` mode, serialized to stdout)
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from toolwright.ui.console import err_console, get_symbols
from toolwright.ui.ops import StatusModel
from toolwright.ui.views.next_steps import NextStepsInput, compute_next_steps


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lockfile_label(model: StatusModel) -> str:
    """Human-readable lockfile state."""
    if model.lockfile_state == "missing":
        return "missing"
    if model.lockfile_state == "pending":
        return f"pending  ({model.approved_count} approved \u00b7 {model.blocked_count} blocked \u00b7 {model.pending_count} pending)"
    if model.lockfile_state == "stale":
        return f"stale  ({model.approved_count} approved \u00b7 {model.blocked_count} blocked)"
    # sealed
    return f"sealed  ({model.approved_count} approved \u00b7 {model.blocked_count} blocked)"


def _baseline_label(model: StatusModel) -> str:
    if not model.has_baseline:
        return "missing"
    if model.baseline_age_seconds is not None:
        age = model.baseline_age_seconds
        if age < 60:
            return "current  (just now)"
        if age < 3600:
            return f"current  ({int(age / 60)}m ago)"
        if age < 86400:
            return f"current  ({int(age / 3600)}h ago)"
        return f"current  ({int(age / 86400)}d ago)"
    return "current"


def _drift_label(model: StatusModel) -> str:
    return {
        "not_checked": "not checked",
        "clean": "clean",
        "warnings": "warnings detected",
        "breaking": "BREAKING changes",
    }.get(model.drift_state, model.drift_state)


def _verify_label(model: StatusModel) -> str:
    return {
        "not_run": "not run",
        "pass": "pass",
        "fail": "FAIL",
        "partial": "partial",
    }.get(model.verification_state, model.verification_state)


def _status_icon(state: str) -> str:
    """Map state to SymbolSet icon name."""
    sym = get_symbols()
    good = {"sealed", "current", "clean", "pass"}
    bad = {"missing", "stale", "breaking", "fail"}
    warn = {"pending", "warnings", "partial"}
    unchecked = {"not_checked", "not_run"}

    if state in good:
        return f"[success]{sym.ok}[/success]"
    if state in bad:
        return f"[error]{sym.fail}[/error]"
    if state in warn:
        return f"[warning]{sym.warning}[/warning]"
    if state in unchecked:
        return f"[muted]{sym.pending}[/muted]"
    return f"[muted]{sym.pending}[/muted]"


def _build_next_steps_input(model: StatusModel) -> NextStepsInput:
    """Convert StatusModel to NextStepsInput."""
    return NextStepsInput(
        command="status",
        toolpack_id=model.toolpack_id,
        lockfile_state=model.lockfile_state,
        verification_state=model.verification_state,
        drift_state=model.drift_state,
        pending_count=model.pending_count,
        has_baseline=model.has_baseline,
        has_mcp_config=model.has_mcp_config,
        has_approved_lockfile=model.lockfile_state in ("sealed", "stale"),
        has_pending_lockfile=model.lockfile_state == "pending",
    )


# ---------------------------------------------------------------------------
# Rich renderer
# ---------------------------------------------------------------------------


def render_rich(model: StatusModel) -> RenderableType:
    """Build a Rich Panel showing governance status."""
    sym = get_symbols()

    # Status lines
    table = Table(show_header=False, show_lines=False, pad_edge=False, box=None, expand=True)
    table.add_column("Icon", width=3)
    table.add_column("Label", style="bold", min_width=12)
    table.add_column("Value")

    rows = [
        ("Toolpack", f"{model.toolpack_id or 'unknown'}  ({model.tool_count} tools)", "sealed"),
        ("Lockfile", _lockfile_label(model), model.lockfile_state),
        ("Baseline", _baseline_label(model), "current" if model.has_baseline else "missing"),
        ("Drift", _drift_label(model), model.drift_state),
        ("Verify", _verify_label(model), model.verification_state),
    ]

    for label, value, state in rows:
        icon = _status_icon(state)
        table.add_row(icon, label, value)

    # Pending + alerts
    parts: list[Text] = []
    if model.pending_count > 0:
        noun = "tool" if model.pending_count == 1 else "tools"
        parts.append(Text.from_markup(
            f"\n  [warning]Pending:  {model.pending_count} {noun} awaiting approval[/warning]"
        ))
    for alert in model.alerts:
        parts.append(Text.from_markup(f"\n  [error]Alert:    {alert}[/error]"))

    # Next step
    ns = compute_next_steps(_build_next_steps_input(model))
    next_text = Text.from_markup(
        f"\n  [next]Next {sym.arrow}[/next] [command]{ns.primary.command}[/command]"
        f"\n          {ns.primary.why}"
    )

    # Compose
    body = Text()
    body.append_text(Text.from_markup(""))  # placeholder for table gap
    # We'll use a Group to combine table + extras
    from rich.console import Group
    group_items: list[RenderableType] = [table]
    for p in parts:
        group_items.append(p)
    group_items.append(next_text)

    group = Group(*group_items)

    title = "[heading]Cask Status[/heading]"
    return Panel(group, title=title, expand=False, padding=(1, 2))


# ---------------------------------------------------------------------------
# Plain renderer
# ---------------------------------------------------------------------------


def render_plain(model: StatusModel) -> str:
    """Build plain-text status output (no ANSI, no Unicode box drawing)."""
    sym = get_symbols()
    lines: list[str] = []
    lines.append("Cask Status")
    lines.append("-" * 40)

    plain_icon = {
        "sealed": "[OK]", "current": "[OK]", "clean": "[OK]", "pass": "[OK]",
        "missing": "[FAIL]", "stale": "[FAIL]", "breaking": "[FAIL]", "fail": "[FAIL]",
        "pending": "[WARN]", "warnings": "[WARN]", "partial": "[WARN]",
        "not_checked": "[--]", "not_run": "[--]",
    }

    rows = [
        ("Toolpack", f"{model.toolpack_id or 'unknown'}  ({model.tool_count} tools)", "sealed"),
        ("Lockfile", _lockfile_label(model).replace("\u00b7", "-"), model.lockfile_state),
        ("Baseline", _baseline_label(model), "current" if model.has_baseline else "missing"),
        ("Drift", _drift_label(model), model.drift_state),
        ("Verify", _verify_label(model), model.verification_state),
    ]

    for label, value, state in rows:
        icon = plain_icon.get(state, "[--]")
        lines.append(f"  {icon:>6}  {label:<12} {value}")

    if model.pending_count > 0:
        noun = "tool" if model.pending_count == 1 else "tools"
        lines.append(f"\n  Pending:  {model.pending_count} {noun} awaiting approval")
    for alert in model.alerts:
        lines.append(f"  Alert:    {alert}")

    ns = compute_next_steps(_build_next_steps_input(model))
    lines.append(f"\n  Next -> {ns.primary.command}")
    lines.append(f"          {ns.primary.why}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON renderer
# ---------------------------------------------------------------------------


def render_json(model: StatusModel) -> dict[str, Any]:
    """Build JSON-serializable status dict."""
    ns = compute_next_steps(_build_next_steps_input(model))
    return {
        "toolpack_id": model.toolpack_id,
        "toolpack_path": model.toolpack_path,
        "root": model.root,
        "tool_count": model.tool_count,
        "lockfile": {
            "state": model.lockfile_state,
            "path": model.lockfile_path,
            "approved": model.approved_count,
            "blocked": model.blocked_count,
            "pending": model.pending_count,
        },
        "baseline": {
            "exists": model.has_baseline,
            "age_seconds": model.baseline_age_seconds,
        },
        "drift": model.drift_state,
        "verification": model.verification_state,
        "has_mcp_config": model.has_mcp_config,
        "alerts": model.alerts,
        "next_step": {
            "command": ns.primary.command,
            "label": ns.primary.label,
            "why": ns.primary.why,
        },
        "alternatives": [
            {"command": a.command, "label": a.label, "why": a.why}
            for a in ns.alternatives
        ],
    }

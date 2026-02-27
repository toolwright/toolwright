"""Visual diff rendering for drift reports, plan reports, and repair diffs.

Stable categories (locked — never add new ones without version bump):
- BREAKING, AUTH, POLICY, SCHEMA, RISK, INFO

Three renderers:
- ``render_rich`` → Rich Tree with severity-colored nodes
- ``render_plain`` → ASCII-prefixed text (no ANSI, no box drawing)
- ``render_json`` → dict for ``--json`` mode
"""

from __future__ import annotations

from typing import Any

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from toolwright.ui.console import get_symbols

# ---------------------------------------------------------------------------
# Stable category → style mapping
# ---------------------------------------------------------------------------

_CATEGORY_STYLES = {
    "breaking": "drift.breaking",
    "auth": "drift.auth",
    "policy": "drift.policy",
    "schema": "drift.schema",
    "risk": "drift.risk",
    "info": "drift.info",
}

_CATEGORY_LABELS = {
    "breaking": "BREAKING",
    "auth": "AUTH",
    "policy": "POLICY",
    "schema": "SCHEMA",
    "risk": "RISK",
    "info": "INFO",
}


# ---------------------------------------------------------------------------
# Data contract
# ---------------------------------------------------------------------------


class DiffItem:
    """A single diff item for rendering.

    This is a view-layer object, not a domain model.  Flows construct
    these from DriftItem, PlanChange, or RepairDiagnosis objects.
    """

    def __init__(
        self,
        category: str,
        title: str,
        *,
        details: list[tuple[str, str]] | None = None,
        action: str | None = None,
    ) -> None:
        self.category = category.lower()
        self.title = title
        self.details = details or []  # (label, value) pairs
        self.action = action


class DiffSummary:
    """Collection of DiffItems with summary counts."""

    def __init__(self, items: list[DiffItem], exit_code: int = 0) -> None:
        self.items = items
        self.exit_code = exit_code

    @property
    def counts(self) -> dict[str, int]:
        """Count items per category."""
        c: dict[str, int] = {}
        for item in self.items:
            c[item.category] = c.get(item.category, 0) + 1
        return c

    @property
    def total(self) -> int:
        return len(self.items)


# ---------------------------------------------------------------------------
# Rich renderer
# ---------------------------------------------------------------------------


def render_rich(summary: DiffSummary, *, title: str = "Changes") -> RenderableType:
    """Build a Rich Panel with tree-style diff items."""
    sym = get_symbols()

    if not summary.items:
        return Panel("[muted]No changes detected[/muted]", title=title, expand=False)

    items_renderables: list[RenderableType] = []

    for item in summary.items:
        cat_label = _CATEGORY_LABELS.get(item.category, item.category.upper())
        cat_style = _CATEGORY_STYLES.get(item.category, "muted")

        # Category + title line
        header = Text.from_markup(f"  [{cat_style}]{cat_label}[/{cat_style}]  {item.title}")
        items_renderables.append(header)

        # Detail lines with tree branches
        for i, (label, value) in enumerate(item.details):
            is_last = (i == len(item.details) - 1) and not item.action
            branch = sym.corner if is_last else sym.branch
            items_renderables.append(Text.from_markup(f"  {branch} {label}: {value}"))

        # Action line
        if item.action:
            items_renderables.append(Text.from_markup(
                f"  {sym.corner} [next]Action: {item.action}[/next]"
            ))

        # Blank line between items
        items_renderables.append(Text(""))

    # Summary footer
    parts: list[str] = []
    for cat in ("breaking", "auth", "policy", "schema", "risk", "info"):
        count = summary.counts.get(cat, 0)
        if count:
            style = _CATEGORY_STYLES.get(cat, "muted")
            parts.append(f"[{style}]{count} {cat}[/{style}]")

    sep = " \u00b7 "
    footer = Text.from_markup(
        f"  {summary.total} changes: {sep.join(parts)}\n"
        f"  Exit code: {summary.exit_code}"
    )
    items_renderables.append(footer)

    return Panel(Group(*items_renderables), title=title, expand=False, padding=(1, 2))


# ---------------------------------------------------------------------------
# Plain renderer
# ---------------------------------------------------------------------------


def render_plain(summary: DiffSummary, *, title: str = "Changes") -> str:
    """Build plain-text diff output (no ANSI, no Unicode)."""
    if not summary.items:
        return f"{title}\n  No changes detected"

    lines: list[str] = [title, "-" * 40]

    for item in summary.items:
        cat_label = _CATEGORY_LABELS.get(item.category, item.category.upper())
        lines.append(f"  [{cat_label}] {item.title}")

        for label, value in item.details:
            lines.append(f"    {label}: {value}")

        if item.action:
            lines.append(f"    Action: {item.action}")

        lines.append("")

    # Summary
    parts = []
    for cat in ("breaking", "auth", "policy", "schema", "risk", "info"):
        count = summary.counts.get(cat, 0)
        if count:
            parts.append(f"{count} {cat}")

    lines.append(f"  {summary.total} changes: {' - '.join(parts)}")
    lines.append(f"  Exit code: {summary.exit_code}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON renderer
# ---------------------------------------------------------------------------


def render_json(summary: DiffSummary) -> dict[str, Any]:
    """Build JSON-serializable diff dict."""
    return {
        "total": summary.total,
        "exit_code": summary.exit_code,
        "counts": summary.counts,
        "items": [
            {
                "category": item.category,
                "title": item.title,
                "details": dict(item.details),
                "action": item.action,
            }
            for item in summary.items
        ],
    }

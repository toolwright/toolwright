"""Enhanced Rich table formatters for the Toolwright TUI.

SymbolSet-aware: uses Unicode or ASCII glyphs based on terminal capability.
All functions accept optional console for test injection.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table

from toolwright.ui.console import get_symbols

if TYPE_CHECKING:
    from toolwright.core.approval.lockfile import ToolApproval
    from toolwright.ui.ops import PreflightCheck

_RISK_STYLES = {
    "low": "risk.low",
    "medium": "risk.medium",
    "high": "risk.high",
    "critical": "risk.critical",
}

_RISK_EXPLANATIONS = {
    "critical": "Admin or destructive endpoint with broad impact",
    "high": "State-changing endpoint with PII or auth access",
    "medium": "State-changing endpoint with moderate scope",
    "low": "Read-only endpoint with minimal risk",
}


def _risk_sort(risk: str) -> int:
    """Sort key: critical first, low last."""
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(risk, 4)


def tool_approval_table(
    tools: list[ToolApproval],
    *,
    show_signature: bool = False,
    show_risk_explanation: bool = False,
) -> Table:
    """Build a Rich Table showing tools with status, risk, method, and path.

    When ``show_risk_explanation`` is True, adds a column explaining why
    each risk tier was assigned.
    """
    sym = get_symbols()
    status_icons = {
        "approved": f"[success]{sym.ok}[/success]",
        "pending": f"[warning]{sym.pending}[/warning]",
        "rejected": f"[error]{sym.fail}[/error]",
    }

    table = Table(title="Tool Approvals", show_lines=False, pad_edge=False)
    table.add_column("", width=3)  # status icon
    table.add_column("Tool", style="bold")
    table.add_column("Risk")
    table.add_column("Method")
    table.add_column("Path")
    table.add_column("Host", style="muted")
    if show_risk_explanation:
        table.add_column("Why", style="muted")
    if show_signature:
        table.add_column("Signature", style="muted")

    for tool in sorted(tools, key=lambda t: (_risk_sort(t.risk_tier), t.name)):
        icon = status_icons.get(tool.status, "?")
        risk_style = _RISK_STYLES.get(tool.risk_tier, "")
        risk_text = f"[{risk_style}]{tool.risk_tier}[/{risk_style}]" if risk_style else tool.risk_tier
        row: list[str] = [
            icon,
            tool.name,
            risk_text,
            tool.method.upper(),
            tool.path,
            tool.host,
        ]
        if show_risk_explanation:
            row.append(_RISK_EXPLANATIONS.get(tool.risk_tier, ""))
        if show_signature:
            sig = (tool.approval_signature or "")[:20]
            row.append(sig + "..." if len(tool.approval_signature or "") > 20 else sig)
        table.add_row(*row)

    return table


def doctor_checklist(
    checks: list[tuple[str, bool, str]],
) -> Table:
    """Build a checklist table: (label, passed, detail)."""
    sym = get_symbols()

    table = Table(show_header=False, show_lines=False, pad_edge=False, box=None)
    table.add_column("", width=3)
    table.add_column("Check", style="bold")
    table.add_column("Detail")

    for label, passed, detail in checks:
        icon = f"[success]{sym.ok}[/success]" if passed else f"[error]{sym.fail}[/error]"
        style = "" if passed else "error"
        table.add_row(icon, f"[{style}]{label}[/{style}]" if style else label, detail)

    return table


def preflight_checklist(
    checks: list[PreflightCheck],
) -> Table:
    """Build a checklist table from PreflightCheck objects."""
    return doctor_checklist(
        [(c.name, c.passed, c.detail) for c in checks]
    )


def risk_summary_panel(tools: list[ToolApproval]) -> Panel:
    """Compact panel showing counts per risk tier."""
    counts: Counter[str] = Counter()
    for t in tools:
        counts[t.risk_tier] += 1

    parts: list[str] = []
    for tier in ("critical", "high", "medium", "low"):
        if counts[tier]:
            style = _RISK_STYLES.get(tier, "")
            parts.append(f"[{style}]{tier}: {counts[tier]}[/{style}]")

    body = "  ".join(parts) if parts else "[muted]no tools[/muted]"
    return Panel(body, title="Risk Summary", expand=False)


def risk_grouped_summary(tools: list[ToolApproval]) -> dict[str, list[ToolApproval]]:
    """Group tools by risk tier (critical first, low last)."""
    groups: dict[str, list[ToolApproval]] = {
        "critical": [],
        "high": [],
        "medium": [],
        "low": [],
    }
    for t in tools:
        tier = t.risk_tier if t.risk_tier in groups else "low"
        groups[tier].append(t)
    return {k: v for k, v in groups.items() if v}

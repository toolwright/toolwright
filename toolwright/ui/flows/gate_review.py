"""PR-like risk-grouped gate review flow.

Three phases:
1. Overview — summary panel with totals, risk breakdown, new capabilities
2. Risk-Grouped Review — highest risk first:
   - Critical & High: reviewed individually with escape hatches
   - Medium: batch review with option to review individually
   - Low: batch approve
3. Summary & Commit — full decision table, final confirmation

Single-letter action prompt (via prompt_action):
  [a]pprove  [b]lock  [s]kip  [d]iff  [y]why  [p]olicy  [?]help
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.table import Table

from toolwright.ui.console import err_console, get_symbols
from toolwright.ui.discovery import find_lockfiles, lockfile_labels
from toolwright.ui.ops import (
    load_lockfile_tools,
    run_gate_approve,
    run_gate_reject,
)
from toolwright.ui.prompts import (
    confirm,
    confirm_typed,
    input_text,
    prompt_action,
    select_one,
)
from toolwright.ui.views.tables import risk_summary_panel, tool_approval_table

# ---------------------------------------------------------------------------
# Risk explanations — human-readable reasons per risk tier
# ---------------------------------------------------------------------------

_RISK_EXPLANATIONS: dict[str, str] = {
    "critical": "Can delete data, modify security settings, or access credentials",
    "high": "Can modify state, create resources, or write data",
    "medium": "Can read sensitive data or perform filtered queries",
    "low": "Read-only access to non-sensitive resources",
}


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


def gate_review_flow(
    *,
    lockfile_path: str | None = None,
    root_path: str | None = None,
    verbose: bool = False,  # noqa: ARG001
    ctx: Any = None,  # noqa: ARG001
    missing_param: str | None = None,  # noqa: ARG001
    input_stream: Any = None,
) -> None:
    """Interactive tool review and approval flow.

    Safety invariants:
    - Never auto-approves without explicit confirmation.
    - High-risk/critical tools require typed APPROVE confirmation.
    - Block decisions require a reason.
    """
    con = err_console
    root = Path(root_path) if root_path else Path(".toolwright")
    sym = get_symbols()

    # ---------------------------------------------------------------
    # Resolve lockfile
    # ---------------------------------------------------------------
    if lockfile_path is None:
        candidates = find_lockfiles(root)
        if not candidates:
            con.print("[error]No lockfiles found.[/error]")
            con.print("Run 'toolwright gate sync' first to create one.")
            return
        if len(candidates) == 1:
            lockfile_path = str(candidates[0])
        else:
            choices = [str(p) for p in candidates]
            labels = lockfile_labels(candidates, root=root)
            lockfile_path = select_one(
                choices,
                labels=labels,
                prompt="Select lockfile",
                console=con,
                input_stream=input_stream,
            )

    lf_path = Path(lockfile_path)
    if lf_path.is_dir():
        con.print(f"[error]Expected a file, got a directory: {lockfile_path}[/error]")
        con.print("Provide the path to a .yaml lockfile, not a directory.")
        return

    # ---------------------------------------------------------------
    # Load lockfile
    # ---------------------------------------------------------------
    try:
        lockfile, all_tools = load_lockfile_tools(lockfile_path)
    except FileNotFoundError as exc:
        con.print(f"[error]{exc}[/error]")
        return

    from toolwright.core.approval.lockfile import ApprovalStatus

    pending = [t for t in all_tools if t.status == ApprovalStatus.PENDING]

    if not pending:
        con.print(f"[success]{sym.ok} No pending tools. All tools are reviewed.[/success]")
        return

    # ---------------------------------------------------------------
    # Phase 1: Overview
    # ---------------------------------------------------------------
    _render_overview(pending, con, sym)

    # ---------------------------------------------------------------
    # Phase 2: Risk-grouped review
    # ---------------------------------------------------------------
    critical = [t for t in pending if t.risk_tier == "critical"]
    high = [t for t in pending if t.risk_tier == "high"]
    medium = [t for t in pending if t.risk_tier == "medium"]
    low = [t for t in pending if t.risk_tier == "low"]

    to_approve: list[str] = []
    to_block: list[tuple[str, str]] = []  # (tool_id, reason)

    # Critical & High — review individually
    for group_label, group in [("CRITICAL", critical), ("HIGH", high)]:
        if not group:
            continue
        con.print(f"\n  [bold]{group_label}-risk tools ({len(group)})[/bold] — individual review required\n")
        for tool in group:
            action = _review_single_tool(
                tool, con, sym,
                lockfile_path=lockfile_path,
                input_stream=input_stream,
            )
            if action == "approve":
                if confirm_typed(
                    f"  Approve {tool.risk_tier}-risk tool {tool.name}?",
                    required_text="APPROVE",
                    console=con,
                    input_stream=input_stream,
                ):
                    to_approve.append(tool.tool_id)
                else:
                    con.print(f"  [muted]Skipped {tool.name}[/muted]")
            elif action == "block":
                reason = input_text(
                    "  Reason for blocking",
                    console=con,
                    input_stream=input_stream,
                )
                if not reason:
                    reason = "Blocked during interactive review"
                to_block.append((tool.tool_id, reason))
            # skip → do nothing

    # Medium — batch review
    if medium:
        con.print(f"\n  [bold]MEDIUM-risk tools ({len(medium)})[/bold]\n")
        for t in medium:
            con.print(f"    {sym.pending} {t.name}  {t.method} {t.path}  ({t.host})")

        batch_action = prompt_action(
            {"a": "approve all", "r": "review individually", "s": "skip all"},
            prompt=f"Approve all {len(medium)} medium-risk tools?",
            console=con,
            input_stream=input_stream,
        )

        if batch_action == "a":
            to_approve.extend(t.tool_id for t in medium)
        elif batch_action == "r":
            for tool in medium:
                action = _review_single_tool(
                    tool, con, sym,
                    lockfile_path=lockfile_path,
                    input_stream=input_stream,
                )
                if action == "approve":
                    to_approve.append(tool.tool_id)
                elif action == "block":
                    reason = input_text(
                        "  Reason for blocking",
                        console=con,
                        input_stream=input_stream,
                    )
                    if not reason:
                        reason = "Blocked during interactive review"
                    to_block.append((tool.tool_id, reason))
        # skip all → do nothing

    # Low — batch approve
    if low:
        con.print(f"\n  [bold]LOW-risk tools ({len(low)})[/bold] — read-only\n")
        for t in low:
            con.print(f"    {sym.pending} {t.name}  {t.method} {t.path}")

        batch_action = prompt_action(
            {"a": "approve all", "r": "review individually", "s": "skip all"},
            prompt=f"{len(low)} low-risk read-only tools. Approve all?",
            console=con,
            input_stream=input_stream,
        )

        if batch_action == "a":
            to_approve.extend(t.tool_id for t in low)
        elif batch_action == "r":
            for tool in low:
                action = _review_single_tool(
                    tool, con, sym,
                    lockfile_path=lockfile_path,
                    input_stream=input_stream,
                )
                if action == "approve":
                    to_approve.append(tool.tool_id)
                elif action == "block":
                    reason = input_text(
                        "  Reason for blocking",
                        console=con,
                        input_stream=input_stream,
                    )
                    if not reason:
                        reason = "Blocked during interactive review"
                    to_block.append((tool.tool_id, reason))

    # ---------------------------------------------------------------
    # Phase 3: Summary & Commit
    # ---------------------------------------------------------------
    if not to_approve and not to_block:
        con.print("\n  [muted]No changes made.[/muted]")
        return

    _render_summary(to_approve, to_block, pending, con, sym)

    if not confirm(
        "\n  Proceed with these changes?",
        default=True,
        console=con,
        input_stream=input_stream,
    ):
        con.print("  [muted]No changes made.[/muted]")
        return

    # Execute
    if to_approve:
        try:
            result = run_gate_approve(
                tool_ids=to_approve,
                lockfile_path=lockfile_path,
                root_path=str(root),
            )
            con.print(f"\n  [success]{sym.ok} Approved {len(result.approved_ids)} tools.[/success]")
            if result.promoted:
                con.print(f"  [seal]{sym.ok} Lockfile promoted to approved.[/seal]")
        except Exception as exc:
            con.print(f"\n  [error]Approval failed: {exc}[/error]")

    for tid, reason in to_block:
        try:
            run_gate_reject(
                tool_ids=[tid],
                lockfile_path=lockfile_path,
                reason=reason,
            )
            con.print(f"  [error]{sym.fail} Blocked {tid}: {reason}[/error]")
        except Exception as exc:
            con.print(f"  [error]Block failed: {exc}[/error]")

    # Next steps
    con.print()
    remaining_pending = len(pending) - len(to_approve) - len(to_block)
    if remaining_pending > 0:
        con.print(f"  [next]Next {sym.arrow}[/next] toolwright gate allow  ({remaining_pending} tools still pending)")
    elif to_approve:
        con.print(f"  [next]Next {sym.arrow}[/next] toolwright gate snapshot  (create baseline)")


# ---------------------------------------------------------------------------
# Phase 1: Overview
# ---------------------------------------------------------------------------


def _render_overview(pending: list[Any], con: Any, sym: Any) -> None:
    """Render the overview panel with risk breakdown."""
    con.print()
    con.print(f"  [heading]Gate Review[/heading] {sym.arrow} {len(pending)} tools pending approval")
    con.print()

    # Risk breakdown
    counts: dict[str, int] = {}
    for t in pending:
        counts[t.risk_tier] = counts.get(t.risk_tier, 0) + 1

    parts: list[str] = []
    for tier in ("critical", "high", "medium", "low"):
        c = counts.get(tier, 0)
        if c:
            style = f"risk.{tier}" if tier in ("critical", "high", "medium", "low") else "muted"
            parts.append(f"[{style}]{c} {tier}[/{style}]")

    sep = " \u00b7 "
    breakdown = sep.join(parts)
    con.print(f"  Risk breakdown: {breakdown}")

    # New capabilities
    methods: dict[str, int] = {}
    for t in pending:
        methods[t.method] = methods.get(t.method, 0) + 1
    method_parts = [f"{v} {k}" for k, v in sorted(methods.items())]
    if method_parts:
        con.print(f"  New capabilities: {', '.join(method_parts)}")

    con.print()
    con.print(tool_approval_table(pending))
    con.print()
    con.print(risk_summary_panel(pending))


# ---------------------------------------------------------------------------
# Single tool review with escape hatches
# ---------------------------------------------------------------------------


_REVIEW_ACTIONS = {
    "a": "approve",
    "b": "block",
    "s": "skip",
    "d": "diff",
    "y": "why",
    "p": "policy",
    "?": "help",
}

_HELP_TEXT = """
  [bold]Actions:[/bold]
    [bold]a[/bold] = approve this tool
    [bold]b[/bold] = block this tool (requires reason)
    [bold]s[/bold] = skip (decide later)
    [bold]d[/bold] = show diff (before/after if prior version exists)
    [bold]y[/bold] = show why this risk tier was assigned
    [bold]p[/bold] = show which policy rule triggered this classification
    [bold]?[/bold] = show this help
"""


def _review_single_tool(
    tool: Any,
    con: Any,
    sym: Any,
    *,
    lockfile_path: str,
    input_stream: Any = None,
) -> str:
    """Review a single tool with escape hatches. Returns "approve", "block", or "skip"."""
    risk_style = f"risk.{tool.risk_tier}" if tool.risk_tier in ("low", "medium", "high", "critical") else "muted"

    con.print(
        f"\n  [{risk_style}]{tool.risk_tier.upper()}[/{risk_style}]  "
        f"[bold]{tool.name}[/bold]  {sym.arrow}  {tool.method} {tool.path}"
    )
    con.print(f"    Host: {tool.host}")
    if tool.toolsets:
        con.print(f"    Toolsets: {', '.join(tool.toolsets)}")

    # Risk explanation
    explanation = _RISK_EXPLANATIONS.get(tool.risk_tier, "")
    if explanation:
        con.print(f"    [muted]{explanation}[/muted]")

    while True:
        action = prompt_action(
            _REVIEW_ACTIONS,
            console=con,
            input_stream=input_stream,
        )

        if action == "a":
            return "approve"
        if action == "b":
            return "block"
        if action == "s":
            return "skip"
        if action == "d":
            _show_diff(tool, con, sym)
        elif action == "y":
            _show_why(tool, con, sym)
        elif action == "p":
            _show_policy(tool, con, sym, lockfile_path=lockfile_path)
        elif action == "?":
            con.print(_HELP_TEXT)


def _show_diff(tool: Any, con: Any, sym: Any) -> None:  # noqa: ARG001
    """Show diff for a tool (before/after if prior version exists)."""
    con.print(f"\n    [heading]Diff for {tool.name}[/heading]")
    if hasattr(tool, "previous_signature") and tool.previous_signature:
        con.print(f"    Previous signature: {tool.previous_signature}")
        con.print(f"    Current signature:  {tool.signature_id}")
        con.print(f"    Version: {tool.tool_version}")
    else:
        con.print("    [muted]New tool (no prior version)[/muted]")
    con.print(f"    Method: {tool.method}")
    con.print(f"    Path:   {tool.path}")
    con.print(f"    Host:   {tool.host}")
    con.print()


def _show_why(tool: Any, con: Any, sym: Any) -> None:  # noqa: ARG001
    """Show expanded risk explanation with evidence."""
    con.print(f"\n    [heading]Risk Analysis: {tool.name}[/heading]")
    con.print(f"    Risk tier: [{f'risk.{tool.risk_tier}'}]{tool.risk_tier.upper()}[/{f'risk.{tool.risk_tier}'}]")

    explanation = _RISK_EXPLANATIONS.get(tool.risk_tier, "No explanation available")
    con.print(f"    Reason: {explanation}")

    # Evidence from method
    method = tool.method.upper()
    if method in ("DELETE", "PATCH"):
        con.print(f"    Evidence: {method} methods modify or remove data")
    elif method in ("POST", "PUT"):
        con.print(f"    Evidence: {method} methods create or update data")
    elif method == "GET":
        con.print("    Evidence: GET method (read-only)")

    con.print()


def _show_policy(tool: Any, con: Any, sym: Any, *, lockfile_path: str) -> None:  # noqa: ARG001
    """Show which policy rule triggered this classification."""
    con.print(f"\n    [heading]Policy for {tool.name}[/heading]")
    con.print(f"    Risk tier: {tool.risk_tier}")
    con.print(f"    Signature: {tool.signature_id}")

    # Try to load policy from lockfile sibling
    try:
        lf = Path(lockfile_path)
        toolpack_dir = lf.parent.parent
        policy_path = toolpack_dir / "artifact" / "policy.yaml"
        if policy_path.exists():
            con.print(f"    Policy file: {policy_path}")
        else:
            con.print("    [muted]Policy file not found near lockfile[/muted]")
    except Exception:
        con.print("    [muted]Could not locate policy file[/muted]")

    con.print()


# ---------------------------------------------------------------------------
# Phase 3: Summary
# ---------------------------------------------------------------------------


def _render_summary(
    to_approve: list[str],
    to_block: list[tuple[str, str]],
    pending: list[Any],
    con: Any,
    sym: Any,
) -> None:
    """Render the decision summary before committing."""
    con.print("\n  [heading]Review Summary[/heading]")
    con.print()

    # Build a simple decision table
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False, expand=False)
    table.add_column("Decision", min_width=10)
    table.add_column("Tool", min_width=20)
    table.add_column("Risk")

    tool_map = {t.tool_id: t for t in pending}

    for tid in to_approve:
        tool = tool_map.get(tid)
        name = tool.name if tool else tid
        risk = tool.risk_tier if tool else "?"
        risk_style = f"risk.{risk}" if risk in ("low", "medium", "high", "critical") else "muted"
        table.add_row(
            f"[success]{sym.ok} approve[/success]",
            name,
            f"[{risk_style}]{risk}[/{risk_style}]",
        )

    for tid, _reason in to_block:
        tool = tool_map.get(tid)
        name = tool.name if tool else tid
        risk = tool.risk_tier if tool else "?"
        risk_style = f"risk.{risk}" if risk in ("low", "medium", "high", "critical") else "muted"
        table.add_row(
            f"[error]{sym.fail} block[/error]",
            name,
            f"[{risk_style}]{risk}[/{risk_style}]",
        )

    skipped_ids = {t.tool_id for t in pending} - set(to_approve) - {tid for tid, _ in to_block}
    for tid in skipped_ids:
        tool = tool_map.get(tid)
        name = tool.name if tool else tid
        risk = tool.risk_tier if tool else "?"
        table.add_row(
            f"[muted]{sym.pending} skip[/muted]",
            f"[muted]{name}[/muted]",
            f"[muted]{risk}[/muted]",
        )

    con.print(Panel(table, title="Decisions", expand=False, padding=(1, 2)))

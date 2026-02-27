"""Interactive gate snapshot flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from toolwright.ui.console import err_console
from toolwright.ui.discovery import find_lockfiles
from toolwright.ui.echo import echo_plan, echo_summary
from toolwright.ui.prompts import confirm, select_one
from toolwright.ui.runner import load_lockfile_tools, run_gate_snapshot


def gate_snapshot_flow(
    *,
    lockfile_path: str | None = None,
    root_path: str | None = None,
    verbose: bool = False,
    ctx: Any = None,  # noqa: ARG001
    missing_param: str | None = None,  # noqa: ARG001
) -> None:
    """Interactive snapshot flow with safe lockfile selection."""
    con = err_console
    root = Path(root_path) if root_path else Path(".toolwright")

    # Resolve lockfile
    if lockfile_path is None:
        candidates = find_lockfiles(root)
        # Prefer approved lockfiles
        approved = [c for c in candidates if "pending" not in c.name]
        pending_only = [c for c in candidates if "pending" in c.name]

        if approved:
            use = approved
        elif pending_only:
            con.print("[warning]Only pending lockfiles found. Approve tools first.[/warning]")
            use = pending_only
        else:
            con.print("[error]No lockfiles found.[/error]")
            return

        if len(use) == 1:
            lockfile_path = str(use[0])
        else:
            lockfile_path = select_one(
                [str(p) for p in use],
                prompt="Select lockfile",
                console=con,
            )

    # Validate: file, not directory
    lf = Path(lockfile_path)
    if lf.is_dir():
        con.print(f"[error]Expected a file, got a directory: {lockfile_path}[/error]")
        return

    # Check for pending tools
    try:
        lockfile, all_tools = load_lockfile_tools(lockfile_path)
    except FileNotFoundError as exc:
        con.print(f"[error]{exc}[/error]")
        return

    from toolwright.core.approval.lockfile import ApprovalStatus

    pending = [t for t in all_tools if t.status == ApprovalStatus.PENDING]
    if pending:
        con.print(f"[warning]{len(pending)} tools are still pending approval.[/warning]")
        con.print("Approve them first with 'toolwright gate allow'.")
        if confirm("Jump to gate review now?", default=True, console=con):
            from toolwright.ui.flows.gate_review import gate_review_flow

            gate_review_flow(lockfile_path=lockfile_path, root_path=str(root), verbose=verbose)
        return

    # Plan + confirm
    cmd = ["toolwright", "gate", "snapshot", "--lockfile", lockfile_path]
    echo_plan([cmd], console=con)

    if not confirm("Create baseline snapshot?", default=True, console=con):
        return

    # Execute
    try:
        result = run_gate_snapshot(lockfile_path=lockfile_path, root_path=str(root))
        con.print("[success]Baseline snapshot created.[/success]")
        if result:
            con.print(f"  Path: {result}")
    except (FileNotFoundError, ValueError) as exc:
        con.print(f"[error]Snapshot failed: {exc}[/error]")
        return

    echo_summary([cmd], console=con)

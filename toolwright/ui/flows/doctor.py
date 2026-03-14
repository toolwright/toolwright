"""Interactive doctor flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from toolwright.ui import prompts as prompt_primitives
from toolwright.ui.console import err_console
from toolwright.ui.discovery import find_toolpacks, toolpack_labels
from toolwright.ui.echo import echo_plan, echo_summary
from toolwright.ui.prompts import select_one
from toolwright.ui.runner import run_doctor_checks
from toolwright.ui.tables import doctor_checklist


def confirm(message: str, *, default: bool = False, console: Any = None) -> bool:
    """Delegate confirmation through the shared prompt module.

    Keeping a flow-local symbol preserves test patch points while still letting
    callers patch ``toolwright.ui.prompts.confirm`` when they need to.
    """
    return prompt_primitives.confirm(message, default=default, console=console)


def doctor_flow(
    *,
    toolpack_path: str | None = None,
    root: Path | None = None,
    verbose: bool = False,  # noqa: ARG001
    ctx: Any = None,  # noqa: ARG001
    missing_param: str | None = None,  # noqa: ARG001
) -> None:
    """Interactive doctor flow.

    If toolpack_path is None, prompts user to select a toolpack.
    Shows plan, confirms, runs checks, displays Rich checklist.
    """
    con = err_console

    if root is None:
        root = Path(".toolwright")

    # Resolve toolpack path
    if toolpack_path is None:
        candidates = find_toolpacks(root)
        if not candidates:
            con.print("[error]No toolpack found.[/error]")
            con.print("Create one with: [command]toolwright create <recipe-name>[/command]")
            return
        if len(candidates) == 1:
            toolpack_path = str(candidates[0])
            con.print(f"Found toolpack: [bold]{toolpack_labels(candidates, root=root)[0]}[/bold]")
        else:
            toolpack_path = select_one(
                [str(p) for p in candidates],
                labels=toolpack_labels(candidates, root=root),
                prompt="Select toolpack",
                console=con,
            )

    # Plan
    cmd = ["toolwright", "doctor", "--toolpack", toolpack_path]
    echo_plan([cmd], console=con)

    if not confirm("Run doctor checks?", default=True, console=con):
        return

    # Execute
    try:
        result = run_doctor_checks(toolpack_path, runtime="auto")
    except (FileNotFoundError, ValueError) as exc:
        con.print(f"[error]Error: {exc}[/error]")
        return

    # Display
    check_tuples = [(c.name, c.passed, c.detail) for c in result.checks]
    table = doctor_checklist(check_tuples)
    con.print()
    con.print(table)
    con.print()

    if result.all_passed:
        con.print("[success]All checks passed.[/success]")
        con.print(f"Next: toolwright serve --toolpack {toolpack_path}")
    else:
        con.print("[error]Some checks failed. Fix the errors above and re-run.[/error]")

    echo_summary([cmd], console=con)

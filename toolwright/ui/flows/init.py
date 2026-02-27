"""Interactive init flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from toolwright.ui.console import err_console
from toolwright.ui.echo import echo_plan, echo_summary
from toolwright.ui.prompts import confirm, input_text


def init_flow(
    *,
    directory: str | None = None,
    verbose: bool = False,
    ctx: Any = None,  # noqa: ARG001
    missing_param: str | None = None,  # noqa: ARG001
) -> None:
    """Guided project initialization."""
    from toolwright.branding import PRODUCT_NAME

    con = err_console

    con.print()
    con.print(f"[heading]Initialize {PRODUCT_NAME}[/heading]")
    con.print()

    if directory is None:
        directory = input_text("Project directory", default=".", console=con)

    # Detect project
    con.print(f"[info]Detecting project at {directory}...[/info]")
    try:
        from toolwright.core.init.detector import detect_project

        detection = detect_project(Path(directory))
        if detection:
            con.print(f"  Type: {detection.project_type}")
            con.print(f"  Language: {detection.language}")
            if detection.frameworks:
                con.print(f"  Frameworks: {', '.join(detection.frameworks)}")
    except Exception:
        con.print("[muted]Could not detect project type.[/muted]")

    # Plan
    cmd = ["toolwright", "init", "-d", directory]
    echo_plan([cmd], console=con)

    if not confirm("Initialize Cask here?", default=True, console=con):
        return

    # Execute
    try:
        from toolwright.cli.init import run_init

        run_init(directory=directory, verbose=verbose)
    except SystemExit:
        pass
    except Exception as exc:
        con.print(f"[error]Init failed: {exc}[/error]")
        return

    con.print("[success]Cask initialized.[/success]")
    con.print("Next: toolwright mint <url> -a <host>  or  toolwright capture import <file> -a <host>")
    echo_summary([cmd], console=con)

"""Doctor command implementation.

Thin wrapper over ``toolwright.ui.runner.run_doctor_checks`` — the core logic
lives there so it can be used by both the CLI and the interactive TUI flow.
"""

from __future__ import annotations

import os
import sys

import click

from toolwright.ui.runner import run_doctor_checks


def _short_path(toolpack_path: str) -> str:
    """Return the shortest usable representation of toolpack_path.

    Prefers a relative path from cwd when it's shorter, otherwise falls back
    to the toolpack filename.
    """
    try:
        rel = os.path.relpath(toolpack_path)
        if not rel.startswith(".."):
            return rel
    except ValueError:
        pass
    return os.path.basename(toolpack_path)


def run_doctor(
    toolpack_path: str,
    runtime: str,
    verbose: bool,
    require_local_mcp: bool = False,
) -> None:
    """Validate toolpack readiness for execution."""
    try:
        result = run_doctor_checks(
            toolpack_path,
            runtime=runtime,
            require_local_mcp=require_local_mcp,
        )
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    errors = [c for c in result.checks if not c.passed]
    warnings: list[str] = []  # reserved for future use

    if errors:
        for check in errors:
            click.echo(f"Error: {check.detail}", err=True)
        click.echo("Doctor failed.", err=True)
        click.echo("Next: fix the errors above and re-run `toolwright doctor --toolpack <path>`.", err=True)
        sys.exit(1)

    if warnings:
        for warning in warnings:
            click.echo(f"Warning: {warning}", err=True)

    # Show each check that passed
    click.echo()
    for check in result.checks:
        mark = "pass" if check.passed else "FAIL"
        click.echo(f"  [{mark}] {check.name}")
    click.echo()
    click.echo("All checks passed.")

    short = _short_path(toolpack_path)
    click.echo(f"Next: toolwright serve --toolpack {short}")

    if verbose:
        click.echo(f"Runtime mode: {result.runtime_mode}")

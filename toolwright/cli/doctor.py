"""Doctor command implementation.

Thin wrapper over ``toolwright.ui.runner.run_doctor_checks`` — the core logic
lives there so it can be used by both the CLI and the interactive TUI flow.
"""

from __future__ import annotations

import sys

import click

from toolwright.ui.runner import run_doctor_checks


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

    click.echo("Doctor check passed.")
    click.echo(f"Next: toolwright serve --toolpack {toolpack_path}")
    click.echo(
        f"      toolwright config --toolpack {toolpack_path}",
    )

    if verbose:
        click.echo(f"Runtime mode: {result.runtime_mode}")

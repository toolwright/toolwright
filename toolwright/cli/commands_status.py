"""Status and dashboard command registration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from toolwright.utils.state import resolve_root


def register_status_commands(*, cli: click.Group) -> None:
    """Register top-level status-oriented commands."""

    @cli.command()
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml (auto-discovered if not given)",
    )
    @click.option(
        "--json",
        "json_mode",
        is_flag=True,
        help="Output status as JSON to stdout",
    )
    @click.pass_context
    def status(ctx: click.Context, toolpack: str | None, json_mode: bool) -> None:
        """Show governance status for a toolpack.

        The compass command — always-available orientation showing lockfile state,
        baseline, drift, verification, pending approvals, alerts, and recommended
        next action.

        \b
        Examples:
          toolwright status
          toolwright status --toolpack .toolwright/toolpacks/stripe-api/toolpack.yaml
          toolwright status --json
        """
        from toolwright.ui.ops import get_status
        from toolwright.ui.views.branding import render_plain_header, render_rich_header
        from toolwright.ui.views.status import render_json, render_plain, render_rich
        from toolwright.utils.resolve import resolve_toolpack_path

        root: Path = ctx.obj.get("root", resolve_root())

        try:
            toolpack_path = str(resolve_toolpack_path(explicit=toolpack, root=root))
        except (FileNotFoundError, click.UsageError) as exc:
            click.echo(str(exc), err=True)
            sys.exit(1)

        try:
            model = get_status(toolpack_path)
        except Exception as exc:
            click.echo(f"Error reading toolpack: {exc}", err=True)
            sys.exit(1)

        if json_mode:
            click.echo(json.dumps(render_json(model), indent=2))
            return

        from toolwright.ui.console import err_console

        if err_console.is_terminal:
            render_rich_header(root=str(root), toolpack_id=model.toolpack_id)
            err_console.print(render_rich(model))
        else:
            click.echo(render_plain_header(root=str(root), toolpack_id=model.toolpack_id), err=True)
            click.echo(render_plain(model), err=True)

    @cli.command()
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml (auto-discovered if not given)",
    )
    @click.pass_context
    def dashboard(ctx: click.Context, toolpack: str | None) -> None:
        """Open the full-screen governance dashboard.

        Read-only toolpack-scoped dashboard showing status, tools, audit,
        and recommended next actions. Requires toolwright[tui] (Textual).

        \b
        Examples:
          toolwright dashboard
          toolwright dashboard --toolpack .toolwright/toolpacks/stripe-api/toolpack.yaml
        """
        from toolwright.ui.dashboard import run_dashboard
        from toolwright.utils.resolve import resolve_toolpack_path

        root: Path = ctx.obj.get("root", resolve_root())

        try:
            toolpack_path = str(resolve_toolpack_path(explicit=toolpack, root=root))
        except (FileNotFoundError, click.UsageError) as exc:
            click.echo(str(exc), err=True)
            sys.exit(1)

        run_dashboard(toolpack_path=toolpack_path, root=str(root))

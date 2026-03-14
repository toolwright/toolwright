"""Snapshot listing and rollback CLI commands."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from toolwright.core.reconcile.versioner import ToolpackVersioner


def register_snapshot_commands(*, cli: click.Group) -> None:
    """Register the snapshots and rollback commands on the provided CLI group."""

    @cli.command()
    @click.option(
        "--root",
        type=click.Path(),
        default=None,
        help="Toolpack directory (default: current directory)",
    )
    def snapshots(root: str | None) -> None:
        """List toolpack snapshots.

        Reads from .toolwright/snapshots/ and displays a table of
        snapshot ID, label, and creation time.

        \b
        Examples:
          toolwright snapshots
          toolwright snapshots --root /path/to/toolpack
        """
        toolpack_dir = Path(root) if root else Path.cwd()
        versioner = ToolpackVersioner(toolpack_dir)
        snaps = versioner.list_snapshots()

        if not snaps:
            click.echo("No snapshots found.")
            return

        # Header
        click.echo(f"{'Snapshot ID':<45} {'Label':<25} {'Created At'}")
        click.echo("-" * 95)

        for snap in snaps:
            snap_id = snap.get("snapshot_id", "?")
            label = snap.get("label", "")
            created_at = snap.get("created_at", "?")
            click.echo(f"{snap_id:<45} {label:<25} {created_at}")

    @cli.command()
    @click.argument("snapshot_id")
    @click.option(
        "--root",
        type=click.Path(),
        default=None,
        help="Toolpack directory (default: current directory)",
    )
    @click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt.")
    @click.pass_context
    def rollback(ctx: click.Context, snapshot_id: str, root: str | None, yes: bool) -> None:
        """Rollback to a toolpack snapshot.

        Restores toolpack files from the specified snapshot.

        \b
        Examples:
          toolwright rollback 20260227T100000-abc12345
          toolwright rollback 20260227T100000-abc12345 --root /path/to/toolpack
        """
        no_interactive = ctx.obj.get("no_interactive_explicit", False) if ctx.obj else False
        if not yes and not no_interactive:
            click.confirm(f"Rollback to snapshot '{snapshot_id}'?", default=False, abort=True)

        toolpack_dir = Path(root) if root else Path.cwd()
        versioner = ToolpackVersioner(toolpack_dir)

        try:
            versioner.rollback(snapshot_id)
        except FileNotFoundError:
            click.echo(f"Error: Snapshot not found: {snapshot_id}", err=True)
            sys.exit(1)

        click.echo(f"Rolled back to snapshot {snapshot_id}")

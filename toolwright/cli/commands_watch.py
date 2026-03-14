"""Watch CLI commands: watch status, watch log."""

from __future__ import annotations

import json
from pathlib import Path

import click

from toolwright.utils.state import resolve_root


def register_watch_commands(*, cli: click.Group) -> None:
    """Register the watch command group on the provided CLI group."""

    @cli.group()
    def watch() -> None:
        """Monitor reconciliation loop health and events."""

    @watch.command()
    @click.option(
        "--root",
        type=click.Path(),
        default=None,
        help="Project root (default: auto-detect)",
    )
    def status(root: str | None) -> None:
        """Show per-tool health and reconciliation loop statistics.

        Reads the persisted reconcile state from .toolwright/state/reconcile.json.

        \b
        Examples:
          toolwright watch status
          toolwright watch status --root /path/to/project
        """
        project_root = Path(root) if root else resolve_root()
        state_file = project_root / ".toolwright" / "state" / "reconcile.json"

        if not state_file.exists():
            click.echo("Watch not running — no reconcile state found.")
            return

        from toolwright.models.reconcile import ReconcileState

        try:
            state = ReconcileState.model_validate_json(state_file.read_text())
        except Exception as e:
            click.echo(f"Error reading reconcile state: {e}", err=True)
            return

        click.echo(f"Reconcile cycles: {state.reconcile_count}")
        if state.last_full_reconcile:
            click.echo(f"Last reconcile:   {state.last_full_reconcile}")
        if state.errors:
            click.echo(f"Errors:           {state.errors}")
        click.echo()

        if not state.tools:
            click.echo("No tools tracked yet.")
            return

        # Header
        click.echo(
            f"{'Tool':<30} {'Status':<12} {'Healthy':<8} {'Unhealthy':<10} {'Last Probe'}"
        )
        click.echo("-" * 90)

        for tool_id, ts in sorted(state.tools.items()):
            status_display = ts.status.value.upper()
            if ts.status.value == "healthy":
                status_display = click.style(status_display, fg="green")
            elif ts.status.value == "unhealthy":
                status_display = click.style(status_display, fg="red")
            elif ts.status.value == "degraded":
                status_display = click.style(status_display, fg="yellow")

            last_probe = ts.last_probe_at or "never"
            click.echo(
                f"{tool_id:<30} {status_display:<21} "
                f"{ts.consecutive_healthy:<8} {ts.consecutive_unhealthy:<10} {last_probe}"
            )

    @watch.command()
    @click.option(
        "--tool",
        default=None,
        help="Filter events by tool ID",
    )
    @click.option(
        "--last",
        "last_n",
        type=int,
        default=20,
        help="Number of recent events to show (default: 20)",
    )
    @click.option(
        "--root",
        type=click.Path(),
        default=None,
        help="Project root (default: auto-detect)",
    )
    def log(tool: str | None, last_n: int, root: str | None) -> None:
        """Show recent reconciliation events.

        Reads the event log from .toolwright/state/reconcile.log.jsonl.

        \b
        Examples:
          toolwright watch log
          toolwright watch log --tool get_users
          toolwright watch log --last 50
        """
        project_root = Path(root) if root else resolve_root()
        log_file = project_root / ".toolwright" / "state" / "reconcile.log.jsonl"

        if not log_file.exists():
            click.echo("No events found — log is empty.")
            return

        try:
            with open(log_file) as f:
                lines = f.readlines()
        except Exception as e:
            click.echo(f"Error reading event log: {e}", err=True)
            return

        events = [json.loads(line) for line in lines]

        if tool:
            events = [e for e in events if e.get("tool_id") == tool]

        events = events[-last_n:]

        if not events:
            click.echo("No events found.")
            return

        for event in events:
            kind = event.get("kind", "unknown")
            tool_id = event.get("tool_id", "?")
            timestamp = event.get("timestamp", "?")
            description = event.get("description", "")

            # Color by event kind
            if "healthy" in kind:
                kind_display = click.style(kind, fg="green")
            elif "unhealthy" in kind or "failed" in kind:
                kind_display = click.style(kind, fg="red")
            elif "drift" in kind:
                kind_display = click.style(kind, fg="yellow")
            else:
                kind_display = kind

            click.echo(f"[{timestamp}] {kind_display} {tool_id}: {description}")

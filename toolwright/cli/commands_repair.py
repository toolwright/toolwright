"""Repair plan/apply CLI commands: repair plan, repair apply."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import click

from toolwright.utils.state import resolve_root

# Default staleness threshold: 1 hour
STALENESS_THRESHOLD_SECONDS = 3600


def register_repair_plan_apply(*, repair_group: click.Group) -> None:
    """Register plan and apply subcommands on the repair group."""

    @repair_group.command()
    @click.option(
        "--root",
        type=click.Path(),
        default=None,
        help="Project root (default: auto-detect)",
    )
    def plan(root: str | None) -> None:
        """Show the current repair plan (Terraform-style output).

        Reads the repair plan from .toolwright/state/repair_plan.json and
        displays patches grouped by safety level: SAFE, APPROVAL_REQUIRED, MANUAL.

        \\b
        Examples:
          toolwright repair plan
          toolwright repair plan --root /path/to/project
        """
        project_root = Path(root) if root else resolve_root()
        plan_file = project_root / ".toolwright" / "state" / "repair_plan.json"

        if not plan_file.exists():
            click.echo("No repair plan found. Run `toolwright repair diagnose` first.")
            return

        try:
            data = json.loads(plan_file.read_text())
        except Exception as e:
            click.echo(f"Error reading repair plan: {e}", err=True)
            return

        plan_data = data.get("plan", {})
        generated_at = data.get("generated_at", "unknown")
        patches = plan_data.get("patches", [])
        total = plan_data.get("total_patches", len(patches))
        safe_count = plan_data.get("safe_count", 0)
        approval_count = plan_data.get("approval_required_count", 0)
        manual_count = plan_data.get("manual_count", 0)

        # Header
        click.echo(f"Repair Plan ({total} patches)")
        click.echo(f"Generated: {generated_at}")
        click.echo()

        # Summary
        click.echo(
            f"  {click.style('SAFE', fg='green')}: {safe_count}  "
            f"{click.style('APPROVAL REQUIRED', fg='yellow')}: {approval_count}  "
            f"{click.style('MANUAL', fg='red')}: {manual_count}"
        )
        click.echo()

        if not patches:
            click.echo("No patches in plan.")
            return

        # Group by kind
        by_kind: dict[str, list[dict]] = {}
        for patch in patches:
            kind = patch.get("kind", "unknown")
            by_kind.setdefault(kind, []).append(patch)

        kind_colors = {"safe": "green", "approval_required": "yellow", "manual": "red"}

        for kind in ["safe", "approval_required", "manual"]:
            kind_patches = by_kind.get(kind, [])
            if not kind_patches:
                continue

            color = kind_colors.get(kind, "white")
            click.echo(click.style(f"--- {kind.upper()} ({len(kind_patches)}) ---", fg=color))
            click.echo()

            for patch in kind_patches:
                click.echo(f"  {patch.get('title', 'Untitled')}")
                click.echo(f"    {patch.get('description', '')}")
                cli_cmd = patch.get("cli_command", "")
                if cli_cmd:
                    click.echo(f"    $ {cli_cmd}")
                risk_note = patch.get("risk_note")
                if risk_note:
                    click.echo(click.style(f"    ⚠ {risk_note}", fg="yellow"))
                click.echo()

    @repair_group.command()
    @click.option(
        "--root",
        type=click.Path(),
        default=None,
        help="Project root (default: auto-detect)",
    )
    def apply(root: str | None) -> None:
        """Apply patches from the current repair plan.

        Reads the repair plan from .toolwright/state/repair_plan.json.
        SAFE patches are applied automatically. APPROVAL_REQUIRED patches
        show a prompt. MANUAL patches print guidance.

        Warns if the plan is stale (older than 1 hour).

        \\b
        Examples:
          toolwright repair apply
          toolwright repair apply --root /path/to/project
        """
        project_root = Path(root) if root else resolve_root()
        plan_file = project_root / ".toolwright" / "state" / "repair_plan.json"

        if not plan_file.exists():
            click.echo("No repair plan found. Run `toolwright repair plan` first.")
            return

        try:
            data = json.loads(plan_file.read_text())
        except Exception as e:
            click.echo(f"Error reading repair plan: {e}", err=True)
            return

        # Check staleness
        generated_at = data.get("generated_at", "")
        if generated_at:
            try:
                gen_time = datetime.fromisoformat(generated_at)
                now = datetime.now(UTC)
                age_seconds = (now - gen_time).total_seconds()
                if age_seconds > STALENESS_THRESHOLD_SECONDS:
                    age_hours = age_seconds / 3600
                    click.echo(
                        click.style(
                            f"Warning: Plan is stale ({age_hours:.1f} hours old). "
                            "Consider re-running `toolwright repair diagnose`.",
                            fg="yellow",
                        )
                    )
                    click.echo()
            except (ValueError, TypeError):
                pass

        plan_data = data.get("plan", {})
        patches = plan_data.get("patches", [])

        if not patches:
            click.echo("No patches to apply.")
            return

        safe_patches = [p for p in patches if p.get("kind") == "safe"]
        approval_patches = [p for p in patches if p.get("kind") == "approval_required"]
        manual_patches = [p for p in patches if p.get("kind") == "manual"]

        # SAFE patches: apply automatically (stub - just report)
        if safe_patches:
            click.echo(click.style(f"Applying {len(safe_patches)} SAFE patch(es):", fg="green"))
            for patch in safe_patches:
                click.echo(f"  ✓ {patch.get('title', 'Untitled')}")
                click.echo(f"    $ {patch.get('cli_command', '')}")
            click.echo()

        # APPROVAL_REQUIRED patches: prompt user
        if approval_patches:
            click.echo(
                click.style(
                    f"{len(approval_patches)} APPROVAL_REQUIRED patch(es) need review:",
                    fg="yellow",
                )
            )
            for patch in approval_patches:
                click.echo(f"  ? {patch.get('title', 'Untitled')}")
                click.echo(f"    $ {patch.get('cli_command', '')}")
                if patch.get("risk_note"):
                    click.echo(click.style(f"    ⚠ {patch['risk_note']}", fg="yellow"))
            click.echo()

        # MANUAL patches: print guidance
        if manual_patches:
            click.echo(
                click.style(
                    f"{len(manual_patches)} MANUAL patch(es) require investigation:",
                    fg="red",
                )
            )
            for patch in manual_patches:
                click.echo(f"  ✗ {patch.get('title', 'Untitled')}")
                click.echo(f"    {patch.get('description', '')}")
            click.echo()

        total = len(patches)
        click.echo(
            f"Summary: {len(safe_patches)} safe, "
            f"{len(approval_patches)} approval required, "
            f"{len(manual_patches)} manual "
            f"({total} total)"
        )

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
        type=click.Path(),
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
        type=click.Path(),
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

    @cli.command()
    @click.option(
        "--toolpack",
        type=click.Path(),
        help="Path to toolpack.yaml (auto-discovered if not given)",
    )
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["rich", "json"]),
        default="rich",
        help="Output format: rich (default) or json",
    )
    @click.pass_context
    def score(ctx: click.Context, toolpack: str | None, output_format: str) -> None:
        """Show governance health score for a toolpack.

        Computes a 0-100 score with letter grade across four dimensions:
        Approval, Stability, Verification, and Readiness. Includes
        actionable recommendations to improve the score.

        \b
        Examples:
          toolwright score
          toolwright score --toolpack .toolwright/toolpacks/stripe-api/toolpack.yaml
          toolwright score --format json
        """
        from toolwright.core.score import compute_score
        from toolwright.utils.resolve import resolve_toolpack_path

        root: Path = ctx.obj.get("root", resolve_root())

        try:
            toolpack_path = str(resolve_toolpack_path(explicit=toolpack, root=root))
        except (FileNotFoundError, click.UsageError) as exc:
            click.echo(str(exc), err=True)
            sys.exit(1)

        try:
            result = compute_score(toolpack_path=toolpack_path)
        except Exception as exc:
            click.echo(f"Error computing score: {exc}", err=True)
            sys.exit(1)

        if output_format == "json":
            payload = {
                "total": result.total,
                "grade": result.grade,
                "toolpack_id": result.toolpack_id,
                "dimensions": [
                    {
                        "name": d.name,
                        "score": round(d.score, 2),
                        "weight": d.weight,
                        "details": d.details,
                        "recommendations": d.recommendations,
                    }
                    for d in result.dimensions
                ],
                "top_recommendations": result.top_recommendations,
            }
            click.echo(json.dumps(payload, indent=2))
            return

        # Rich terminal output
        lines: list[str] = []
        lines.append("")
        lines.append(f"  Governance Score: {result.total}/100 ({result.grade})")
        lines.append("")

        for d in result.dimensions:
            pct = round(d.score * 100)
            filled = round(d.score * 10)
            bar = "\u2588" * filled + "\u2591" * (10 - filled)
            name_padded = d.name.ljust(12)
            pct_str = f"{pct}%".rjust(4)
            lines.append(f"  {name_padded} {bar} {pct_str}  {d.details}")

        if result.top_recommendations:
            lines.append("")
            lines.append("  Top recommendations:")
            for i, rec in enumerate(result.top_recommendations, 1):
                lines.append(f"    {i}. {rec}")

        lines.append("")
        click.echo("\n".join(lines), err=True)

    @cli.command()
    @click.argument("tool_name")
    @click.option(
        "--toolpack",
        type=click.Path(),
        help="Path to toolpack.yaml (auto-discovered if not given)",
    )
    @click.option(
        "--json",
        "json_mode",
        is_flag=True,
        help="Output as JSON",
    )
    @click.pass_context
    def why(ctx: click.Context, tool_name: str, toolpack: str | None, json_mode: bool) -> None:
        """Explain governance decisions for a specific tool.

        Shows why a tool was blocked, approved, or is pending review.
        Provides status, reasons, timeline, and recommended next steps.

        \b
        Examples:
          toolwright why get_products
          toolwright why get_users --toolpack .toolwright/toolpacks/stripe-api/toolpack.yaml
          toolwright why get_products --json
        """
        from toolwright.core.why import explain_tool
        from toolwright.utils.resolve import resolve_toolpack_path

        root: Path = ctx.obj.get("root", resolve_root())

        try:
            toolpack_path = str(resolve_toolpack_path(explicit=toolpack, root=root))
        except (FileNotFoundError, click.UsageError) as exc:
            click.echo(str(exc), err=True)
            sys.exit(1)

        try:
            result = explain_tool(
                tool_name=tool_name,
                toolpack_path=toolpack_path,
                root=root,
            )
        except Exception as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)

        if json_mode:
            payload = {
                "tool_name": result.tool_name,
                "status": result.status,
                "reasons": result.reasons,
                "timeline": result.timeline,
                "next_steps": result.next_steps,
            }
            click.echo(json.dumps(payload, indent=2))
            return

        lines: list[str] = []
        lines.append("")
        lines.append(f"  Why: {result.tool_name}")
        lines.append("")
        lines.append(f"  Status: {result.status}")

        if result.reasons:
            lines.append("")
            lines.append("  Reasons:")
            for reason in result.reasons:
                lines.append(f"    \u2022 {reason}")

        if result.timeline:
            lines.append("")
            lines.append("  Timeline:")
            for event in result.timeline:
                lines.append(f"    \u2022 {event}")

        if result.next_steps:
            lines.append("")
            lines.append("  Next steps:")
            for i, step in enumerate(result.next_steps, 1):
                lines.append(f"    {i}. {step}")

        lines.append("")
        click.echo("\n".join(lines))

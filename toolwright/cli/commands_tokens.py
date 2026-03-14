"""CLI command registration for ``toolwright estimate-tokens``."""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING

import click

from toolwright.cli.command_helpers import cli_root

if TYPE_CHECKING:
    from toolwright.core.token_estimator import TokenEstimator


def register_tokens_commands(*, cli: click.Group) -> None:
    """Register the estimate-tokens command on the top-level CLI group."""

    @cli.command("estimate-tokens")
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        default=None,
        help="Path to toolpack.yaml (auto-resolves if omitted)",
    )
    @click.pass_context
    def estimate_tokens(ctx: click.Context, toolpack: str | None) -> None:
        """Show token consumption estimates per transport mode.

        Compares MCP, CLI, and REST transports to help choose the most
        token-efficient way to expose your toolpack to AI agents.

        \\b
        Examples:
          toolwright estimate-tokens
          toolwright estimate-tokens --toolpack ./my-api/toolpack.yaml
        """
        from toolwright.core.token_estimator import TokenEstimator
        from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths
        from toolwright.utils.resolve import resolve_toolpack_path

        # Resolve toolpack
        try:
            tp_path = resolve_toolpack_path(explicit=toolpack, root=cli_root(ctx))
        except (FileNotFoundError, click.UsageError) as e:
            click.echo(f"Error: {e}", err=True)
            ctx.exit(1)
            return

        tp = load_toolpack(tp_path)
        resolved = resolve_toolpack_paths(toolpack=tp, toolpack_path=tp_path)

        # Load tools.json
        if not resolved.tools_path.exists():
            click.echo(
                f"Error: tools manifest not found: {resolved.tools_path}",
                err=True,
            )
            ctx.exit(1)
            return

        try:
            manifest = json.loads(resolved.tools_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            click.echo(f"Error reading tools manifest: {e}", err=True)
            ctx.exit(1)
            return

        # Optionally load groups.json
        groups_data = None
        if resolved.groups_path and resolved.groups_path.exists():
            with contextlib.suppress(json.JSONDecodeError, OSError):
                groups_data = json.loads(resolved.groups_path.read_text())

        # Override name from toolpack display name
        display_name = tp.display_name or tp.toolpack_id
        if display_name:
            manifest.setdefault("name", display_name)

        estimator = TokenEstimator.from_manifest(manifest, groups_data=groups_data)

        # Render output
        _render_estimate(estimator)

    return estimate_tokens


def _render_estimate(estimator: TokenEstimator) -> None:
    """Render the token estimate table to stdout."""

    estimates = estimator.estimates()

    # Header
    cat_parts = []
    for cat in ("read", "write", "admin"):
        count = estimator.categories.get(cat, 0)
        if count:
            cat_parts.append(f"{count} {cat}")
    cat_str = f" ({', '.join(cat_parts)})" if cat_parts else ""

    click.echo()
    click.echo(f"  Token Budget Estimate for {estimator.name}")
    click.echo()
    click.echo(f"  Tools: {estimator.tool_count}{cat_str}")
    click.echo()

    # Table header
    hdr = f"  {'Transport':<18}{'Tokens/call':>13}   {'Context overhead':>18}   {'Total estimate':>16}"
    click.echo(hdr)
    click.echo("  " + "\u2500" * (len(hdr) - 2))

    for e in estimates:
        label = e.transport
        per_tool = f"~{e.tokens_per_tool}/tool"

        # Context detail
        if "scoped" in label.lower() and estimator._largest_group_size is not None:
            ctx_str = f"~{e.context_overhead:,} ({estimator._largest_group_size} tools)"
        else:
            ctx_str = f"~{e.context_overhead:,}"

        total_str = f"~{e.total:,}"
        click.echo(f"  {label:<18}{per_tool:>13}   {ctx_str:>18}   {total_str:>16}")

    # Recommendations
    recs = estimator.recommendations()
    if recs:
        click.echo()
        click.echo("  Recommendations:")
        for rec in recs:
            click.echo(f"    \u2022 {rec}")

    click.echo()

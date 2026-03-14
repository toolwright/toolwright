"""Packaging, installation, and client-config command registration."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import click

from toolwright.cli.command_helpers import cli_root


def register_packaging_commands(
    *,
    cli: click.Group,
    run_with_lock: Callable[..., None],
) -> None:
    """Register packaging and setup commands."""

    @cli.command(
        epilog="""\b
Examples:
  toolwright config --toolpack toolpack.yaml
  toolwright config --toolpack toolpack.yaml --format yaml
  toolwright config --toolpack toolpack.yaml --name my-api
  toolwright config --toolpack toolpack.yaml --format codex
""",
    )
    @click.option(
        "--toolpack",
        type=click.Path(),
        help="Path to toolpack.yaml (auto-resolved if not given)",
    )
    @click.option(
        "--name",
        help="Override the MCP server name (defaults to toolpack_id)",
    )
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["json", "yaml", "codex"]),
        default="json",
        show_default=True,
        help="Output format for config snippet",
    )
    @click.option(
        "--command",
        "command_override",
        default=None,
        help="Override the toolwright command path (default: 'toolwright')",
    )
    @click.pass_context
    def config(
        ctx: click.Context,
        toolpack: str | None,
        name: str | None,
        output_format: str,
        command_override: str | None,
    ) -> None:
        """Print a ready-to-paste MCP client config snippet (Claude, Cursor, Codex)."""
        from toolwright.cli.config import run_config
        from toolwright.utils.resolve import resolve_toolpack_path

        resolved = str(resolve_toolpack_path(explicit=toolpack, root=cli_root(ctx)))
        run_config(
            toolpack_path=resolved,
            fmt=output_format,
            name_override=name,
            command_override=command_override,
        )

    @cli.command()
    @click.argument("toolpack_path", type=click.Path(exists=True))
    @click.option(
        "--output",
        "-o",
        type=click.Path(),
        default=None,
        help="Output directory for .twp bundle",
    )
    def share(toolpack_path: str, output: str | None) -> None:
        """Package a toolpack into a signed .twp bundle for sharing."""
        from toolwright.core.share.bundler import create_bundle

        toolpack_dir = Path(toolpack_path)
        output_dir = Path(output) if output else None
        result_path = create_bundle(toolpack_dir, output_dir=output_dir)
        size = result_path.stat().st_size
        size_human = (
            f"{size / 1024:.1f} KB"
            if size < 1024 * 1024
            else f"{size / (1024 * 1024):.1f} MB"
        )
        click.echo(f"Created {result_path} ({size_human})")

    @cli.command("install")
    @click.argument("bundle_path", type=click.Path(exists=True))
    @click.option(
        "--target",
        "-t",
        type=click.Path(),
        default=None,
        help="Target installation directory",
    )
    def install_cmd(bundle_path: str, target: str | None) -> None:
        """Verify and install a .twp toolpack bundle."""
        from toolwright.core.share.installer import install_bundle

        twp_path = Path(bundle_path)
        install_dir = Path(target) if target else Path(".toolwright/toolpacks") / twp_path.stem
        result = install_bundle(twp_path, install_dir=install_dir)
        if result.verified:
            click.echo(f"Installed '{result.name}' to {install_dir}")
            if result.files:
                click.echo(f"  Files: {len(result.files)}")
        else:
            click.echo("Error: Bundle verification failed.", err=True)
            raise SystemExit(1)

    @cli.command(hidden=True)
    @click.option(
        "--toolpack",
        required=True,
        type=click.Path(),
        help="Path to toolpack.yaml",
    )
    @click.option(
        "--out",
        "output",
        required=True,
        type=click.Path(),
        help="Output bundle zip path",
    )
    @click.pass_context
    def bundle(ctx: click.Context, toolpack: str, output: str) -> None:
        """Create a deterministic toolpack bundle."""
        from toolwright.cli.bundle import run_bundle

        run_bundle(
            toolpack_path=toolpack,
            output_path=output,
            verbose=ctx.obj.get("verbose", False),
        )

    @cli.command(hidden=True)
    @click.option(
        "--toolpack",
        required=True,
        type=click.Path(),
        help="Path to toolpack.yaml",
    )
    @click.option(
        "--apply/--dry-run",
        "apply_changes",
        default=False,
        show_default=True,
        help="Apply migrations or print planned changes",
    )
    @click.pass_context
    def migrate(ctx: click.Context, toolpack: str, apply_changes: bool) -> None:
        """Migrate legacy toolpack/artifact layouts to current schema contracts."""
        from toolwright.cli.migrate import run_migrate

        run_with_lock(
            ctx,
            "migrate",
            lambda: run_migrate(
                toolpack_path=toolpack,
                apply_changes=apply_changes,
                verbose=ctx.obj.get("verbose", False),
            ),
        )

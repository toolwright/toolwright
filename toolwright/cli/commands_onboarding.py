"""Onboarding and project-management command registration."""

from __future__ import annotations

from pathlib import Path

import click
import yaml

from toolwright.utils.state import resolve_root


def register_onboarding_commands(*, cli: click.Group) -> None:
    """Register onboarding-oriented top-level commands."""

    @cli.command()
    @click.argument("url", required=False, default=None)
    @click.option(
        "-a", "--allowed-host",
        multiple=True,
        help="API host(s) to capture (used with URL argument)",
    )
    @click.pass_context
    def ship(ctx: click.Context, url: str | None, allowed_host: tuple[str, ...]) -> None:
        """Ship a governed agent end-to-end.

        The flagship guided lifecycle: capture, review, approve, snapshot,
        verify, and serve — all in one flow.

        Optionally pass a URL to run the automated path (capture + compile +
        smart approve + serve). Without a URL, runs the interactive flow.

        \b
        Examples:
          toolwright ship                                      # Interactive
          toolwright ship https://app.example.com -a api.example.com  # Automated
        """
        from toolwright.ui.flows.ship import ship_secure_agent_flow

        root: Path = ctx.obj.get("root", resolve_root())
        no_interactive = ctx.obj.get("no_interactive_explicit", False) if ctx.obj else False

        if no_interactive and not url:
            raise click.ClickException(
                "In non-interactive mode, a URL argument is required. "
                "Usage: toolwright --no-interactive ship <URL> -a <host>"
            )

        ship_secure_agent_flow(
            root=root,
            verbose=ctx.obj.get("verbose", False),
            url=url,
            allowed_hosts=list(allowed_host) if allowed_host else None,
        )

    @cli.command("init")
    @click.option(
        "--directory", "-d",
        default=".",
        help="Project directory to initialize (default: current directory)",
    )
    @click.pass_context
    def init_cmd(ctx: click.Context, directory: str) -> None:
        """Initialize toolwright in a project directory.

        Auto-detects project type, generates config, and prints next steps.
        """
        from toolwright.cli.init import run_init

        run_init(
            directory=directory,
            verbose=ctx.obj.get("verbose", False) if ctx.obj else False,
        )

    @cli.command("rename")
    @click.argument("new_name")
    @click.option(
        "--toolpack",
        type=click.Path(),
        help="Path to toolpack.yaml (auto-discovered if not given)",
    )
    @click.pass_context
    def rename_cmd(ctx: click.Context, new_name: str, toolpack: str | None) -> None:
        """Rename a toolpack's display name.

        Updates only the display_name field in toolpack.yaml.
        Does not change toolpack_id, tool IDs, lockfile, or signatures.

        \b
        Examples:
          toolwright rename my-stripe-api
          toolwright rename production-api --toolpack .toolwright/toolpacks/api/toolpack.yaml
        """
        if not new_name.strip():
            click.echo("Error: display name cannot be empty.", err=True)
            ctx.exit(1)
            return

        root = ctx.obj["root"] if ctx.obj else Path(".")

        from toolwright.utils.resolve import resolve_toolpack_path

        try:
            resolved_toolpack = str(resolve_toolpack_path(explicit=toolpack, root=root))
        except (FileNotFoundError, click.UsageError) as exc:
            click.echo(str(exc), err=True)
            ctx.exit(1)
            return

        toolpack_path = Path(resolved_toolpack)

        raw = yaml.safe_load(toolpack_path.read_text())
        old_name = raw.get("display_name") or raw.get("toolpack_id", "unnamed")
        raw["display_name"] = new_name
        toolpack_path.write_text(yaml.dump(raw, default_flow_style=False, sort_keys=False))

        click.echo(f"Renamed: {old_name} → {new_name}")

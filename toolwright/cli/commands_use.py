"""The 'use' command — set/clear default toolpack."""

from __future__ import annotations

from pathlib import Path

import click

from toolwright.utils.state import resolve_root


def register_use_command(*, cli: click.Group) -> None:
    """Register the 'use' command on the provided CLI group."""

    @cli.command()
    @click.argument("name", required=False)
    @click.option(
        "--clear",
        is_flag=True,
        help="Clear the default toolpack setting",
    )
    @click.pass_context
    def use(ctx: click.Context, name: str | None, clear: bool) -> None:
        """Set the default toolpack for this project.

        When a default is set, --toolpack can be omitted from all commands.
        The NAME argument is the toolpack directory name under .toolwright/toolpacks/.

        \b
        Examples:
          toolwright use stripe         # Set default to the 'stripe' toolpack
          toolwright use github         # Switch default to 'github'
          toolwright use --clear        # Remove the default setting
        """
        from toolwright.utils.config_file import load_config, save_config

        root: Path = ctx.obj.get("root", resolve_root())

        if clear:
            cfg = load_config(root)
            cfg.pop("default_toolpack", None)
            save_config(root, cfg)
            click.echo("Default toolpack cleared.")
            return

        if not name:
            # Show current default
            cfg = load_config(root)
            current = cfg.get("default_toolpack")
            if current:
                click.echo(f"Default toolpack: {current}")
            else:
                click.echo("No default toolpack set. Usage: toolwright use <name>")
            return

        # Validate the toolpack exists
        tp_dir = root / "toolpacks" / name
        tp_file = tp_dir / "toolpack.yaml"
        if not tp_file.exists():
            # List available toolpacks
            toolpacks_dir = root / "toolpacks"
            available: list[str] = []
            if toolpacks_dir.is_dir():
                available = sorted(
                    d.name
                    for d in toolpacks_dir.iterdir()
                    if d.is_dir() and (d / "toolpack.yaml").exists()
                )

            msg = f"Toolpack '{name}' not found in {toolpacks_dir}."
            if available:
                msg += "\n\nAvailable toolpacks:\n" + "\n".join(
                    f"  {n}" for n in available
                )
            click.echo(msg, err=True)
            ctx.exit(1)
            return

        cfg = load_config(root)
        cfg["default_toolpack"] = name
        save_config(root, cfg)
        click.echo(f"Default toolpack set to: {name}")

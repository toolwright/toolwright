"""Main CLI entry point for Toolwright."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import click

from toolwright import __version__
from toolwright.branding import (
    CLI_PRIMARY_COMMAND,
    PRODUCT_NAME,
)
from toolwright.cli.commands_approval import register_approval_commands
from toolwright.cli.commands_auth import register_auth_commands
from toolwright.cli.commands_build import register_build_commands
from toolwright.cli.commands_create import register_create_commands
from toolwright.cli.commands_governance import register_governance_commands
from toolwright.cli.commands_groups import register_groups_commands
from toolwright.cli.commands_kill import register_kill_commands
from toolwright.cli.commands_mcp import register_mcp_commands
from toolwright.cli.commands_onboarding import register_onboarding_commands
from toolwright.cli.commands_packaging import register_packaging_commands
from toolwright.cli.commands_recipes import register_recipes_commands
from toolwright.cli.commands_repair import register_repair_commands
from toolwright.cli.commands_rules import register_rules_commands
from toolwright.cli.commands_runtime import register_runtime_commands
from toolwright.cli.commands_snapshots import register_snapshot_commands
from toolwright.cli.commands_status import register_status_commands
from toolwright.cli.commands_tokens import register_tokens_commands
from toolwright.cli.commands_use import register_use_command
from toolwright.cli.commands_validation import register_validation_commands
from toolwright.cli.commands_watch import register_watch_commands
from toolwright.utils.locks import RootLockError, root_command_lock
from toolwright.utils.state import resolve_root

# Commands visible only with --help-all.
ADVANCED_COMMANDS = {
    "compile",
    "bundle",
    "lint",
    "doctor",
    "enforce",
    "migrate",
    "inspect",
    "confirm",
    "propose",
    "scope",
    "state",
    "run",
    "ship",
    "init",
    "demo",
    "rename",
    "use",
    "snapshots",
    "rollback",
    "share",
    "install",
    "capture",
    "wrap",
}

# Operations commands shown after core in default help.
OPERATIONS_COMMANDS = [
    "drift",
    "diff",
    "repair",
    "verify",
    "health",
    "auth",
    "kill",
    "enable",
    "quarantine",
    "watch",
    "recipes",
    "dashboard",
]

# Core commands shown prominently in default help, in workflow order.
CORE_COMMANDS = [
    "create",
    "mint",
    "serve",
    "gate",
    "status",
    "rules",
    "groups",
    "config",
]


class ToolwrightGroup(click.Group):
    """Custom group with sectioned help output and interactive flow dispatch."""

    def invoke(self, ctx: click.Context) -> None:
        """Override invoke to intercept MissingParameter for allowlisted commands."""
        try:
            super().invoke(ctx)
        except click.MissingParameter as exc:
            from toolwright.ui.flows import INTERACTIVE_COMMANDS

            cmd_name = ctx.invoked_subcommand
            if ctx.obj and ctx.obj.get("interactive") and cmd_name in INTERACTIVE_COMMANDS:
                flow = INTERACTIVE_COMMANDS[cmd_name]
                hint = exc.param_hint
                param_str: str | None = None
                if isinstance(hint, str):
                    param_str = hint
                elif hint:
                    param_str = ", ".join(hint)
                flow(ctx=ctx, missing_param=param_str)
                return
            raise

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Write command sections: Quick Start, Operations, Advanced hint."""
        commands = []
        for subcommand in self.list_commands(ctx):
            cmd = self.commands.get(subcommand)
            if cmd is None or cmd.hidden:
                continue
            help_text = cmd.get_short_help_str(limit=150)
            commands.append((subcommand, help_text))

        if not commands:
            return

        cmd_map = dict(commands)

        core = [(n, cmd_map[n]) for n in CORE_COMMANDS if n in cmd_map]
        ops = [(n, cmd_map[n]) for n in OPERATIONS_COMMANDS if n in cmd_map]

        if core:
            with formatter.section("Quick Start"):
                formatter.write_dl(core)
        if ops:
            with formatter.section("Operations"):
                formatter.write_dl(ops)

        formatter.write("\n")
        formatter.write("  Use 'toolwright <command> --help' for details on any command.\n")
        formatter.write("  Use 'toolwright --help-all' to see all commands including advanced.\n")


def _render_help_all(ctx: click.Context) -> str:
    """Render top-level help including hidden advanced commands."""
    command = ctx.command
    if not isinstance(command, click.Group):
        return ctx.get_help()

    formatter = ctx.make_formatter()
    command.format_usage(ctx, formatter)
    command.format_help_text(ctx, formatter)
    command.format_options(ctx, formatter)
    with formatter.section("All Commands"):
        formatter.write_dl(
            [
                (name, command.commands[name].get_short_help_str())
                for name in sorted(command.commands)
            ]
        )
    return formatter.getvalue().rstrip("\n")


def _show_help_all(
    ctx: click.Context,
    _param: click.Parameter,
    value: bool,
) -> None:
    """Eager callback for --help-all."""
    if not value or ctx.resilient_parsing:
        return
    click.echo(_render_help_all(ctx))
    ctx.exit()


@click.group(cls=ToolwrightGroup, invoke_without_command=True)
@click.version_option(version=__version__, prog_name=CLI_PRIMARY_COMMAND)
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose output")
@click.option(
    "--help-all",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_show_help_all,
    help="Show help including advanced commands",
)
@click.option(
    "--root",
    type=click.Path(file_okay=False, path_type=Path),
    default=resolve_root(),
    show_default=True,
    help="Canonical state root for captures, artifacts, reports, and locks",
)
@click.option(
    "--no-interactive",
    is_flag=True,
    envvar="TOOLWRIGHT_NON_INTERACTIVE",
    help="Disable interactive prompts (same as TOOLWRIGHT_NON_INTERACTIVE=1)",
)
@click.pass_context
def cli(ctx: click.Context, verbose: bool, root: Path, no_interactive: bool) -> None:
    """Trusted MCP supply chain for AI tools with fail-closed runtime and bounded self-healing."""
    from toolwright.ui.policy import should_interact

    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["root"] = root
    ctx.obj["brand"] = {
        "product": PRODUCT_NAME,
        "primary_command": CLI_PRIMARY_COMMAND,
    }
    ctx.obj["interactive"] = should_interact(
        force=False if no_interactive else None,
    )

    if ctx.invoked_subcommand is None:
        if ctx.obj["interactive"]:
            from toolwright.ui.flows.quickstart import wizard_flow

            wizard_flow(root=root, verbose=verbose)
        else:
            click.echo(ctx.get_help())


def _run_with_lock(
    ctx: click.Context,
    command: str,
    callback: Callable[[], None],
    *,
    lock_id: str | None = None,
) -> None:

    try:
        with root_command_lock(
            ctx.obj.get("root", resolve_root()),
            command,
            lock_id=lock_id,
        ):
            callback()
    except RootLockError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Register top-level command groups
# ---------------------------------------------------------------------------

register_mcp_commands(cli=cli)
register_approval_commands(cli=cli, run_with_lock=_run_with_lock)
register_runtime_commands(cli=cli, run_with_lock=_run_with_lock)
register_build_commands(cli=cli, run_with_lock=_run_with_lock)
register_use_command(cli=cli)
register_rules_commands(cli=cli)
register_kill_commands(cli=cli)
register_watch_commands(cli=cli)
register_snapshot_commands(cli=cli)
register_groups_commands(cli=cli)
register_recipes_commands(cli=cli)
register_create_commands(cli=cli, run_with_lock=_run_with_lock)
register_packaging_commands(cli=cli, run_with_lock=_run_with_lock)
register_status_commands(cli=cli)
register_onboarding_commands(cli=cli)
register_auth_commands(cli=cli)
register_validation_commands(cli=cli, run_with_lock=_run_with_lock)
register_repair_commands(cli=cli)
register_governance_commands(cli=cli, run_with_lock=_run_with_lock)
register_tokens_commands(cli=cli)

# Register wrap (overlay) command
from toolwright.cli.commands_wrap import wrap_command as _wrap_cmd  # noqa: E402

cli.add_command(_wrap_cmd, "wrap")

# Register drift status subcommand
from toolwright.cli.drift import drift_status as _drift_status_cmd  # noqa: E402

cli.add_command(_drift_status_cmd, "drift-status")


# ---------------------------------------------------------------------------
# Advanced / Hidden Commands
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()

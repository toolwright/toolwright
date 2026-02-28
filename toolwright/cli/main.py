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
from toolwright.cli.commands_auth import register_auth_check_command
from toolwright.cli.commands_kill import register_kill_commands
from toolwright.cli.commands_mcp import register_mcp_commands
from toolwright.cli.commands_repair import register_repair_plan_apply
from toolwright.cli.commands_rules import register_rules_commands
from toolwright.cli.commands_snapshots import register_snapshot_commands
from toolwright.cli.commands_use import register_use_command
from toolwright.cli.commands_watch import register_watch_commands
from toolwright.cli.commands_workflow import register_workflow_commands
from toolwright.utils.locks import RootLockError, clear_root_lock, root_command_lock
from toolwright.utils.state import confirmation_store_path, resolve_root

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
    "compliance",
    "state",
}

# Commands shown in the "More" section of default help.
MORE_COMMANDS = {
    "capture",
    "workflow",
    "auth",
}

# Core commands shown prominently in default help, in workflow order.
CORE_COMMANDS = [
    "status",
    "ship",
    "init",
    "mint",
    "gate",
    "serve",
    "config",
    "verify",
    "drift",
    "repair",
    "diff",
    "dashboard",
    "rules",
    "kill",
    "enable",
    "quarantine",
    "health",
    "run",
    "use",
    "demo",
    "rename",
    "watch",
    "snapshots",
    "rollback",
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
        """Write command sections: Core, More."""
        commands = []
        for subcommand in self.list_commands(ctx):
            cmd = self.commands.get(subcommand)
            if cmd is None or cmd.hidden:
                continue
            help_text = cmd.get_short_help_str(limit=150)
            commands.append((subcommand, help_text))

        if not commands:
            return

        core = [(n, h) for n, h in commands if n in CORE_COMMANDS]
        more = [(n, h) for n, h in commands if n in MORE_COMMANDS]

        # Sort core commands in workflow order.
        core_order = list(CORE_COMMANDS)
        core.sort(key=lambda x: core_order.index(x[0]) if x[0] in core_order else 99)
        more.sort()

        if core:
            with formatter.section("Core Commands"):
                formatter.write_dl(core)
        if more:
            with formatter.section("Advanced"):
                formatter.write_dl(more)

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
    """Turn observed web/API traffic into safe, versioned, agent-ready MCP tools."""
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
    import json as _json

    from toolwright.ui.ops import get_status
    from toolwright.ui.views.branding import render_plain_header, render_rich_header
    from toolwright.ui.views.status import render_json, render_plain, render_rich

    root: Path = ctx.obj.get("root", resolve_root())

    # Resolve toolpack path via resolution chain
    from toolwright.utils.resolve import resolve_toolpack_path

    try:
        toolpack_path = str(resolve_toolpack_path(explicit=toolpack, root=root))
    except (FileNotFoundError, click.UsageError) as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    # Get status data
    try:
        model = get_status(toolpack_path)
    except Exception as exc:
        click.echo(f"Error reading toolpack: {exc}", err=True)
        sys.exit(1)

    # Render
    if json_mode:
        click.echo(_json.dumps(render_json(model), indent=2))
        return

    # Detect output mode
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
    and recommended next actions.  Requires toolwright[tui] (Textual).

    \b
    Examples:
      toolwright dashboard
      toolwright dashboard --toolpack .toolwright/toolpacks/stripe-api/toolpack.yaml
    """
    from toolwright.ui.dashboard import run_dashboard

    root: Path = ctx.obj.get("root", resolve_root())

    from toolwright.utils.resolve import resolve_toolpack_path

    try:
        toolpack_path = str(resolve_toolpack_path(explicit=toolpack, root=root))
    except (FileNotFoundError, click.UsageError) as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    run_dashboard(toolpack_path=toolpack_path, root=str(root))


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
    ship_secure_agent_flow(
        root=root,
        verbose=ctx.obj.get("verbose", False),
        url=url,
        allowed_hosts=list(allowed_host) if allowed_host else None,
    )


def _default_root_path(ctx: click.Context, *parts: str) -> Path:
    root = ctx.obj.get("root", resolve_root())
    return Path(root, *parts)


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
# Core Commands
# ---------------------------------------------------------------------------


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
    type=click.Path(exists=True),
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
    import yaml as _yaml

    if not new_name.strip():
        click.echo("Error: display name cannot be empty.", err=True)
        ctx.exit(1)
        return

    root = ctx.obj["root"] if ctx.obj else Path(".")

    from toolwright.utils.resolve import resolve_toolpack_path

    try:
        toolpack = str(resolve_toolpack_path(explicit=toolpack, root=root))
    except (FileNotFoundError, click.UsageError) as exc:
        click.echo(str(exc), err=True)
        ctx.exit(1)
        return

    tp_path = Path(toolpack)

    # Read, update, write
    raw = _yaml.safe_load(tp_path.read_text())
    old_name = raw.get("display_name") or raw.get("toolpack_id", "unnamed")
    raw["display_name"] = new_name
    tp_path.write_text(_yaml.dump(raw, default_flow_style=False, sort_keys=False))

    click.echo(f"Renamed: {old_name} → {new_name}")

@cli.command()
@click.argument("subcommand", type=click.Choice(["import", "record"]))
@click.argument("source", required=False)
@click.option(
    "--allowed-hosts",
    "-a",
    multiple=True,
    help="API hosts to include (required, repeatable). Use the domain of your API, e.g. -a api.example.com",
)
@click.option("--name", "-n", help="Name for the capture session")
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Capture output directory (defaults to <root>/captures)",
)
@click.option(
    "--input-format",
    type=click.Choice(["har", "otel", "openapi"]),
    default="har",
    show_default=True,
    help="Input format for import mode (auto-detected for OpenAPI specs)",
)
@click.option("--no-redact", is_flag=True, help="Disable redaction (not recommended)")
@click.option(
    "--headless/--no-headless",
    default=False,
    show_default=True,
    help="Run Playwright browser headless in record mode",
)
@click.option(
    "--script",
    type=click.Path(exists=True),
    help="Python script with async run(page, context) for scripted capture",
)
@click.option(
    "--duration",
    type=int,
    default=30,
    show_default=True,
    help="Capture duration in seconds for non-interactive/headless mode",
)
@click.option(
    "--load-storage-state",
    type=click.Path(exists=True),
    help="Load browser storage state (cookies, localStorage) from a JSON file",
)
@click.option(
    "--save-storage-state",
    type=click.Path(),
    help="Save browser storage state to a JSON file after capture",
)
@click.pass_context
def capture(
    ctx: click.Context,
    subcommand: str,
    source: str | None,
    allowed_hosts: tuple[str, ...],
    name: str | None,
    output: str | None,
    input_format: str,
    no_redact: bool,
    headless: bool,
    script: str | None,
    duration: int,
    load_storage_state: str | None,
    save_storage_state: str | None,
) -> None:
    """Import traffic from HAR/OTEL/OpenAPI files or capture with Playwright.

    For 'import': SOURCE is the path to a HAR, OTEL, or OpenAPI file.
    For 'record': SOURCE is the starting URL for browser capture.

    \b
    Examples:
      # Import a HAR file
      toolwright capture import traffic.har -a api.example.com

      # Import an OpenAPI spec
      toolwright capture import openapi.yaml -a api.example.com

      # Import OpenTelemetry traces
      toolwright capture import traces.json --input-format otel -a api.example.com

      # Record traffic interactively with Playwright
      toolwright capture record https://example.com -a api.example.com

    Record mode supports interactive, timed headless, and scripted automation.
    """
    if not allowed_hosts:
        click.echo(
            "Error: --allowed-hosts / -a is required.\n\n"
            "This tells toolwright which API hosts to capture. Use the domain of your API server.\n\n"
            "Examples:\n"
            "  toolwright capture import traffic.har -a api.example.com\n"
            "  toolwright capture record https://app.example.com -a api.example.com\n"
            "  toolwright capture import spec.yaml -a api.example.com -a auth.example.com\n\n"
            "Tip: check your HAR/spec file for the API hostname.",
            err=True,
        )
        sys.exit(2)

    resolved_output = output or str(_default_root_path(ctx, "captures"))

    # Auto-detect OpenAPI for import subcommand.
    effective_format = input_format
    if subcommand == "import" and source and input_format == "har":
        effective_format = _detect_openapi_format(source, input_format)

    if effective_format == "openapi":
        from toolwright.cli.capture import run_capture_openapi

        _run_with_lock(
            ctx,
            "capture",
            lambda: run_capture_openapi(
                source=source or "",
                allowed_hosts=list(allowed_hosts) if allowed_hosts else None,
                name=name,
                output=resolved_output,
                verbose=ctx.obj.get("verbose", False),
                root_path=str(ctx.obj.get("root", resolve_root())),
            ),
        )
        return

    from toolwright.cli.capture import run_capture

    _run_with_lock(
        ctx,
        "capture",
        lambda: run_capture(
            subcommand=subcommand,
            source=source,
            input_format=effective_format,
            allowed_hosts=list(allowed_hosts),
            name=name,
            output=resolved_output,
            redact=not no_redact,
            headless=headless,
            script_path=script,
            duration_seconds=duration,
            load_storage_state=load_storage_state,
            save_storage_state=save_storage_state,
            verbose=ctx.obj.get("verbose", False),
            root_path=str(ctx.obj.get("root", resolve_root())),
        ),
    )


def _detect_openapi_format(source: str, default: str) -> str:
    """Detect if a source file is an OpenAPI spec."""
    import json as _json

    import yaml as _yaml

    source_path = Path(source)
    if not source_path.exists():
        return default
    try:
        text = source_path.read_text(encoding="utf-8")
        if source_path.suffix in {".yaml", ".yml"}:
            data = _yaml.safe_load(text)
        elif source_path.suffix == ".json":
            data = _json.loads(text)
        else:
            return default
        if isinstance(data, dict) and "openapi" in data:
            return "openapi"
    except Exception:
        pass
    return default


@cli.command()
@click.argument("start_url")
@click.option(
    "--allowed-hosts",
    "-a",
    multiple=True,
    required=True,
    help="Hosts to include (required, repeatable)",
)
@click.option("--name", "-n", help="Optional toolpack/session name")
@click.option(
    "--scope",
    "-s",
    default="first_party_only",
    show_default=True,
    help="Scope to apply during compile",
)
@click.option(
    "--headless/--no-headless",
    default=True,
    show_default=True,
    help="Run browser headless during capture",
)
@click.option(
    "--script",
    type=click.Path(exists=True),
    help="Python script with async run(page, context) for scripted capture",
)
@click.option(
    "--duration",
    type=int,
    default=30,
    show_default=True,
    help="Capture duration in seconds when no script is provided",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output root directory (defaults to --root)",
)
@click.option(
    "--deterministic/--volatile-metadata",
    default=True,
    show_default=True,
    help="Deterministic metadata by default; use --volatile-metadata for ephemeral IDs/timestamps",
)
@click.option(
    "--runtime",
    type=click.Choice(["local", "container"]),
    default="local",
    show_default=True,
    help="Runtime mode metadata/emission (container emits runtime files)",
)
@click.option(
    "--runtime-build",
    is_flag=True,
    help="Build container image after emitting runtime files (requires Docker)",
)
@click.option(
    "--runtime-tag",
    help="Container image tag to use when --runtime=container",
)
@click.option(
    "--runtime-version-pin",
    help="Exact requirement line for toolwright runtime when --runtime=container",
)
@click.option(
    "--print-mcp-config",
    is_flag=True,
    help="Print a ready-to-paste Claude Desktop MCP config snippet",
)
@click.option(
    "--auth-profile",
    default=None,
    help="Auth profile name to use for authenticated capture",
)
@click.option(
    "--webmcp",
    is_flag=True,
    default=False,
    help="Discover WebMCP tools (navigator.modelContext) on the target page",
)
@click.option(
    "--redaction-profile",
    type=click.Choice(["default_safe", "high_risk_pii"]),
    default=None,
    help="Redaction profile to apply during capture (default: built-in patterns)",
)
@click.pass_context
def mint(
    ctx: click.Context,
    start_url: str,
    allowed_hosts: tuple[str, ...],
    name: str | None,
    scope: str,
    headless: bool,
    script: str | None,
    duration: int,
    output: str | None,
    deterministic: bool,
    runtime: str,
    runtime_build: bool,
    runtime_tag: str | None,
    runtime_version_pin: str | None,
    print_mcp_config: bool,
    auth_profile: str | None,
    webmcp: bool,
    redaction_profile: str | None,
) -> None:
    """Capture traffic and compile a governed toolpack.

    \b
    Example:
      toolwright mint https://example.com -a api.example.com --print-mcp-config
      toolwright mint https://app.example.com -a api.example.com --auth-profile myapp
      toolwright mint https://app.example.com --webmcp -a api.example.com
    """
    from toolwright.cli.mint import run_mint

    resolved_output = output or str(ctx.obj.get("root", resolve_root()))

    _run_with_lock(
        ctx,
        "mint",
        lambda: run_mint(
            start_url=start_url,
            allowed_hosts=list(allowed_hosts),
            name=name,
            scope_name=scope,
            headless=headless,
            script_path=script,
            duration_seconds=duration,
            output_root=resolved_output,
            deterministic=deterministic,
            runtime_mode=runtime,
            runtime_build=runtime_build,
            runtime_tag=runtime_tag,
            runtime_version_pin=runtime_version_pin,
            print_mcp_config=print_mcp_config,
            auth_profile=auth_profile,
            webmcp=webmcp,
            redaction_profile=redaction_profile,
            verbose=ctx.obj.get("verbose", False),
        ),
    )


@cli.command("diff")
@click.option(
    "--toolpack",
    type=click.Path(exists=True),
    help="Path to toolpack.yaml (auto-resolved if not given)",
)
@click.option(
    "--baseline",
    type=click.Path(),
    help="Baseline toolpack.yaml or snapshot directory",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output directory for diff artifacts",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "markdown", "github-md", "both"]),
    default="both",
    show_default=True,
    help="Diff output format",
)
@click.pass_context
def diff(
    ctx: click.Context,
    toolpack: str | None,
    baseline: str | None,
    output: str | None,
    output_format: str,
) -> None:
    """Generate a risk-classified change report."""
    from toolwright.utils.resolve import resolve_toolpack_path

    resolved = str(resolve_toolpack_path(explicit=toolpack, root=ctx.obj.get("root")))

    from toolwright.cli.plan import run_plan

    run_plan(
        toolpack_path=resolved,
        baseline=baseline,
        output_dir=output,
        output_format=output_format,
        root_path=str(ctx.obj.get("root", resolve_root())),
        verbose=ctx.obj.get("verbose", False),
    )


@cli.command()
@click.option(
    "--toolpack",
    type=click.Path(exists=True),
    help="Path to toolpack.yaml (auto-resolved if not given)",
)
@click.option(
    "--runtime",
    type=click.Choice(["auto", "local", "container"]),
    default="auto",
    show_default=True,
    help="Runtime to use",
)
@click.option(
    "--print-config-and-exit",
    is_flag=True,
    help="Print MCP config snippet to stdout and exit",
)
@click.option(
    "--toolset",
    help="Named toolset to expose (optional)",
)
@click.option(
    "--lockfile",
    type=click.Path(),
    help="Path to approved lockfile (required by default unless --unsafe-no-lockfile)",
)
@click.option(
    "--base-url",
    help="Base URL for upstream API (overrides manifest hosts)",
)
@click.option(
    "--auth",
    "auth_header",
    help="Authorization header value for upstream requests",
)
@click.option(
    "--audit-log",
    type=click.Path(),
    help="Path for audit log file",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Evaluate policy but don't execute upstream calls",
)
@click.option(
    "--confirm-store",
    type=click.Path(),
    help="Path to local out-of-band confirmation store",
)
@click.option(
    "--allow-private-cidr",
    "allow_private_cidrs",
    multiple=True,
    help="Allow private CIDR targets (repeatable; default denies private ranges)",
)
@click.option(
    "--allow-redirects",
    is_flag=True,
    help="Allow redirects (each hop is re-validated against allowlists)",
)
@click.option(
    "--unsafe-no-lockfile",
    is_flag=True,
    help="Allow runtime without approved lockfile (unsafe escape hatch)",
)
@click.pass_context
def run(
    ctx: click.Context,
    toolpack: str | None,
    runtime: str,
    print_config_and_exit: bool,
    toolset: str | None,
    lockfile: str | None,
    base_url: str | None,
    auth_header: str | None,
    audit_log: str | None,
    dry_run: bool,
    confirm_store: str | None,
    allow_private_cidrs: tuple[str, ...],
    allow_redirects: bool,
    unsafe_no_lockfile: bool,
) -> None:
    """Execute a toolpack with policy enforcement.

    For development with fine-grained path control, see `toolwright serve`.
    """
    from toolwright.utils.resolve import resolve_toolpack_path

    resolved_tp = str(resolve_toolpack_path(explicit=toolpack, root=ctx.obj.get("root")))

    from toolwright.cli.run import run_run

    resolved_confirm_store = confirm_store or str(
        confirmation_store_path(ctx.obj.get("root", resolve_root()))
    )

    _run_with_lock(
        ctx,
        "run",
        lambda: run_run(
            toolpack_path=resolved_tp,
            runtime=runtime,
            print_config_and_exit=print_config_and_exit,
            toolset=toolset,
            lockfile=lockfile,
            base_url=base_url,
            auth_header=auth_header,
            audit_log=audit_log,
            dry_run=dry_run,
            confirm_store=resolved_confirm_store,
            allow_private_cidrs=list(allow_private_cidrs),
            allow_redirects=allow_redirects,
            unsafe_no_lockfile=unsafe_no_lockfile,
            verbose=ctx.obj.get("verbose", False),
        ),
        lock_id=str(Path(resolved_tp).resolve()),
    )


@cli.command()
@click.option("--from", "from_capture", help="Source capture ID")
@click.option("--to", "to_capture", help="Target capture ID")
@click.option("--baseline", type=click.Path(exists=True), help="Baseline file path")
@click.option("--capture-id", help="Capture ID to compare against baseline")
@click.option("--capture-path", type=click.Path(), help="Capture path to compare against baseline")
@click.option(
    "--capture",
    "-c",
    "capture_legacy",
    help="Deprecated alias for --capture-id/--capture-path",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output directory (defaults to <root>/reports)",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["json", "markdown", "both"]),
    default="both",
    help="Report format",
)
@click.option(
    "--deterministic/--volatile-metadata",
    default=True,
    show_default=True,
    help="Deterministic drift output by default; use --volatile-metadata for ephemeral IDs/timestamps",
)
@click.pass_context
def drift(
    ctx: click.Context,
    from_capture: str | None,
    to_capture: str | None,
    baseline: str | None,
    capture_id: str | None,
    capture_path: str | None,
    capture_legacy: str | None,
    output: str | None,
    output_format: str,
    deterministic: bool,
) -> None:
    """Detect drift between captures or against a baseline.

    \b
    Examples:
      toolwright drift --from cap_old --to cap_new
      toolwright drift --baseline baseline.json --capture-id cap_new
    """
    from toolwright.cli.drift import run_drift

    if capture_legacy:
        if capture_id or capture_path:
            click.echo(
                "Error: --capture cannot be used with --capture-id or --capture-path",
                err=True,
            )
            sys.exit(1)
        if Path(capture_legacy).exists():
            capture_path = capture_legacy
        else:
            capture_id = capture_legacy

    resolved_output = output or str(_default_root_path(ctx, "reports"))

    run_drift(
        from_capture=from_capture,
        to_capture=to_capture,
        baseline=baseline,
        capture_id=capture_id,
        capture_path=capture_path,
        output_dir=resolved_output,
        output_format=output_format,
        verbose=ctx.obj.get("verbose", False),
        deterministic=deterministic,
        root_path=str(ctx.obj.get("root", resolve_root())),
    )


@cli.group()
def repair() -> None:
    """Diagnose, plan, and apply fixes for a governed toolpack.

    \b
    Subcommands:
      diagnose  Diagnose issues from audit logs, drift, and verify reports
      plan      Show the current repair plan (Terraform-style)
      apply     Apply patches from the repair plan
    """


@repair.command(
    epilog="""\b
Examples:
  toolwright repair diagnose --toolpack toolpack.yaml
  toolwright repair diagnose --toolpack toolpack.yaml --from audit.log.jsonl
  toolwright repair diagnose --toolpack toolpack.yaml --from audit.log.jsonl --from drift.json
  toolwright repair diagnose --toolpack toolpack.yaml --no-auto-discover
""",
)
@click.option(
    "--toolpack",
    type=click.Path(exists=True),
    help="Path to toolpack.yaml (auto-resolved if not given)",
)
@click.option(
    "--from",
    "from_",
    multiple=True,
    type=click.Path(),
    help="Context file(s) to diagnose (audit log, drift report, verify report). Repeatable.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output directory for repair artifacts (defaults to <root>/repairs/<timestamp>_repair/)",
)
@click.option(
    "--auto-discover/--no-auto-discover",
    default=True,
    show_default=True,
    help="Auto-discover context files near the toolpack",
)
@click.pass_context
def diagnose(
    ctx: click.Context,
    toolpack: str | None,
    from_: tuple[str, ...],
    output: str | None,
    auto_discover: bool,
) -> None:
    """Diagnose issues and propose fixes for a governed toolpack.

    Parses audit logs, drift reports, and verify reports to diagnose problems,
    then proposes copy-pasteable remediation commands classified by safety level.

    \b
    Safety levels:
      safe              Read-only, zero capability expansion
      approval_required Changes approved state or grants new capability
      manual            Requires investigation or new capture
    """
    from toolwright.utils.resolve import resolve_toolpack_path

    resolved = str(resolve_toolpack_path(explicit=toolpack, root=ctx.obj.get("root")))

    from toolwright.cli.repair import run_repair

    run_repair(
        toolpack_path=resolved,
        context_paths=list(from_),
        output_dir=output,
        auto_discover=auto_discover,
        verbose=ctx.obj.get("verbose", False),
        root_path=str(ctx.obj.get("root", resolve_root())),
    )


register_repair_plan_apply(repair_group=repair)


@cli.command(
    epilog="""\b
Examples:
  toolwright verify --toolpack toolpack.yaml
  toolwright verify --toolpack toolpack.yaml --mode baseline-check
  toolwright verify --toolpack toolpack.yaml --mode contracts --strict
  toolwright verify --toolpack toolpack.yaml --mode provenance
""",
)
@click.option(
    "--toolpack",
    type=click.Path(exists=True),
    help="Path to toolpack.yaml (auto-resolved if not given)",
)
@click.option(
    "--mode",
    type=click.Choice(["contracts", "baseline-check", "replay", "outcomes", "provenance", "all"]),
    default="all",
    show_default=True,
    help="Verification mode",
)
@click.option("--lockfile", type=click.Path(), help="Optional lockfile override (pending allowed)")
@click.option("--playbook", type=click.Path(exists=True), help="Path to deterministic playbook")
@click.option("--ui-assertions", type=click.Path(exists=True), help="Path to UI assertion list")
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output directory for verification reports (defaults to <root>/reports)",
)
@click.option("--strict/--no-strict", default=True, show_default=True, help="Strict gating mode")
@click.option("--top-k", default=5, show_default=True, type=int, help="Top candidate APIs per assertion")
@click.option(
    "--min-confidence",
    default=0.70,
    show_default=True,
    type=float,
    help="Minimum confidence threshold for provenance pass",
)
@click.option(
    "--unknown-budget",
    default=0.20,
    show_default=True,
    type=float,
    help="Maximum ratio of unknown provenance assertions before gating",
)
@click.pass_context
def verify(
    ctx: click.Context,
    toolpack: str | None,
    mode: str,
    lockfile: str | None,
    playbook: str | None,
    ui_assertions: str | None,
    output: str | None,
    strict: bool,
    top_k: int,
    min_confidence: float,
    unknown_budget: float,
) -> None:
    """Run verification contracts (replay, outcomes, provenance)."""
    from toolwright.utils.resolve import resolve_toolpack_path

    resolved_tp = str(resolve_toolpack_path(explicit=toolpack, root=ctx.obj.get("root")))

    from toolwright.cli.verify import run_verify

    resolved_output = output or str(_default_root_path(ctx, "reports"))
    run_verify(
        toolpack_path=resolved_tp,
        mode=mode,
        lockfile_path=lockfile,
        playbook_path=playbook,
        ui_assertions_path=ui_assertions,
        output_dir=resolved_output,
        strict=strict,
        top_k=top_k,
        min_confidence=min_confidence,
        unknown_budget=unknown_budget,
        verbose=ctx.obj.get("verbose", False),
    )


@cli.command()
@click.option(
    "--out",
    type=click.Path(file_okay=False),
    help="Output directory for demo artifacts (defaults to a temporary directory)",
)
@click.option(
    "--live",
    is_flag=True,
    help="Run live/browser orchestration (requires extra dependencies)",
)
@click.option(
    "--scenario",
    type=click.Choice(["basic_products", "auth_refresh"]),
    default="basic_products",
    show_default=True,
    help="Live scenario to execute when --live is enabled",
)
@click.option(
    "--keep",
    is_flag=True,
    help="Keep existing output directory contents",
)
@click.option(
    "--smoke",
    is_flag=True,
    help="Run smoke test matrix across multiple scenarios",
)
@click.option(
    "--smoke-scenarios",
    default="offline_fixture",
    show_default=True,
    help="Comma-separated scenarios for --smoke mode",
)
@click.option(
    "--generate-only",
    is_flag=True,
    help="Generate a fixture toolpack without running the prove flow",
)
@click.option(
    "--offline",
    is_flag=True,
    help="Compile-only mode (no server). Same as --generate-only.",
)
@click.pass_context
def demo(
    ctx: click.Context,
    out: str | None,
    live: bool,
    scenario: str,
    keep: bool,
    smoke: bool,
    smoke_scenarios: str,
    generate_only: bool,
    offline: bool,
) -> None:
    """One-command proof of governance enforcement.

    Proves that governance is enforced, replays are deterministic, and parity
    passes. Runs offline by default (no credentials or browser needed).

    \b
    Examples:
      toolwright demo                          # Offline proof flow
      toolwright demo --offline                # Compile-only (no server)
      toolwright demo --live                   # Live browser proof
      toolwright demo --smoke                  # Smoke test matrix
      toolwright demo --generate-only          # Generate fixture toolpack only
    """
    if generate_only or offline:
        from toolwright.cli.demo import run_demo

        _run_with_lock(
            ctx,
            "demo",
            lambda: run_demo(
                output_root=out or str(ctx.obj.get("root", resolve_root())),
                verbose=ctx.obj.get("verbose", False),
            ),
        )
        return

    if smoke:
        from toolwright.cli.wow import run_prove_smoke

        exit_code = run_prove_smoke(
            out_dir=out,
            live=live,
            scenarios=smoke_scenarios,
            keep=keep,
            verbose=ctx.obj.get("verbose", False),
        )
        if exit_code != 0:
            sys.exit(exit_code)
        return

    from toolwright.cli.wow import run_wow

    exit_code = run_wow(
        out_dir=out,
        live=live,
        scenario=scenario,
        keep=keep,
        verbose=ctx.obj.get("verbose", False),
    )
    if exit_code != 0:
        sys.exit(exit_code)


# ---------------------------------------------------------------------------
# Register serve, inspect, gate from external modules
# ---------------------------------------------------------------------------

register_mcp_commands(cli=cli, run_with_lock=_run_with_lock)
register_approval_commands(cli=cli, run_with_lock=_run_with_lock)
register_use_command(cli=cli)
register_workflow_commands(cli=cli)
register_rules_commands(cli=cli)
register_kill_commands(cli=cli)
register_watch_commands(cli=cli)
register_snapshot_commands(cli=cli)


# ---------------------------------------------------------------------------
# HEAL: Health check command
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--tools",
    required=True,
    type=click.Path(exists=True),
    help="Path to tools.json manifest.",
)
def health(tools: str) -> None:
    """Probe endpoint health for all tools in a manifest.

    Sends non-mutating probes (HEAD/OPTIONS) to each endpoint and
    reports status, response time, and failure classification.

    Exits 0 if all healthy, 1 if any unhealthy.

    \\b
    Examples:
      toolwright health --tools output/tools.json
      toolwright health --tools my-api/tools.json
    """
    import asyncio
    import json as _json

    manifest = _json.loads(Path(tools).read_text())
    actions = manifest.get("actions", [])

    if not actions:
        click.echo("No actions found in manifest.")
        return

    from toolwright.core.health.checker import HealthChecker

    checker = HealthChecker()
    results = asyncio.run(checker.check_all(actions))

    any_unhealthy = False
    for r in results:
        status = "healthy" if r.healthy else "UNHEALTHY"
        if not r.healthy:
            any_unhealthy = True
        fc = f"  [{r.failure_class.value}]" if r.failure_class else ""
        code = f"  {r.status_code}" if r.status_code is not None else ""
        click.echo(
            f"  {r.tool_id:<30} {status:<12}{code}{fc}  {r.response_time_ms:.0f}ms"
        )

    click.echo()
    if any_unhealthy:
        click.echo("Some tools are unhealthy.")
        raise SystemExit(1)
    else:
        click.echo("All tools healthy.")


# ---------------------------------------------------------------------------
# Advanced / Hidden Commands
# ---------------------------------------------------------------------------


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
    type=click.Path(exists=True),
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
def config(toolpack: str | None, name: str | None, output_format: str) -> None:
    """Print a ready-to-paste MCP client config snippet (Claude, Cursor, Codex)."""
    from toolwright.utils.resolve import resolve_toolpack_path

    resolved = str(resolve_toolpack_path(explicit=toolpack))

    from toolwright.cli.config import run_config

    run_config(toolpack_path=resolved, fmt=output_format, name_override=name)


@cli.command(hidden=True)
@click.option(
    "--toolpack",
    required=True,
    type=click.Path(exists=True),
    help="Path to toolpack.yaml",
)
@click.option(
    "--runtime",
    type=click.Choice(["auto", "local", "container"]),
    default="auto",
    show_default=True,
    help="Runtime to validate",
)
@click.pass_context
def doctor(ctx: click.Context, toolpack: str, runtime: str) -> None:
    """Validate toolpack readiness for execution."""
    from click.core import ParameterSource

    from toolwright.cli.doctor import run_doctor

    runtime_source = ctx.get_parameter_source("runtime")
    require_local_mcp = (
        runtime == "local" and runtime_source == ParameterSource.COMMANDLINE
    )

    run_doctor(
        toolpack_path=toolpack,
        runtime=runtime,
        verbose=ctx.obj.get("verbose", False),
        require_local_mcp=require_local_mcp,
    )


@cli.command(hidden=True)
@click.option("--capture", "-c", required=True, help="Capture session ID or path")
@click.option(
    "--scope",
    "-s",
    default="first_party_only",
    help="Scope to apply (default: first_party_only)",
)
@click.option("--scope-file", type=click.Path(exists=True), help="Path to custom scope YAML")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["manifest", "openapi", "all"]),
    default="all",
    help="Output format",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output directory (defaults to <root>/artifacts)",
)
@click.option(
    "--deterministic/--volatile-metadata",
    default=True,
    show_default=True,
    help="Deterministic artifacts by default; use --volatile-metadata for ephemeral IDs/timestamps",
)
@click.pass_context
def compile(
    ctx: click.Context,
    capture: str,
    scope: str,
    scope_file: str | None,
    output_format: str,
    output: str | None,
    deterministic: bool,
) -> None:
    """Compile captured traffic into contracts, tools, and policies."""
    from toolwright.cli.compile import run_compile

    resolved_output = output or str(_default_root_path(ctx, "artifacts"))

    _run_with_lock(
        ctx,
        "compile",
        lambda: run_compile(
            capture_id=capture,
            scope_name=scope,
            scope_file=scope_file,
            output_format=output_format,
            output_dir=resolved_output,
            verbose=ctx.obj.get("verbose", False),
            deterministic=deterministic,
            root_path=str(ctx.obj.get("root", resolve_root())),
        ),
    )


@cli.command(hidden=True)
@click.option(
    "--toolpack",
    required=True,
    type=click.Path(exists=True),
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
    type=click.Path(exists=True),
    help="Path to toolpack.yaml (resolves tools/policy paths)",
)
@click.option("--tools", type=click.Path(exists=True), help="Path to tools.json")
@click.option("--policy", type=click.Path(exists=True), help="Path to policy.yaml")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Lint output format",
)
@click.pass_context
def lint(
    ctx: click.Context,
    toolpack: str | None,
    tools: str | None,
    policy: str | None,
    output_format: str,
) -> None:
    """Lint capability artifacts for strict governance hygiene."""
    from toolwright.cli.lint import run_lint

    run_lint(
        toolpack_path=toolpack,
        tools_path=tools,
        policy_path=policy,
        output_format=output_format,
        verbose=ctx.obj.get("verbose", False),
    )


@cli.command(hidden=True)
@click.option("--tools", "-t", required=True, type=click.Path(exists=True), help="Tool manifest")
@click.option(
    "--toolsets",
    type=click.Path(exists=True),
    help="Path to toolsets.yaml artifact (optional)",
)
@click.option(
    "--toolset",
    help="Named toolset to enforce (optional, defaults to all tools)",
)
@click.option("--policy", "-p", required=True, type=click.Path(exists=True), help="Policy file")
@click.option(
    "--lockfile",
    type=click.Path(exists=True),
    help="Approval lockfile for runtime gating (required in proxy mode unless --unsafe-no-lockfile)",
)
@click.option("--port", default=8081, help="Port for gateway")
@click.option("--audit-log", type=click.Path(), help="Path for audit log")
@click.option("--dry-run", is_flag=True, help="Evaluate but don't execute")
@click.option(
    "--mode", "-m",
    type=click.Choice(["evaluate", "proxy"]),
    default="evaluate",
    help="Mode: evaluate (policy only) or proxy (forward to upstream)",
)
@click.option(
    "--base-url",
    help="Base URL for upstream API (proxy mode)",
)
@click.option(
    "--auth",
    "auth_header",
    help="Authorization header for upstream requests (proxy mode)",
)
@click.option(
    "--confirm-store",
    type=click.Path(),
    help="Path to local out-of-band confirmation store",
)
@click.option(
    "--allow-private-cidr",
    "allow_private_cidrs",
    multiple=True,
    help="Allow private CIDR targets (repeatable; default denies private ranges)",
)
@click.option(
    "--allow-redirects",
    is_flag=True,
    help="Allow redirects (each hop is re-validated against allowlists)",
)
@click.option(
    "--unsafe-no-lockfile",
    is_flag=True,
    help="Allow proxy mode without lockfile approvals/integrity gating (unsafe escape hatch)",
)
@click.pass_context
def enforce(
    ctx: click.Context,
    tools: str,
    toolsets: str | None,
    toolset: str | None,
    policy: str,
    lockfile: str | None,
    port: int,
    audit_log: str | None,
    dry_run: bool,
    mode: str,
    base_url: str | None,
    auth_header: str | None,
    confirm_store: str | None,
    allow_private_cidrs: tuple[str, ...],
    allow_redirects: bool,
    unsafe_no_lockfile: bool,
) -> None:
    """Run the policy enforcement gateway."""
    from toolwright.cli.enforce import run_enforce

    resolved_confirm_store = confirm_store or str(
        confirmation_store_path(ctx.obj.get("root", resolve_root()))
    )

    _run_with_lock(
        ctx,
        "enforce",
        lambda: run_enforce(
            tools_path=tools,
            toolsets_path=toolsets,
            toolset_name=toolset,
            policy_path=policy,
            port=port,
            audit_log=audit_log,
            dry_run=dry_run,
            verbose=ctx.obj.get("verbose", False),
            mode=mode,
            base_url=base_url,
            auth_header=auth_header,
            lockfile_path=lockfile,
            confirmation_store_path=resolved_confirm_store,
            allow_private_cidrs=list(allow_private_cidrs),
            allow_redirects=allow_redirects,
            unsafe_no_lockfile=unsafe_no_lockfile,
        ),
    )


@cli.command(hidden=True)
@click.option(
    "--toolpack",
    required=True,
    type=click.Path(exists=True),
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

    _run_with_lock(
        ctx,
        "migrate",
        lambda: run_migrate(
            toolpack_path=toolpack,
            apply_changes=apply_changes,
            verbose=ctx.obj.get("verbose", False),
        ),
    )


# ---------------------------------------------------------------------------
# Secondary Groups (hidden by default)
# ---------------------------------------------------------------------------


@cli.group(hidden=True)
def scope() -> None:
    """Scope authoring and merge workflows."""


@scope.command("merge")
@click.option(
    "--suggested",
    type=click.Path(),
    help="Path to generated scopes.suggested.yaml (defaults to <root>/scopes/scopes.suggested.yaml)",
)
@click.option(
    "--authoritative",
    type=click.Path(),
    help="Path to authoritative scopes.yaml (defaults to <root>/scopes/scopes.yaml)",
)
@click.option(
    "--output",
    type=click.Path(),
    help="Path to write merge proposal (defaults to sibling scopes.merge.proposed.yaml)",
)
@click.option("--apply", is_flag=True, help="Apply merged proposal into authoritative scopes.yaml")
@click.pass_context
def scope_merge(
    ctx: click.Context,
    suggested: str | None,
    authoritative: str | None,
    output: str | None,
    apply: bool,
) -> None:
    """Merge suggested scopes into authoritative scopes via explicit proposal."""
    from toolwright.cli.scopes import run_scopes_merge

    resolved_suggested = suggested or str(_default_root_path(ctx, "scopes", "scopes.suggested.yaml"))
    resolved_authoritative = authoritative or str(_default_root_path(ctx, "scopes", "scopes.yaml"))

    def _merge_scopes() -> None:
        run_scopes_merge(
            suggested_path=resolved_suggested,
            authoritative_path=resolved_authoritative,
            output_path=output,
            apply=apply,
            verbose=ctx.obj.get("verbose", False),
        )

    if apply:
        _run_with_lock(ctx, "scope merge", _merge_scopes)
    else:
        _merge_scopes()


@cli.group(hidden=True)
def confirm() -> None:
    """Out-of-band confirmation workflow for state-changing actions."""


@confirm.command("grant")
@click.argument("token_id", required=True)
@click.option(
    "--store",
    "store_path",
    type=click.Path(),
    help="Path to confirmation store",
)
@click.pass_context
def confirm_grant(ctx: click.Context, token_id: str, store_path: str | None) -> None:
    """Grant a pending confirmation token."""
    from toolwright.cli.confirm import run_confirm_grant

    resolved_store = store_path or str(
        confirmation_store_path(ctx.obj.get("root", resolve_root()))
    )

    _run_with_lock(
        ctx,
        "confirm grant",
        lambda: run_confirm_grant(
            token_id=token_id,
            db_path=resolved_store,
            verbose=ctx.obj.get("verbose", False),
        ),
    )


@confirm.command("deny")
@click.argument("token_id", required=True)
@click.option(
    "--store",
    "store_path",
    type=click.Path(),
    help="Path to confirmation store",
)
@click.option("--reason", help="Optional denial reason")
@click.pass_context
def confirm_deny(
    ctx: click.Context,
    token_id: str,
    store_path: str | None,
    reason: str | None,
) -> None:
    """Deny a pending confirmation token."""
    from toolwright.cli.confirm import run_confirm_deny

    resolved_store = store_path or str(
        confirmation_store_path(ctx.obj.get("root", resolve_root()))
    )

    _run_with_lock(
        ctx,
        "confirm deny",
        lambda: run_confirm_deny(
            token_id=token_id,
            db_path=resolved_store,
            reason=reason,
            verbose=ctx.obj.get("verbose", False),
        ),
    )


@confirm.command("list")
@click.option(
    "--store",
    "store_path",
    type=click.Path(),
    help="Path to confirmation store",
)
@click.pass_context
def confirm_list(ctx: click.Context, store_path: str | None) -> None:
    """List pending confirmation tokens."""
    from toolwright.cli.confirm import run_confirm_list

    resolved_store = store_path or str(
        confirmation_store_path(ctx.obj.get("root", resolve_root()))
    )

    run_confirm_list(
        db_path=resolved_store,
        verbose=ctx.obj.get("verbose", False),
    )


@cli.group(hidden=True)
def propose() -> None:
    """Manage agent draft proposals for new capabilities."""


@propose.command("create")
@click.argument("capture_id")
@click.option(
    "--scope",
    "-s",
    default="first_party_only",
    show_default=True,
    help="Scope to apply before generating proposals",
)
@click.option(
    "--scope-file",
    type=click.Path(exists=True),
    default=None,
    help="Optional custom scope file",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=False),
    default=None,
    help="Directory to write proposal artifacts (defaults to <root>/proposals)",
)
@click.option(
    "--deterministic/--volatile-metadata",
    default=True,
    show_default=True,
    help="Deterministic proposal artifact IDs by default",
)
@click.pass_context
def propose_create(
    ctx: click.Context,
    capture_id: str,
    scope: str,
    scope_file: str | None,
    output: str | None,
    deterministic: bool,
) -> None:
    """Generate endpoint catalog and tool proposals from a capture."""
    from toolwright.cli.propose import run_propose_from_capture

    root = str(ctx.obj.get("root", resolve_root())) if ctx.obj else ".toolwright"
    run_propose_from_capture(
        root=root,
        capture_id=capture_id,
        scope_name=scope,
        scope_file=scope_file,
        output_dir=output,
        deterministic=deterministic,
        verbose=ctx.obj.get("verbose", False) if ctx.obj else False,
    )


@propose.command("publish")
@click.argument("proposal_input", type=click.Path(exists=True))
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=False),
    default=None,
    help="Directory root for published bundle output (defaults to <root>/published)",
)
@click.option(
    "--min-confidence",
    type=float,
    default=0.75,
    show_default=True,
    help="Minimum proposal confidence to include",
)
@click.option(
    "--max-risk",
    type=click.Choice(["safe", "low", "medium", "high", "critical"]),
    default="high",
    show_default=True,
    help="Maximum risk tier to include",
)
@click.option(
    "--include-review-required",
    is_flag=True,
    help="Include proposals flagged as requires_review",
)
@click.option(
    "--proposal-id",
    "proposal_ids",
    multiple=True,
    help="Restrict publish to specific proposal IDs (repeatable)",
)
@click.option(
    "--sync-lockfile",
    is_flag=True,
    help="Sync generated tools into lockfile after publish",
)
@click.option(
    "--lockfile",
    default=None,
    help="Lockfile path override (used with --sync-lockfile)",
)
@click.option(
    "--deterministic/--volatile-metadata",
    default=True,
    show_default=True,
    help="Deterministic bundle IDs and timestamps by default",
)
@click.pass_context
def propose_publish(
    ctx: click.Context,
    proposal_input: str,
    output: str | None,
    min_confidence: float,
    max_risk: str,
    include_review_required: bool,
    proposal_ids: tuple[str, ...],
    sync_lockfile: bool,
    lockfile: str | None,
    deterministic: bool,
) -> None:
    """Publish tools.proposed.yaml into runtime-ready bundle artifacts."""
    from toolwright.cli.propose import run_propose_publish

    root = str(ctx.obj.get("root", resolve_root())) if ctx.obj else ".toolwright"
    run_propose_publish(
        root=root,
        proposal_input=proposal_input,
        output_dir=output,
        min_confidence=min_confidence,
        max_risk=max_risk,
        include_review_required=include_review_required,
        proposal_ids=proposal_ids,
        sync_lockfile_enabled=sync_lockfile,
        lockfile_path=lockfile,
        deterministic=deterministic,
        verbose=ctx.obj.get("verbose", False) if ctx.obj else False,
    )


@propose.command("list")
@click.option("--status", type=click.Choice(["pending", "approved", "rejected"]), default=None)
@click.pass_context
def propose_list(ctx: click.Context, status: str | None) -> None:
    """List agent draft proposals."""
    from toolwright.cli.propose import run_propose_list

    root = str(ctx.obj.get("root", resolve_root())) if ctx.obj else ".toolwright"
    run_propose_list(root=root, status=status)


@propose.command("show")
@click.argument("proposal_id")
@click.pass_context
def propose_show(ctx: click.Context, proposal_id: str) -> None:
    """Show details of a specific proposal."""
    from toolwright.cli.propose import run_propose_show

    root = str(ctx.obj.get("root", resolve_root())) if ctx.obj else ".toolwright"
    run_propose_show(root=root, proposal_id=proposal_id)


@propose.command("approve")
@click.argument("proposal_id")
@click.option("--by", "reviewed_by", default="human", help="Who is approving")
@click.pass_context
def propose_approve(ctx: click.Context, proposal_id: str, reviewed_by: str) -> None:
    """Approve a proposal for future capture."""
    from toolwright.cli.propose import run_propose_approve

    root = str(ctx.obj.get("root", resolve_root())) if ctx.obj else ".toolwright"
    run_propose_approve(root=root, proposal_id=proposal_id, reviewed_by=reviewed_by)


@propose.command("reject")
@click.argument("proposal_id")
@click.option("--reason", "-r", default="", help="Rejection reason")
@click.option("--by", "reviewed_by", default="human", help="Who is rejecting")
@click.pass_context
def propose_reject(ctx: click.Context, proposal_id: str, reason: str, reviewed_by: str) -> None:
    """Reject a proposal with an optional reason."""
    from toolwright.cli.propose import run_propose_reject

    root = str(ctx.obj.get("root", resolve_root())) if ctx.obj else ".toolwright"
    run_propose_reject(root=root, proposal_id=proposal_id, reason=reason, reviewed_by=reviewed_by)


# ---------------------------------------------------------------------------
# Auth Group
# ---------------------------------------------------------------------------


@cli.group()
def auth() -> None:
    """Manage authentication profiles and check auth configuration."""


register_auth_check_command(auth_group=auth)


@auth.command("login")
@click.option("--profile", required=True, help="Profile name")
@click.option("--url", required=True, help="Target URL to authenticate against")
@click.option("--root", default=None, help="Toolwright root directory override")
@click.pass_context
def auth_login(ctx: click.Context, profile: str, url: str, root: str | None) -> None:
    """Launch headful browser for one-time login, saving storage state."""
    from toolwright.cli.auth import auth_login as _do_login

    resolved_root = root or str(ctx.obj.get("root", resolve_root())) if ctx.obj else root or ".toolwright"
    ctx.invoke(_do_login, profile=profile, url=url, root=resolved_root)


@auth.command("status")
@click.option("--profile", required=True, help="Profile name")
@click.option("--root", default=None, help="Toolwright root directory override")
@click.pass_context
def auth_status(ctx: click.Context, profile: str, root: str | None) -> None:
    """Show the status of an auth profile."""
    from toolwright.cli.auth import auth_status as _do_status

    resolved_root = root or str(ctx.obj.get("root", resolve_root())) if ctx.obj else root or ".toolwright"
    ctx.invoke(_do_status, profile=profile, root=resolved_root)


@auth.command("clear")
@click.option("--profile", required=True, help="Profile name")
@click.option("--root", default=None, help="Toolwright root directory override")
@click.pass_context
def auth_clear(ctx: click.Context, profile: str, root: str | None) -> None:
    """Delete an auth profile."""
    from toolwright.cli.auth import auth_clear as _do_clear

    resolved_root = root or str(ctx.obj.get("root", resolve_root())) if ctx.obj else root or ".toolwright"
    ctx.invoke(_do_clear, profile=profile, root=resolved_root)


@auth.command("list")
@click.option("--root", default=None, help="Toolwright root directory override")
@click.pass_context
def auth_list_cmd(ctx: click.Context, root: str | None) -> None:
    """List all auth profiles."""
    from toolwright.cli.auth import auth_list as _do_list

    resolved_root = root or str(ctx.obj.get("root", resolve_root())) if ctx.obj else root or ".toolwright"
    ctx.invoke(_do_list, root=resolved_root)


# ---------------------------------------------------------------------------
# State Management
# ---------------------------------------------------------------------------


@cli.group(hidden=True)
def state() -> None:
    """Local state management commands."""


@state.command("unlock")
@click.option(
    "--force",
    is_flag=True,
    help="Force remove lock even if process appears active",
)
@click.pass_context
def state_unlock(ctx: click.Context, force: bool) -> None:
    """Clear the root state lock file."""
    root = ctx.obj.get("root", resolve_root())
    try:
        clear_root_lock(root, force=force)
    except RootLockError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"Cleared lock for root: {root}")


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------


@cli.group(hidden=True)
def compliance() -> None:
    """EU AI Act compliance reporting."""


@compliance.command("report")
@click.option(
    "--tools", "tools_path",
    type=click.Path(exists=True),
    help="Path to tools.json manifest",
)
@click.option(
    "--output", "output_path",
    type=click.Path(),
    default=None,
    help="Output path for the report (default: stdout as JSON)",
)
def compliance_report(tools_path: str | None, output_path: str | None) -> None:
    """Generate a structured compliance report."""
    from toolwright.cli.compliance import run_compliance_report

    run_compliance_report(tools_path=tools_path, output_path=output_path)


if __name__ == "__main__":
    cli()

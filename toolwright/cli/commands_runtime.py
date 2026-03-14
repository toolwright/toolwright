"""Runtime-oriented top-level command registration."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import click

from toolwright.cli.command_helpers import cli_root, resolve_confirmation_store
from toolwright.utils.locks import RootLockError, clear_root_lock


def register_runtime_commands(
    *,
    cli: click.Group,
    run_with_lock: Callable[..., None],
) -> None:
    """Register runtime execution and state-management commands."""

    @cli.command()
    @click.option(
        "--tools", "-t",
        type=click.Path(),
        help="Path to tools.json manifest",
    )
    @click.option(
        "--toolpack",
        type=click.Path(),
        help="Path to toolpack.yaml (auto-resolved if not given)",
    )
    @click.option(
        "--toolsets",
        type=click.Path(),
        help="Path to toolsets.yaml (defaults to sibling of --tools if present)",
    )
    @click.option(
        "--policy", "-p",
        type=click.Path(),
        help="Path to policy.yaml (optional)",
    )
    @click.option(
        "--toolset",
        help="Named toolset to expose (defaults to readonly when toolsets.yaml exists)",
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
        envvar="TOOLWRIGHT_AUTH_HEADER",
        help="Authorization header value for upstream requests (also reads TOOLWRIGHT_AUTH_HEADER env var)",
    )
    @click.option(
        "--extra-header", "-H",
        "extra_header_raw",
        multiple=True,
        help="Extra header to inject into upstream requests (repeatable, format: 'Name: value')",
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
    @click.option(
        "--rules-path",
        type=click.Path(),
        help="Path to behavioral rules JSON file (enables CORRECT pillar runtime enforcement)",
    )
    @click.option(
        "--circuit-breaker-path",
        type=click.Path(),
        help="Path to circuit breaker state JSON file (enables KILL pillar runtime enforcement)",
    )
    @click.option(
        "--watch",
        is_flag=True,
        help="Enable continuous health monitoring (reconciliation loop)",
    )
    @click.option(
        "--watch-config",
        type=click.Path(),
        help="Path to watch config YAML (default: .toolwright/watch.yaml)",
    )
    @click.option(
        "--auto-heal",
        type=click.Choice(["off", "safe", "all"]),
        default=None,
        help="Auto-heal policy (requires --watch): off, safe, or all",
    )
    @click.option(
        "--verbose-tools",
        is_flag=True,
        help="Use full verbose tool descriptions instead of compact ones",
    )
    @click.option(
        "--tool-filter",
        help="Glob pattern to filter tools by name (e.g. 'get_*')",
    )
    @click.option(
        "--max-risk",
        type=click.Choice(["low", "medium", "high", "critical"]),
        default=None,
        help="Maximum risk tier to expose (filters out higher-risk tools)",
    )
    @click.option(
        "--scope", "-s",
        "serve_scope",
        type=str,
        default=None,
        help="Comma-separated tool groups to serve (e.g., 'products,orders'). Use 'toolwright groups list' to see available groups.",
    )
    @click.option(
        "--no-tool-limit",
        is_flag=True,
        default=False,
        help="Override the 200-tool safety limit. Not recommended.",
    )
    @click.option(
        "--schema-validation",
        type=click.Choice(["strict", "warn", "off"]),
        default="warn",
        show_default=True,
        help="Output schema validation mode: strict (client validates), warn (lenient, default), off (skip)",
    )
    @click.option(
        "--shape-baselines",
        type=click.Path(),
        default=None,
        help="Path to shape_baselines.json for autonomous drift probing (requires --watch)",
    )
    @click.option(
        "--shape-probe-interval",
        type=int,
        default=300,
        show_default=True,
        help="Interval in seconds between shape drift probes (requires --shape-baselines)",
    )
    @click.option(
        "--http",
        "use_http",
        is_flag=True,
        help="Use HTTP transport (StreamableHTTP) instead of stdio",
    )
    @click.option(
        "--host",
        default="127.0.0.1",
        show_default=True,
        help="Host to bind the HTTP server to (requires --http)",
    )
    @click.option(
        "--port",
        type=int,
        default=8745,
        show_default=True,
        help="Port for the HTTP server (requires --http)",
    )
    @click.pass_context
    def serve(
        ctx: click.Context,
        tools: str | None,
        toolpack: str | None,
        toolsets: str | None,
        policy: str | None,
        toolset: str | None,
        lockfile: str | None,
        base_url: str | None,
        auth_header: str | None,
        extra_header_raw: tuple[str, ...],
        audit_log: str | None,
        dry_run: bool,
        confirm_store: str | None,
        allow_private_cidrs: tuple[str, ...],
        allow_redirects: bool,
        unsafe_no_lockfile: bool,
        rules_path: str | None,
        circuit_breaker_path: str | None,
        watch: bool,
        watch_config: str | None,
        auto_heal: str | None,
        verbose_tools: bool,
        tool_filter: str | None,
        max_risk: str | None,
        serve_scope: str | None,
        no_tool_limit: bool,
        schema_validation: str,
        shape_baselines: str | None,
        shape_probe_interval: int,
        use_http: bool,
        host: str,
        port: int,
    ) -> None:
        """Start the governed MCP server on stdio transport.

        Exposes compiled tools as callable actions that AI agents can use
        safely, with policy enforcement, confirmation requirements, and
        audit logging.

        For production use with automatic validation, see `toolwright run`.

        \b
        Examples:
          toolwright serve --toolpack .toolwright/toolpacks/<id>/toolpack.yaml
          toolwright serve --tools tools.json --policy policy.yaml
          toolwright serve --toolpack toolpack.yaml --toolset readonly
          toolwright serve --toolpack toolpack.yaml --base-url https://api.example.com
          toolwright serve --toolpack toolpack.yaml --dry-run

        \b
        Claude Desktop configuration (see Claude Desktop docs for your platform):
          {
            "mcpServers": {
              "my-api": {
                "command": "toolwright",
                "args": ["serve", "--toolpack", "/path/to/toolpack.yaml"]
              }
            }
          }
        """
        if auto_heal is not None and not watch:
            click.echo("Error: --auto-heal requires --watch", err=True)
            ctx.exit(2)

        if shape_baselines is not None and not watch:
            click.echo("Error: --shape-baselines requires --watch", err=True)
            ctx.exit(2)

        from toolwright.utils.headers import parse_extra_headers

        cli_extra_headers = parse_extra_headers(extra_header_raw) if extra_header_raw else None

        if not toolpack and not tools:
            try:
                from toolwright.utils.resolve import resolve_toolpack_path

                toolpack = str(resolve_toolpack_path(root=cli_root(ctx)))
            except (FileNotFoundError, click.UsageError):
                pass

        from toolwright.mcp.runtime import run_mcp_serve

        lock_id = None
        if toolpack:
            lock_id = f"toolpack:{Path(toolpack).resolve()}"
        elif tools:
            lock_id = f"tools:{Path(tools).resolve()}"

        run_with_lock(
            ctx,
            "serve",
            lambda: run_mcp_serve(
                tools_path=tools,
                toolpack_path=toolpack,
                toolsets_path=toolsets,
                toolset_name=toolset,
                policy_path=policy,
                lockfile_path=lockfile,
                base_url=base_url,
                auth_header=auth_header,
                audit_log=audit_log,
                dry_run=dry_run,
                confirmation_store_path=resolve_confirmation_store(ctx, confirm_store),
                allow_private_cidrs=list(allow_private_cidrs),
                allow_redirects=allow_redirects,
                unsafe_no_lockfile=unsafe_no_lockfile,
                verbose=ctx.obj.get("verbose", False),
                rules_path=rules_path,
                circuit_breaker_path=circuit_breaker_path,
                watch=watch,
                watch_config_path=watch_config,
                auto_heal_override=auto_heal,
                verbose_tools=verbose_tools,
                tool_filter=tool_filter,
                max_risk=max_risk,
                transport="http" if use_http else "stdio",
                host=host,
                port=port,
                extra_headers=cli_extra_headers,
                schema_validation=schema_validation,
                shape_baselines_path=shape_baselines,
                shape_probe_interval=shape_probe_interval,
                scope=serve_scope,
                no_tool_limit=no_tool_limit,
            ),
            lock_id=lock_id,
        )

    @cli.command()
    @click.option(
        "--toolpack",
        type=click.Path(),
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
        from toolwright.cli.run import run_run
        from toolwright.utils.resolve import resolve_toolpack_path

        resolved_toolpack = str(resolve_toolpack_path(explicit=toolpack, root=cli_root(ctx)))

        run_with_lock(
            ctx,
            "run",
            lambda: run_run(
                toolpack_path=resolved_toolpack,
                runtime=runtime,
                print_config_and_exit=print_config_and_exit,
                toolset=toolset,
                lockfile=lockfile,
                base_url=base_url,
                auth_header=auth_header,
                audit_log=audit_log,
                dry_run=dry_run,
                confirm_store=resolve_confirmation_store(ctx, confirm_store),
                allow_private_cidrs=list(allow_private_cidrs),
                allow_redirects=allow_redirects,
                unsafe_no_lockfile=unsafe_no_lockfile,
                verbose=ctx.obj.get("verbose", False),
            ),
            lock_id=str(Path(resolved_toolpack).resolve()),
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

        run_with_lock(
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
                confirmation_store_path=resolve_confirmation_store(ctx, confirm_store),
                allow_private_cidrs=list(allow_private_cidrs),
                allow_redirects=allow_redirects,
                unsafe_no_lockfile=unsafe_no_lockfile,
            ),
        )

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
        root = cli_root(ctx)
        try:
            clear_root_lock(root, force=force)
        except RootLockError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        click.echo(f"Cleared lock for root: {root}")

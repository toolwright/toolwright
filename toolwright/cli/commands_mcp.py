"""MCP serve and inspect command registration for the top-level CLI."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import click

from toolwright.utils.state import confirmation_store_path, resolve_root


def register_mcp_commands(
    *,
    cli: click.Group,
    run_with_lock: Callable[..., None],
) -> None:
    """Register serve and inspect commands on the provided CLI group."""

    @cli.command()
    @click.option(
        "--tools", "-t",
        type=click.Path(),
        help="Path to tools.json manifest",
    )
    @click.option(
        "--toolpack",
        type=click.Path(exists=True),
        help="Path to toolpack.yaml (resolves manifest/policy/toolsets paths)",
    )
    @click.option(
        "--toolsets",
        type=click.Path(),
        help="Path to toolsets.yaml (defaults to sibling of --tools if present)",
    )
    @click.option(
        "--toolset",
        help="Named toolset to expose (defaults to readonly when toolsets.yaml exists)",
    )
    @click.option(
        "--policy", "-p",
        type=click.Path(),
        help="Path to policy.yaml (optional)",
    )
    @click.option(
        "--lockfile", "-l",
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
        toolset: str | None,
        policy: str | None,
        lockfile: str | None,
        base_url: str | None,
        auth_header: str | None,
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
          # Resolve all paths from a toolpack
          toolwright serve --toolpack .toolwright/toolpacks/<id>/toolpack.yaml

          # With explicit manifest
          toolwright serve --tools tools.json --policy policy.yaml

          # Expose a curated toolset
          toolwright serve --toolpack toolpack.yaml --toolset readonly

          # With upstream API configuration
          toolwright serve --toolpack toolpack.yaml --base-url https://api.example.com

          # Dry run mode (no actual API calls)
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

        resolved_confirm_store = confirm_store or str(
            confirmation_store_path(ctx.obj.get("root", resolve_root()))
        )

        # Auto-resolve toolpack if neither --toolpack nor --tools provided
        if not toolpack and not tools:
            try:
                from toolwright.utils.resolve import resolve_toolpack_path

                toolpack = str(resolve_toolpack_path(root=ctx.obj.get("root")))
            except (FileNotFoundError, click.UsageError):
                pass  # Let downstream handle missing tools/toolpack

        from toolwright.cli.mcp import run_mcp_serve

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
                confirmation_store_path=resolved_confirm_store,
                allow_private_cidrs=list(allow_private_cidrs),
                allow_redirects=allow_redirects,
                unsafe_no_lockfile=unsafe_no_lockfile,
                verbose=ctx.obj.get("verbose", False),
                rules_path=rules_path,
                circuit_breaker_path=circuit_breaker_path,
                watch=watch,
                watch_config_path=watch_config,
                auto_heal_override=auto_heal,
                transport="http" if use_http else "stdio",
                host=host,
                port=port,
            ),
            lock_id=lock_id,
        )

    @cli.command(hidden=True)
    @click.option(
        "--artifacts", "-a",
        type=click.Path(exists=True),
        help="Path to artifacts directory",
    )
    @click.option(
        "--tools", "-t",
        type=click.Path(exists=True),
        help="Path to tools.json (overrides --artifacts)",
    )
    @click.option(
        "--policy", "-p",
        type=click.Path(exists=True),
        help="Path to policy.yaml (overrides --artifacts)",
    )
    @click.option(
        "--lockfile", "-l",
        type=click.Path(),
        help="Path to lockfile (default: ./toolwright.lock.yaml)",
    )
    @click.option(
        "--rules-path",
        type=click.Path(),
        help="Path to behavioral rules JSON file (enables CORRECT meta-tools)",
    )
    @click.option(
        "--circuit-breaker-path",
        type=click.Path(),
        help="Path to circuit breaker state JSON file (enables KILL meta-tools)",
    )
    @click.pass_context
    def inspect(
        ctx: click.Context,  # noqa: ARG001
        artifacts: str | None,
        tools: str | None,
        policy: str | None,
        lockfile: str | None,
        rules_path: str | None,
        circuit_breaker_path: str | None,
    ) -> None:
        """Start a read-only MCP introspection server.

        Allows operators and CI tools to inspect governance state:
        list actions, check policy, view approval status, get risk summaries.

        \b
        Examples:
          toolwright inspect --artifacts .toolwright/artifacts/*/
          toolwright inspect --tools tools.json --policy policy.yaml
          toolwright inspect --tools tools.json --rules-path rules.json --circuit-breaker-path breakers.json

        \b
        Available tools exposed:
          GOVERN: toolwright_list_actions, toolwright_check_policy,
                  toolwright_get_approval_status, toolwright_risk_summary
          HEAL:   toolwright_diagnose_tool, toolwright_health_check
          KILL:   toolwright_kill_tool, toolwright_enable_tool,
                  toolwright_quarantine_report (requires --circuit-breaker-path)
          CORRECT: toolwright_add_rule, toolwright_list_rules,
                   toolwright_remove_rule (requires --rules-path)

        \b
        Claude Desktop configuration:
          {
            "mcpServers": {
              "toolwright": {
                "command": "toolwright",
                "args": ["inspect", "--tools", "/path/to/tools.json"]
              }
            }
          }
        """
        from toolwright.utils.deps import require_mcp_dependency

        require_mcp_dependency()

        from toolwright.mcp.meta_server import run_meta_server

        run_meta_server(
            artifacts_dir=artifacts,
            tools_path=tools,
            policy_path=policy,
            lockfile_path=lockfile,
            rules_path=rules_path,
            circuit_breaker_path=circuit_breaker_path,
        )

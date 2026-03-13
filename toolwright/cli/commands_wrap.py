"""CLI command for toolwright wrap - govern any existing MCP server."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import click


@click.command("wrap")
@click.argument("command_args", nargs=-1)
@click.option("--name", default=None, help="Server name (auto-derived from command if omitted)")
@click.option("--url", default=None, help="Streamable HTTP target URL")
@click.option(
    "--header",
    multiple=True,
    help="HTTP header for target (repeatable, format: 'Name: value')",
)
@click.option("--auto-approve", is_flag=True, help="Auto-approve low-risk (read-only) tools")
@click.option("--vendor", "do_vendor", is_flag=True, help="Vendor package for code-level healing")
@click.option("--http", "use_http", is_flag=True, help="Expose Toolwright as HTTP instead of stdio")
@click.option("--port", default=8745, type=int, help="HTTP port (when --http)")
@click.option("--dry-run", is_flag=True, help="Simulate without executing upstream calls")
@click.option("--rules", type=click.Path(exists=True), help="Behavioral rules file")
@click.option("--circuit-breaker", type=click.Path(), help="Circuit breaker state file")
def wrap_command(
    command_args: tuple[str, ...],
    name: str | None,
    url: str | None,
    header: tuple[str, ...],
    auto_approve: bool,
    do_vendor: bool,  # noqa: ARG001  vendor is deferred to v2
    use_http: bool,
    port: int,
    dry_run: bool,
    rules: str | None,
    circuit_breaker: str | None,
) -> None:
    """Govern any existing MCP server without recreating its tools.

    \b
    Examples:
      toolwright wrap npx -y @modelcontextprotocol/server-github
      toolwright wrap --url https://mcp.sentry.dev/mcp --header "Authorization: Bearer xxx"
      toolwright wrap --name github --auto-approve npx -y @modelcontextprotocol/server-github
      toolwright wrap                    # Uses saved .toolwright/wrap/<name>/wrap.yaml
    """
    from toolwright.models.overlay import TargetType, WrapConfig
    from toolwright.overlay.config import derive_server_name, load_wrap_config, save_wrap_config

    # Resolve target
    if url:
        target_type = TargetType.STREAMABLE_HTTP
        command = None
        args: list[str] = []
        headers = _parse_headers(header)
        if not name:
            # Derive from URL hostname
            from urllib.parse import urlparse

            parsed = urlparse(url)
            name = (parsed.hostname or "unknown").split(".")[0]
    elif command_args:
        target_type = TargetType.STDIO
        command = command_args[0]
        args = list(command_args[1:])
        headers = {}
        url = None
        if not name:
            name = derive_server_name(command, args)
    else:
        # Try loading saved config
        wrap_root = Path(".toolwright") / "wrap"
        saved = load_wrap_config(wrap_root=wrap_root)
        if saved is None:
            click.echo(
                "Error: No target specified. Provide a command, --url, or run from a directory "
                "with a saved .toolwright/wrap/ config.",
                err=True,
            )
            sys.exit(1)
        config = saved
        click.echo(f"Using saved config for '{config.server_name}'", err=True)
        _run_wrap(config, dry_run, rules, circuit_breaker, use_http, port)
        return

    state_dir = Path(".toolwright") / "wrap" / name
    config = WrapConfig(
        server_name=name,
        target_type=target_type,
        command=command,
        args=args,
        url=url,
        headers=headers,
        auto_approve_safe=auto_approve,
        state_dir=state_dir,
        proxy_transport="http" if use_http else "stdio",
    )

    # Save config for future use
    save_wrap_config(config)

    _run_wrap(config, dry_run, rules, circuit_breaker, use_http, port)


def _parse_headers(header_strings: tuple[str, ...]) -> dict[str, str]:
    """Parse 'Name: value' header strings into a dict."""
    headers: dict[str, str] = {}
    for h in header_strings:
        if ":" in h:
            key, _, value = h.partition(":")
            headers[key.strip()] = value.strip()
    return headers


def _run_wrap(
    config: Any,
    dry_run: bool,
    rules: str | None,
    circuit_breaker: str | None,
    use_http: bool,
    port: int,
) -> None:
    """Execute the wrap server lifecycle."""
    asyncio.run(_async_run_wrap(config, dry_run, rules, circuit_breaker, use_http, port))


async def _async_run_wrap(
    config: Any,
    dry_run: bool,
    rules: str | None,
    circuit_breaker: str | None,
    use_http: bool,
    port: int,
) -> None:
    """Async entry point for the wrap server."""
    import json

    import click

    from toolwright.overlay.config import build_client_config
    from toolwright.overlay.connection import WrappedConnection
    from toolwright.overlay.discovery import build_synthetic_manifest, discover_tools
    from toolwright.overlay.server import OverlayServer

    # 1. Connect to upstream
    click.echo(f"Connecting to upstream server '{config.server_name}'...", err=True)
    connection = WrappedConnection(config)
    try:
        await connection.connect()
    except Exception as e:
        click.echo(f"Error: Failed to connect to upstream: {e}", err=True)
        sys.exit(1)

    click.echo(f"Connected to '{config.server_name}'", err=True)

    # 2. Discover tools
    click.echo("Discovering tools...", err=True)
    discovery = await discover_tools(connection, config)
    click.echo(f"Found {len(discovery.tools)} tools", err=True)

    # Show risk breakdown
    risk_counts: dict[str, int] = {}
    for tool in discovery.tools:
        risk_counts[tool.risk_tier] = risk_counts.get(tool.risk_tier, 0) + 1
    for tier in ["critical", "high", "medium", "low"]:
        if tier in risk_counts:
            click.echo(f"  {tier}: {risk_counts[tier]}", err=True)

    # 3. Build manifest and sync lockfile
    manifest = build_synthetic_manifest(discovery, config)
    server = OverlayServer(
        config=config,
        connection=connection,
        dry_run=dry_run,
        rules_path=Path(rules) if rules else None,
        circuit_breaker_path=Path(circuit_breaker) if circuit_breaker else None,
    )

    changes = server.sync_lockfile(manifest)
    new_count = len(changes.get("new", []))
    modified_count = len(changes.get("modified", []))

    if new_count:
        click.echo(f"\n{new_count} new tool(s) pending approval", err=True)
    if modified_count:
        click.echo(f"{modified_count} tool(s) changed, pending re-approval", err=True)

    # 4. Auto-approve low-risk if requested
    if config.auto_approve_safe:
        from toolwright.core.approval.lockfile import ApprovalStatus

        lockfile = server._lockfile_manager
        if lockfile and lockfile.lockfile:
            approved_count = 0
            for tool_approval in lockfile.lockfile.tools.values():
                if (
                    tool_approval.status == ApprovalStatus.PENDING
                    and tool_approval.risk_tier == "low"
                ):
                    tool_approval.status = ApprovalStatus.APPROVED
                    tool_approval.approved_by = "auto:low-risk"
                    approved_count += 1
            if approved_count:
                lockfile.save()
                click.echo(f"Auto-approved {approved_count} low-risk tool(s)", err=True)

    # 5. Load approved tools
    server.load_tools_from_discovery(discovery)
    approved = len(server.actions)
    total = len(discovery.tools)
    click.echo(f"\nServing {approved}/{total} approved tools", err=True)

    if approved == 0:
        click.echo(
            "\nNo tools approved yet. Use 'toolwright gate allow <tool>' to approve tools.",
            err=True,
        )
        await connection.close()
        return

    # 6. Print client config
    client_config = build_client_config(config, proxy_port=port)
    click.echo("\n--- Client Configuration ---", err=True)
    click.echo("\nClaude Desktop (claude_desktop_config.json):", err=True)
    click.echo(json.dumps(client_config["claude_desktop"], indent=2), err=True)
    click.echo(f"\nClaude Code:\n  {client_config['claude_code']}", err=True)

    # 7. Run server
    if dry_run:
        click.echo("\n[dry-run] Would start MCP server. Exiting.", err=True)
        await connection.close()
        return

    click.echo(f"\nStarting Toolwright overlay proxy for '{config.server_name}'...", err=True)
    try:
        if use_http:
            server.run_http(host="127.0.0.1", port=port)
        else:
            await server.run_stdio()
    finally:
        await connection.close()

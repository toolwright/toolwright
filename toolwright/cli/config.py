"""Config snippet command implementation."""

from __future__ import annotations

import sys

import click

from toolwright.core.config_snippets import render_mcp_client_config


def run_config(
    toolpack_path: str,
    fmt: str,
    *,
    name_override: str | None = None,
    command_override: str | None = None,
) -> None:
    """Emit an MCP client config snippet."""
    try:
        snippet = render_mcp_client_config(
            toolpack_path=toolpack_path,
            fmt=fmt,
            name_override=name_override,
            command_override=command_override,
        )
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    click.echo(snippet)

    # Show helpful context on stderr so it doesn't pollute piped output
    import os
    import platform
    _CLIENT_PATHS = {
        "Darwin": "~/Library/Application Support/Claude/claude_desktop_config.json",
        "Linux": "~/.config/Claude/claude_desktop_config.json",
        "Windows": "%APPDATA%/Claude/claude_desktop_config.json",
    }
    target = _CLIENT_PATHS.get(platform.system())
    if target:
        expanded = os.path.expanduser(target)
        click.echo(f"\nPaste into: {expanded}", err=True)
        click.echo("Then restart Claude Desktop to apply.", err=True)

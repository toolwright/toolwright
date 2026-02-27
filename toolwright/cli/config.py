"""Config snippet command implementation."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from toolwright.core.toolpack import Toolpack, load_toolpack
from toolwright.utils.config import build_mcp_config_payload, render_config_payload


def run_config(toolpack_path: str, fmt: str, *, name_override: str | None = None) -> None:
    """Emit an MCP client config snippet."""
    try:
        toolpack = load_toolpack(Path(toolpack_path))
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    server_name = name_override or _derive_server_name(toolpack)
    payload = build_mcp_config_payload(
        toolpack_path=Path(toolpack_path),
        server_name=server_name,
    )
    click.echo(render_config_payload(payload, fmt))


def _derive_server_name(toolpack: Toolpack) -> str:
    """Derive a human-readable MCP server name from toolpack metadata."""
    from urllib.parse import urlparse

    if toolpack.origin:
        if toolpack.origin.name:
            base = toolpack.origin.name.strip().lower().replace(" ", "-")
            sanitized = "".join(ch for ch in base if ch.isalnum() or ch in {"-", "_"})
            if sanitized:
                return sanitized
        if toolpack.origin.start_url:
            host = urlparse(toolpack.origin.start_url).netloc
            if host:
                return host.replace(".", "-").replace(":", "-")
    return toolpack.toolpack_id

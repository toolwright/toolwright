"""Shared MCP client config rendering for CLI and UI surfaces."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from toolwright.core.toolpack import Toolpack, load_toolpack
from toolwright.utils.config import build_mcp_config_payload, render_config_payload


def render_mcp_client_config(
    toolpack_path: str | Path,
    fmt: str,
    *,
    name_override: str | None = None,
    command_override: str | None = None,
) -> str:
    """Render an MCP client config snippet for a toolpack."""
    resolved_path = Path(toolpack_path)
    toolpack = load_toolpack(resolved_path)
    server_name = name_override or derive_server_name(toolpack)
    payload = build_mcp_config_payload(
        toolpack_path=resolved_path,
        server_name=server_name,
        command_override=command_override,
    )
    return render_config_payload(payload, fmt)


def derive_server_name(toolpack: Toolpack) -> str:
    """Derive a human-readable MCP server name from toolpack metadata."""
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

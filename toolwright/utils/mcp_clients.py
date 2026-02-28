"""MCP client detection and config installation.

Detects Claude Desktop and Cursor config files on macOS, Linux, and Windows.
Safely merges Toolwright server config into existing client configs.
"""

from __future__ import annotations

import json
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MCPClient:
    """A detected MCP client with its config file path."""

    name: str
    config_path: Path


def detect_mcp_clients(*, home_override: Path | None = None) -> list[MCPClient]:
    """Detect installed MCP clients by checking for config files.

    Checks standard locations for Claude Desktop and Cursor on all platforms.
    """
    home = home_override or Path.home()
    system = platform.system()

    candidates: list[tuple[str, Path]] = []

    # Claude Desktop
    if system == "Darwin":
        candidates.append((
            "Claude Desktop",
            home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        ))
    elif system == "Linux":
        candidates.append((
            "Claude Desktop",
            home / ".config" / "Claude" / "claude_desktop_config.json",
        ))
    elif system == "Windows":
        appdata = Path(home) / "AppData" / "Roaming"
        candidates.append((
            "Claude Desktop",
            appdata / "Claude" / "claude_desktop_config.json",
        ))

    # Cursor (same on all platforms)
    candidates.append(("Cursor", home / ".cursor" / "mcp.json"))

    return [
        MCPClient(name=name, config_path=path)
        for name, path in candidates
        if path.exists()
    ]


def install_config(
    client: MCPClient,
    *,
    server_name: str,
    toolpack_path: Path,
) -> None:
    """Install Toolwright MCP server config into a client's config file.

    Creates a backup (.bak) before modifying. Merges the new server entry
    into existing mcpServers. Refuses if the config file can't be parsed.
    """
    config_path = client.config_path

    # Read and parse existing config
    raw = config_path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"Could not parse {config_path}: {exc}"
        raise ValueError(msg) from exc

    # Create backup
    backup_path = config_path.with_suffix(config_path.suffix + ".bak")
    shutil.copy2(config_path, backup_path)

    # Ensure mcpServers key exists
    if "mcpServers" not in data:
        data["mcpServers"] = {}

    # Add the Toolwright server entry
    data["mcpServers"][server_name] = {
        "command": "toolwright",
        "args": ["serve", "--toolpack", str(toolpack_path)],
    }

    # Write back
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def uninstall_config(
    client: MCPClient,
    *,
    server_name: str,
) -> None:
    """Remove a Toolwright server entry from a client's config file."""
    config_path = client.config_path
    raw = config_path.read_text(encoding="utf-8")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    servers = data.get("mcpServers", {})
    if server_name in servers:
        del servers[server_name]
        config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

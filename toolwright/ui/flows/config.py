"""Interactive config flow (MVP: snippet + guidance, no auto-apply)."""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from toolwright.ui.console import err_console
from toolwright.ui.discovery import find_toolpacks
from toolwright.ui.echo import echo_plan, echo_summary
from toolwright.ui.prompts import select_one

# Known MCP client config paths by platform
_CLIENT_CONFIG_PATHS: dict[str, dict[str, str]] = {
    "Claude Desktop": {
        "Darwin": "~/Library/Application Support/Claude/claude_desktop_config.json",
        "Linux": "~/.config/Claude/claude_desktop_config.json",
        "Windows": "%APPDATA%/Claude/claude_desktop_config.json",
    },
    "Claude Code": {
        "Darwin": "~/.claude.json",
        "Linux": "~/.claude.json",
        "Windows": "~/.claude.json",
    },
    "Cursor": {
        "Darwin": "~/.cursor/mcp.json",
        "Linux": "~/.cursor/mcp.json",
        "Windows": "~/.cursor/mcp.json",
    },
}


def config_flow(
    *,
    toolpack_path: str | None = None,
    root: Path | None = None,
    ctx: Any = None,  # noqa: ARG001
    missing_param: str | None = None,  # noqa: ARG001
) -> None:
    """Generate MCP client config snippet with guidance."""
    con = err_console

    if root is None:
        root = Path(".toolwright")

    con.print()
    con.print("[heading]Generate MCP Client Config[/heading]")
    con.print()

    # Resolve toolpack
    if toolpack_path is None:
        candidates = find_toolpacks(root)
        if not candidates:
            con.print("[error]No toolpacks found.[/error]")
            return
        if len(candidates) == 1:
            toolpack_path = str(candidates[0])
        else:
            toolpack_path = select_one(
                [str(p) for p in candidates],
                prompt="Select toolpack",
                console=con,
            )

    # Choose client
    clients = ["Claude Desktop", "Claude Code", "Cursor", "Codex", "Generic JSON"]
    client = select_one(clients, prompt="Target MCP client", console=con)

    # Choose format
    fmt = "codex" if client == "Codex" else "json"

    # Plan
    cmd = ["toolwright", "config", "--toolpack", toolpack_path, "--format", fmt]
    echo_plan([cmd], console=con)

    # Generate snippet
    try:
        from toolwright.cli.config import run_config

        con.print()
        run_config(toolpack_path=toolpack_path, fmt=fmt)
    except SystemExit:
        pass
    except Exception as exc:
        con.print(f"[error]Config generation failed: {exc}[/error]")
        return

    # Show target config path
    system = platform.system()
    paths = _CLIENT_CONFIG_PATHS.get(client, {})
    target_path = paths.get(system)
    if target_path:
        expanded = Path(target_path).expanduser()
        con.print()
        con.print(f"[heading]Target config file:[/heading] {expanded}")
        con.print("[muted]Copy the snippet above into that file.[/muted]")
        con.print("[muted]Back up your existing config first.[/muted]")

    echo_summary([cmd], console=con)

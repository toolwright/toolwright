"""MCP client config snippet helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


def _resolve_toolwright_command() -> str:
    """Return the short ``toolwright`` command name.

    Users install toolwright via ``pip install toolwright`` which places
    ``toolwright`` on PATH.  Emitting an absolute path (especially a
    virtualenv path) makes the config non-portable and confusing.
    """
    return "toolwright"


def _infer_state_root(toolpack_dir: Path) -> Path:
    """Infer the .toolwright state root from a toolpack directory.

    Standard layout: ``<project>/.toolwright/toolpacks/<name>/toolpack.yaml``
    In that case the state root is ``<project>/.toolwright``.

    Fallback: create a ``.toolwright`` directory inside the toolpack dir.
    """
    # Standard layout: .toolwright/toolpacks/<name>/
    if toolpack_dir.parent.name == "toolpacks":
        grandparent = toolpack_dir.parent.parent  # e.g. .toolwright
        if grandparent.name == ".toolwright":
            return grandparent.resolve()

    # Fallback: toolpack-local .toolwright
    return (toolpack_dir / ".toolwright").resolve()


def build_mcp_config_payload(
    *,
    toolpack_path: Path,
    server_name: str,
    portable: bool = False,
    command_override: str | None = None,
) -> dict[str, Any]:
    """Build a config payload for MCP clients.

    Args:
        toolpack_path: Path to toolpack.yaml
        server_name: Server name for the MCP config
        portable: If True, emit relative paths suitable for bundles
            that will be extracted to a different location.
        command_override: If set, use this as the command instead of
            the default ``toolwright``.
    """
    if portable:
        return {
            "mcpServers": {
                server_name: {
                    "command": command_override or "toolwright",
                    "args": [
                        "--root",
                        ".toolwright",
                        "serve",
                        "--toolpack",
                        "toolpack.yaml",
                    ],
                }
            }
        }

    toolpack_abs = toolpack_path.resolve()
    toolpack_root = toolpack_abs.parent
    state_root = _infer_state_root(toolpack_root)
    command = command_override or _resolve_toolwright_command()

    return {
        "mcpServers": {
            server_name: {
                "command": command,
                "args": [
                    "--root",
                    str(state_root),
                    "serve",
                    "--toolpack",
                    str(toolpack_abs),
                ],
            }
        }
    }


def render_config_payload(payload: dict[str, Any], fmt: str) -> str:
    """Render config payload to json, yaml, or Codex TOML."""
    if fmt == "codex":
        servers = payload.get("mcpServers")
        if not isinstance(servers, dict) or not servers:
            raise ValueError("Invalid MCP config payload: missing mcpServers")

        def _toml_key_segment(key: str) -> str:
            if re.fullmatch(r"[A-Za-z0-9_-]+", key):
                return key
            # Use JSON string quoting for TOML basic string escape compatibility.
            return json.dumps(key)

        def _toml_quote(value: str) -> str:
            return json.dumps(value)

        stanzas: list[str] = []
        for server_name, server in servers.items():
            if not isinstance(server_name, str) or not isinstance(server, dict):
                continue
            command = server.get("command")
            args = server.get("args")
            if not isinstance(command, str) or not isinstance(args, list) or not all(
                isinstance(item, str) for item in args
            ):
                raise ValueError("Invalid MCP config payload: server missing command/args")

            header = f"[mcp_servers.{_toml_key_segment(server_name)}]"
            rendered_args = ", ".join(_toml_quote(item) for item in args)
            stanzas.append(
                "\n".join(
                    [
                        header,
                        f"args = [{rendered_args}]",
                        f"command = {_toml_quote(command)}",
                        "enabled = true",
                    ]
                )
            )

        return "\n\n".join(stanzas) + "\n"

    if fmt == "yaml":
        return yaml.safe_dump(payload, sort_keys=True)
    return json.dumps(payload, indent=2, sort_keys=True)

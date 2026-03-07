"""Configuration persistence and server name derivation for overlay mode."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from toolwright.models.overlay import TargetType, WrapConfig

_CONFIG_FILENAME = "wrap.yaml"

# Prefixes to strip from package names to get a clean server name
_NAME_STRIP_PREFIXES = ["mcp-server-", "server-"]


def derive_server_name(command: str, args: list[str]) -> str:
    """Extract a clean server name from a command + args pattern.

    Examples:
        npx -y @modelcontextprotocol/server-github → "github"
        npx -y mcp-server-fetch → "fetch"
        python -m my_mcp_server → "my-mcp-server"
        docker run -i mcp/postgres → "postgres"
    """
    # For npx: find the package name argument (skip flags like -y)
    if command in ("npx", "npx.cmd"):
        for arg in args:
            if arg.startswith("-"):
                continue
            return _clean_package_name(arg)

    # For docker: find the image name (skip flags)
    if command in ("docker", "docker.exe"):
        # Look for image name after 'run' and flags
        past_run = False
        for arg in args:
            if arg == "run":
                past_run = True
                continue
            if past_run and not arg.startswith("-"):
                # Docker image like mcp/postgres → postgres
                return arg.split("/")[-1].split(":")[0]

    # For python -m module: use module name
    if command in ("python", "python3", sys.executable):
        for i, arg in enumerate(args):
            if arg == "-m" and i + 1 < len(args):
                return args[i + 1].replace("_", "-")

    # Fallback: use the command itself
    return Path(command).stem


def _clean_package_name(package: str) -> str:
    """Clean an npm package name to a short server name.

    @modelcontextprotocol/server-github → github
    @anthropic/mcp-server-brave → brave
    mcp-server-fetch → fetch
    server-filesystem → filesystem
    """
    # Strip scope (@org/)
    if "/" in package:
        package = package.rsplit("/", 1)[-1]

    # Strip known prefixes
    for prefix in _NAME_STRIP_PREFIXES:
        if package.startswith(prefix):
            package = package[len(prefix):]
            break

    return package


def save_wrap_config(config: WrapConfig) -> None:
    """Persist WrapConfig to .toolwright/wrap/<name>/wrap.yaml."""
    config.state_dir.mkdir(parents=True, exist_ok=True)
    config_path = config.state_dir / _CONFIG_FILENAME

    data = {
        "server_name": config.server_name,
        "target_type": config.target_type.value,
        "command": config.command,
        "args": config.args,
        "env": config.env,
        "url": config.url,
        "headers": config.headers,
        "auto_approve_safe": config.auto_approve_safe,
        "proxy_transport": config.proxy_transport,
    }

    config_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def load_wrap_config(
    state_dir: Path | None = None,
    wrap_root: Path | None = None,
) -> WrapConfig | None:
    """Load a WrapConfig from disk.

    Args:
        state_dir: Direct path to a wrap state directory
        wrap_root: Parent wrap directory; auto-detects if only one config exists
    """
    if state_dir is not None:
        config_path = state_dir / _CONFIG_FILENAME
        if config_path.exists():
            return _load_from_file(config_path, state_dir)
        return None

    if wrap_root is not None:
        if not wrap_root.exists():
            return None
        subdirs = [d for d in wrap_root.iterdir() if d.is_dir() and (d / _CONFIG_FILENAME).exists()]
        if len(subdirs) == 1:
            return _load_from_file(subdirs[0] / _CONFIG_FILENAME, subdirs[0])
        return None

    return None


def _load_from_file(config_path: Path, state_dir: Path) -> WrapConfig:
    """Load WrapConfig from a YAML file."""
    data = yaml.safe_load(config_path.read_text())
    return WrapConfig(
        server_name=data["server_name"],
        target_type=TargetType(data["target_type"]),
        command=data.get("command"),
        args=data.get("args", []),
        env=data.get("env", {}),
        url=data.get("url"),
        headers=data.get("headers", {}),
        auto_approve_safe=data.get("auto_approve_safe", False),
        proxy_transport=data.get("proxy_transport", "stdio"),
        state_dir=state_dir,
    )


def build_client_config(config: WrapConfig, proxy_port: int = 8745) -> dict[str, Any]:
    """Build copy-pasteable client configuration blocks.

    Returns dict with keys: claude_desktop, claude_code
    """
    name = config.server_name

    # Claude Desktop config (stdio)
    claude_desktop: dict[str, Any] = {
        "mcpServers": {
            name: {
                "command": "toolwright",
                "args": ["wrap", "--name", name],
            }
        }
    }

    # Claude Code command
    import json as _json

    stdio_json = _json.dumps({"command": "toolwright", "args": ["wrap", "--name", name]})
    claude_code = f"claude mcp add-json {name} '{stdio_json}'"

    if config.proxy_transport == "http":
        claude_desktop = {
            "mcpServers": {
                name: {
                    "url": f"http://127.0.0.1:{proxy_port}/mcp",
                }
            }
        }
        http_json = _json.dumps({"url": f"http://127.0.0.1:{proxy_port}/mcp"})
        claude_code = f"claude mcp add-json {name} '{http_json}'"

    return {
        "claude_desktop": claude_desktop,
        "claude_code": claude_code,
    }

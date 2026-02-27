"""Optional dependency checks for runtime CLI paths."""

from __future__ import annotations

import importlib.util
import sys

import click

MCP_MISSING_ERROR = 'Error: mcp not installed. Install with: pip install "toolwright[mcp]"'


def has_mcp_dependency() -> bool:
    """Return True when the real `mcp` package is import-discoverable."""
    try:
        spec = importlib.util.find_spec("mcp")
    except (ImportError, ValueError):
        return False
    return spec is not None


def require_mcp_dependency() -> None:
    """Exit with a single actionable line when `mcp` is unavailable."""
    if has_mcp_dependency():
        return
    click.echo(MCP_MISSING_ERROR, err=True)
    sys.exit(1)

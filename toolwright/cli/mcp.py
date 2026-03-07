"""Compatibility wrapper for MCP runtime helpers.

This module preserves existing import paths while the MCP serve
implementation now lives under ``toolwright.mcp``.
"""

from __future__ import annotations

from toolwright.mcp.runtime import (
    check_jsonschema_available,
    check_tool_count_guardrails,
    run_mcp_serve,
    stdio_transport_warning,
    warn_missing_auth,
)

__all__ = [
    "check_jsonschema_available",
    "check_tool_count_guardrails",
    "run_mcp_serve",
    "stdio_transport_warning",
    "warn_missing_auth",
]

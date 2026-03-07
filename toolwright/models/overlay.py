"""Data models for overlay mode (toolwright wrap)."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class TargetType(StrEnum):
    """Type of upstream MCP server to wrap."""

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class WrapConfig(BaseModel):
    """Configuration for wrapping an upstream MCP server."""

    server_name: str
    target_type: TargetType
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    auto_approve_safe: bool = False
    state_dir: Path
    proxy_transport: str = "stdio"

    @property
    def lockfile_path(self) -> Path:
        return self.state_dir / "lockfile.yaml"


class WrappedTool(BaseModel):
    """A tool discovered from an upstream MCP server."""

    name: str
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)
    risk_tier: str = "high"
    tool_def_digest: str = ""
    confirmation_required: str = "never"


class SourceInfo(BaseModel):
    """Information about the source code of a wrapped server."""

    source_type: str
    source_path: str
    editable: bool


class DiscoveryResult(BaseModel):
    """Result of discovering tools from an upstream MCP server."""

    tools: list[WrappedTool] = Field(default_factory=list)
    server_name: str
    server_version: str | None = None


def compute_tool_def_digest(
    name: str,
    description: str | None,
    input_schema: dict[str, Any] | None,
    annotations: dict[str, Any] | None,
) -> str:
    """Compute a deterministic digest of a tool's definition.

    Used to detect upstream tool changes that require re-approval.
    """
    canonical = json.dumps(
        {
            "name": name,
            "description": description or "",
            "inputSchema": input_schema or {},
            "annotations": annotations or {},
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]

"""Tool discovery, risk classification, and manifest generation for overlay mode.

Connects to an upstream MCP server, enumerates its tools, classifies risk
using heuristics + MCP annotations, and produces a synthetic manifest
compatible with the existing lockfile/pipeline infrastructure.
"""

from __future__ import annotations

from typing import Any

from toolwright.models.overlay import (
    DiscoveryResult,
    WrapConfig,
    WrappedTool,
    compute_tool_def_digest,
)
from toolwright.utils.schema_version import CURRENT_SCHEMA_VERSION

# -- Risk classification patterns --

_CRITICAL_PATTERNS = ["delete", "remove", "destroy", "drop", "purge", "revoke"]
_HIGH_PATTERNS = [
    "create", "update", "modify", "write", "send", "push",
    "execute", "run", "invoke", "trigger", "deploy",
]
_LOW_PATTERNS = ["get", "list", "read", "search", "find", "query", "fetch"]


def classify_risk(mcp_tool: Any) -> str:
    """Classify risk tier from tool name heuristics + MCP annotations.

    Returns: "critical", "high", "medium", or "low".

    Logic:
    - Critical: destructive keywords in name always win
    - High: state-changing keywords in name
    - Low: read-only keywords ONLY if annotations don't contradict
    - Medium: read-only keywords but annotations indicate destructive
    - Default: high (conservative for opaque tools)
    """
    name = mcp_tool.name.lower()
    annotations = getattr(mcp_tool, "annotations", None)

    read_only_hint = None
    destructive_hint = None
    if annotations is not None:
        read_only_hint = getattr(annotations, "readOnlyHint", None)
        destructive_hint = getattr(annotations, "destructiveHint", None)

    # Critical patterns always win
    if any(p in name for p in _CRITICAL_PATTERNS):
        return "critical"

    # High patterns
    if any(p in name for p in _HIGH_PATTERNS):
        return "high"

    # Low only if BOTH heuristics AND hints agree
    if any(p in name for p in _LOW_PATTERNS):
        # If annotations explicitly say destructive and NOT readOnly → medium
        if destructive_hint is True and not read_only_hint:
            return "medium"
        return "low"

    return "high"


def tool_def_digest(mcp_tool: Any) -> str:
    """Compute a deterministic digest of an MCP tool's definition."""
    annotations = getattr(mcp_tool, "annotations", None)
    annotations_dict: dict[str, Any] = {}
    if annotations is not None:
        # Try to convert annotations object to dict
        if hasattr(annotations, "model_dump"):
            annotations_dict = annotations.model_dump()
        elif isinstance(annotations, dict):
            annotations_dict = annotations
    return compute_tool_def_digest(
        name=mcp_tool.name,
        description=getattr(mcp_tool, "description", None),
        input_schema=getattr(mcp_tool, "inputSchema", None),
        annotations=annotations_dict,
    )


async def discover_tools(conn: Any, config: WrapConfig) -> DiscoveryResult:
    """Enumerate tools from upstream, classify risk, compute digests."""
    mcp_tools = await conn.list_tools()

    wrapped_tools: list[WrappedTool] = []
    for mcp_tool in mcp_tools:
        risk = classify_risk(mcp_tool)
        digest = tool_def_digest(mcp_tool)
        confirmation = "always" if risk == "critical" else "never"

        annotations = getattr(mcp_tool, "annotations", None)
        annotations_dict: dict[str, Any] = {}
        if annotations is not None:
            if hasattr(annotations, "model_dump"):
                annotations_dict = annotations.model_dump()
            elif isinstance(annotations, dict):
                annotations_dict = annotations

        wrapped_tools.append(
            WrappedTool(
                name=mcp_tool.name,
                description=getattr(mcp_tool, "description", None),
                input_schema=getattr(mcp_tool, "inputSchema", None) or {},
                annotations=annotations_dict,
                risk_tier=risk,
                tool_def_digest=digest,
                confirmation_required=confirmation,
            )
        )

    return DiscoveryResult(
        tools=wrapped_tools,
        server_name=config.server_name,
    )


def build_synthetic_manifest(
    discovery: DiscoveryResult,
    config: WrapConfig,
) -> dict[str, Any]:
    """Build a tools.json-compatible manifest from discovered tools.

    Each action gets synthetic HTTP-like fields that the pipeline expects:
    - method="MCP" (won't match HTTP-method heuristics, by design)
    - path="mcp://<server_name>/<tool_name>"
    - host=<server_name>
    - signature_id=tool_def_digest (enables lockfile change detection)
    """
    actions: list[dict[str, Any]] = []
    for tool in discovery.tools:
        actions.append({
            "name": tool.name,
            "tool_id": tool.name,
            "signature_id": tool.tool_def_digest,
            "method": "MCP",
            "path": f"mcp://{config.server_name}/{tool.name}",
            "host": config.server_name,
            "description": tool.description or "",
            "input_schema": tool.input_schema,
            "risk_tier": tool.risk_tier,
            "confirmation_required": tool.confirmation_required,
        })

    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "actions": actions,
    }

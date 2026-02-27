"""Meta MCP server that exposes Toolwright itself as tools.

This server allows AI agents to use Toolwright capabilities directly:
- List actions from a manifest
- Evaluate policy for actions
- Check approval status
- Detect drift between captures

Use this when you want agents to have governance capabilities over tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from toolwright.core.approval import ApprovalStatus, LockfileManager
from toolwright.core.audit import AuditLogger, MemoryAuditBackend
from toolwright.core.enforce import Enforcer
from toolwright.mcp._compat import (
    InitializationOptions,
    NotificationOptions,
    Server,
    mcp_stdio,
)
from toolwright.mcp._compat import (
    mcp_types as types,
)
from toolwright.utils.schema_version import resolve_schema_version

logger = logging.getLogger(__name__)


class ToolwrightMetaMCPServer:
    """MCP server that exposes Toolwright governance tools.

    This "meta" server allows agents to:
    - List and inspect available actions
    - Check if actions would be allowed by policy
    - View approval status of tools
    - Detect drift between API versions

    This enables agents to be governance-aware and make informed decisions
    about which tools to use.
    """

    def __init__(
        self,
        artifacts_dir: str | Path | None = None,
        tools_path: str | Path | None = None,
        policy_path: str | Path | None = None,
        lockfile_path: str | Path | None = None,
    ) -> None:
        """Initialize the meta MCP server.

        Args:
            artifacts_dir: Directory containing Toolwright artifacts
            tools_path: Path to tools.json (overrides artifacts_dir)
            policy_path: Path to policy.yaml (overrides artifacts_dir)
            lockfile_path: Path to lockfile (default: ./toolwright.lock.yaml)
        """
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else None

        # Resolve paths
        self.tools_path: Path | None
        if tools_path:
            self.tools_path = Path(tools_path)
        elif self.artifacts_dir:
            self.tools_path = self.artifacts_dir / "tools.json"
        else:
            self.tools_path = None

        self.policy_path: Path | None
        if policy_path:
            self.policy_path = Path(policy_path)
        elif self.artifacts_dir:
            self.policy_path = self.artifacts_dir / "policy.yaml"
        else:
            self.policy_path = None

        self.lockfile_path: Path | None = Path(lockfile_path) if lockfile_path else None

        # Load manifest if available
        self.manifest: dict[str, Any] | None = None
        if self.tools_path and self.tools_path.exists():
            with open(self.tools_path) as f:
                self.manifest = json.load(f)
            resolve_schema_version(
                self.manifest,
                artifact="tools manifest",
                allow_legacy=True,
            )

        # Set up enforcer if policy exists
        self.enforcer: Enforcer | None = None
        if self.policy_path and self.policy_path.exists():
            audit_logger = AuditLogger(MemoryAuditBackend())
            self.enforcer = Enforcer.from_file(str(self.policy_path), audit_logger)

        # Create MCP server
        self.server = Server("toolwright-meta")

        # Register handlers
        self._register_handlers()

        logger.info("Initialized Toolwright Meta MCP server")

    def _register_handlers(self) -> None:
        """Register MCP protocol handlers."""

        @self.server.list_tools()  # type: ignore
        async def handle_list_tools() -> list[types.Tool]:
            """Return Toolwright meta tools."""
            return [
                types.Tool(
                    name="toolwright_list_actions",
                    description="List all available actions from the Toolwright manifest with their risk tiers and approval status",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "filter_risk": {
                                "type": "string",
                                "enum": ["low", "medium", "high", "critical"],
                                "description": "Filter actions by risk tier",
                            },
                            "filter_method": {
                                "type": "string",
                                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                                "description": "Filter actions by HTTP method",
                            },
                            "filter_status": {
                                "type": "string",
                                "enum": ["pending", "approved", "rejected"],
                                "description": "Filter actions by approval status",
                            },
                        },
                    },
                ),
                types.Tool(
                    name="toolwright_check_policy",
                    description="Check if an action would be allowed by the current policy",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "action_name": {
                                "type": "string",
                                "description": "Name of the action to check",
                            },
                        },
                        "required": ["action_name"],
                    },
                ),
                types.Tool(
                    name="toolwright_get_approval_status",
                    description="Get the approval status of an action",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "action_name": {
                                "type": "string",
                                "description": "Name of the action to check",
                            },
                        },
                        "required": ["action_name"],
                    },
                ),
                types.Tool(
                    name="toolwright_list_pending_approvals",
                    description="List all actions pending approval",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                types.Tool(
                    name="toolwright_get_action_details",
                    description="Get detailed information about a specific action",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "action_name": {
                                "type": "string",
                                "description": "Name of the action",
                            },
                        },
                        "required": ["action_name"],
                    },
                ),
                types.Tool(
                    name="toolwright_risk_summary",
                    description="Get a summary of actions by risk tier",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                types.Tool(
                    name="toolwright_get_flows",
                    description="Get detected API flow sequences (dependencies between endpoints).",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
            ]

        @self.server.call_tool()  # type: ignore
        async def handle_call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
            """Handle meta tool execution."""
            arguments = arguments or {}

            if name == "toolwright_list_actions":
                return await self._list_actions(arguments)
            elif name == "toolwright_check_policy":
                return await self._check_policy(arguments)
            elif name == "toolwright_get_approval_status":
                return await self._get_approval_status(arguments)
            elif name == "toolwright_list_pending_approvals":
                return await self._list_pending_approvals()
            elif name == "toolwright_get_action_details":
                return await self._get_action_details(arguments)
            elif name == "toolwright_risk_summary":
                return await self._risk_summary()
            elif name == "toolwright_get_flows":
                return await self._get_flows(arguments)
            else:
                return [types.TextContent(
                    type="text",
                    text=json.dumps({"error": f"Unknown tool: {name}"})
                )]

    async def _list_actions(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """List actions with optional filtering."""
        if not self.manifest:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "No manifest loaded"})
            )]

        actions = self.manifest.get("actions", [])

        # Apply filters
        filter_risk = arguments.get("filter_risk")
        filter_method = arguments.get("filter_method")
        filter_status = arguments.get("filter_status")

        # Load lockfile for status filtering (always load to show status)
        lockfile_manager = LockfileManager(self.lockfile_path)
        if lockfile_manager.exists():
            lockfile_manager.load()

        result = []
        for action in actions:
            # Filter by risk
            if filter_risk and action.get("risk_tier") != filter_risk:
                continue

            # Filter by method
            if filter_method and action.get("method") != filter_method:
                continue

            # Get approval status
            status = "unknown"
            if lockfile_manager and lockfile_manager.lockfile:
                action_signature = str(action.get("signature_id", ""))
                tool_approval = (
                    lockfile_manager.get_tool(action_signature)
                    if action_signature
                    else None
                )
                if not tool_approval:
                    tool_approval = lockfile_manager.get_tool(action["name"])
                if tool_approval:
                    status = tool_approval.status.value

            # Filter by status
            if filter_status and status != filter_status:
                continue

            result.append({
                "name": action["name"],
                "method": action.get("method", "GET"),
                "path": action.get("path", "/"),
                "risk_tier": action.get("risk_tier", "low"),
                "approval_status": status,
                "description": action.get("description", ""),
            })

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "total": len(result),
                "actions": result,
            }, indent=2)
        )]

    async def _check_policy(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Check if an action would be allowed by policy."""
        action_name = arguments.get("action_name")
        if not action_name:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "action_name is required"})
            )]

        if not self.manifest:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "No manifest loaded"})
            )]

        # Find action
        action = None
        for a in self.manifest.get("actions", []):
            if a["name"] == action_name:
                action = a
                break

        if not action:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": f"Action not found: {action_name}"})
            )]

        if not self.enforcer:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "action": action_name,
                    "policy_loaded": False,
                    "message": "No policy loaded - action would be allowed by default",
                })
            )]

        # Evaluate policy
        result = self.enforcer.evaluate(
            method=action.get("method", "GET"),
            path=action.get("path", "/"),
            host=action.get("host", ""),
            action_id=action_name,
            risk_tier=action.get("risk_tier", "low"),
        )

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "action": action_name,
                "allowed": result.allowed,
                "requires_confirmation": result.requires_confirmation,
                "confirmation_message": result.confirmation_message,
                "reason": result.reason,
                "matched_rule": result.rule_id,
            }, indent=2)
        )]

    async def _get_approval_status(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Get approval status for an action."""
        action_name = arguments.get("action_name")
        if not action_name:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "action_name is required"})
            )]

        manager = LockfileManager(self.lockfile_path)
        if not manager.exists():
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "action": action_name,
                    "status": "no_lockfile",
                    "message": "No lockfile found - run 'toolwright gate sync' first",
                })
            )]

        manager.load()
        action_signature = ""
        if self.manifest:
            for action in self.manifest.get("actions", []):
                if action.get("name") == action_name:
                    action_signature = str(action.get("signature_id", ""))
                    break

        tool = manager.get_tool(action_signature) if action_signature else None
        if not tool:
            tool = manager.get_tool(action_name)

        if not tool:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "action": action_name,
                    "status": "not_found",
                    "message": f"Action '{action_name}' not found in lockfile",
                })
            )]

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "action": action_name,
                "status": tool.status.value,
                "risk_tier": tool.risk_tier,
                "approved_by": tool.approved_by,
                "approved_at": tool.approved_at.isoformat() if tool.approved_at else None,
                "rejection_reason": tool.rejection_reason,
                "version": tool.tool_version,
            }, indent=2)
        )]

    async def _list_pending_approvals(self) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """List all pending approvals."""
        manager = LockfileManager(self.lockfile_path)
        if not manager.exists():
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "error": "No lockfile found - run 'toolwright gate sync' first",
                })
            )]

        manager.load()
        pending = manager.get_pending()

        result = []
        for tool in pending:
            result.append({
                "name": tool.name,
                "method": tool.method,
                "path": tool.path,
                "risk_tier": tool.risk_tier,
                "change_type": tool.change_type,
            })

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "total_pending": len(result),
                "pending_actions": result,
                "message": f"{len(result)} action(s) require approval before use",
            }, indent=2)
        )]

    async def _get_action_details(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Get detailed information about an action."""
        action_name = arguments.get("action_name")
        if not action_name:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "action_name is required"})
            )]

        if not self.manifest:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "No manifest loaded"})
            )]

        # Find action
        action = None
        for a in self.manifest.get("actions", []):
            if a["name"] == action_name:
                action = a
                break

        if not action:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": f"Action not found: {action_name}"})
            )]

        # Get approval status if available
        approval_info = {}
        manager = LockfileManager(self.lockfile_path)
        if manager.exists():
            manager.load()
            action_signature = str(action.get("signature_id", ""))
            tool = manager.get_tool(action_signature) if action_signature else None
            if not tool:
                tool = manager.get_tool(action_name)
            if tool:
                approval_info = {
                    "approval_status": tool.status.value,
                    "approved_by": tool.approved_by,
                    "approved_at": tool.approved_at.isoformat() if tool.approved_at else None,
                }

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "name": action["name"],
                "method": action.get("method", "GET"),
                "path": action.get("path", "/"),
                "host": action.get("host", ""),
                "description": action.get("description", ""),
                "risk_tier": action.get("risk_tier", "low"),
                "input_schema": action.get("input_schema", {}),
                "output_schema": action.get("output_schema"),
                "confirmation_required": action.get("confirmation_required", "never"),
                **approval_info,
            }, indent=2)
        )]

    async def _risk_summary(self) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Get summary of actions by risk tier."""
        if not self.manifest:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "No manifest loaded"})
            )]

        actions = self.manifest.get("actions", [])

        # Count by risk tier
        by_risk: dict[str, list[str]] = {
            "low": [],
            "medium": [],
            "high": [],
            "critical": [],
        }

        for action in actions:
            risk = action.get("risk_tier", "low")
            if risk in by_risk:
                by_risk[risk].append(action["name"])

        # Get approval summary
        approval_summary = {"pending": 0, "approved": 0, "rejected": 0}
        manager = LockfileManager(self.lockfile_path)
        if manager.exists():
            manager.load()
            for tool in manager.lockfile.tools.values():  # type: ignore[union-attr]
                if tool.status == ApprovalStatus.PENDING:
                    approval_summary["pending"] += 1
                elif tool.status == ApprovalStatus.APPROVED:
                    approval_summary["approved"] += 1
                elif tool.status == ApprovalStatus.REJECTED:
                    approval_summary["rejected"] += 1

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "total_actions": len(actions),
                "by_risk_tier": {
                    "low": {"count": len(by_risk["low"]), "actions": by_risk["low"]},
                    "medium": {"count": len(by_risk["medium"]), "actions": by_risk["medium"]},
                    "high": {"count": len(by_risk["high"]), "actions": by_risk["high"]},
                    "critical": {"count": len(by_risk["critical"]), "actions": by_risk["critical"]},
                },
                "approval_summary": approval_summary,
            }, indent=2)
        )]

    async def _get_flows(
        self, _arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Get flow sequences from manifest."""
        if not self.manifest:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "No manifest loaded"})
            )]

        # Extract flow info from actions (depends_on/enables)
        flows: list[dict[str, Any]] = []
        for action in self.manifest.get("actions", []):
            deps = action.get("depends_on", [])
            enables = action.get("enables", [])
            if deps or enables:
                flows.append({
                    "action": action["name"],
                    "depends_on": deps,
                    "enables": enables,
                })

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "total_actions_with_flows": len(flows),
                "flows": flows,
            }, indent=2)
        )]

    async def run_stdio(self) -> None:
        """Run the server using stdio transport."""
        async with mcp_stdio.stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="toolwright-meta",
                    server_version="1.0.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )


def run_meta_server(
    artifacts_dir: str | None = None,
    tools_path: str | None = None,
    policy_path: str | None = None,
    lockfile_path: str | None = None,
) -> None:
    """Run the Toolwright Meta MCP server.

    Args:
        artifacts_dir: Directory containing Toolwright artifacts
        tools_path: Path to tools.json (overrides artifacts_dir)
        policy_path: Path to policy.yaml (overrides artifacts_dir)
        lockfile_path: Path to lockfile
    """
    server = ToolwrightMetaMCPServer(
        artifacts_dir=artifacts_dir,
        tools_path=tools_path,
        policy_path=policy_path,
        lockfile_path=lockfile_path,
    )

    asyncio.run(server.run_stdio())

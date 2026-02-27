"""Meta MCP server that exposes Toolwright itself as tools.

This server allows AI agents to use Toolwright capabilities directly:
- List actions from a manifest
- Evaluate policy for actions
- Check approval status
- Diagnose and repair tools (HEAL)
- Kill, enable, and quarantine tools (KILL)
- Add, list, and remove behavioral rules (CORRECT)

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
    - Diagnose and repair tools (HEAL)
    - Kill, enable, and quarantine tools (KILL)
    - Add, list, and remove behavioral rules (CORRECT)

    This enables agents to be governance-aware and make informed decisions
    about which tools to use.
    """

    def __init__(
        self,
        artifacts_dir: str | Path | None = None,
        tools_path: str | Path | None = None,
        policy_path: str | Path | None = None,
        lockfile_path: str | Path | None = None,
        circuit_breaker_path: str | Path | None = None,
        rules_path: str | Path | None = None,
        state_dir: str | Path | None = None,
    ) -> None:
        """Initialize the meta MCP server.

        Args:
            artifacts_dir: Directory containing Toolwright artifacts
            tools_path: Path to tools.json (overrides artifacts_dir)
            policy_path: Path to policy.yaml (overrides artifacts_dir)
            lockfile_path: Path to lockfile (default: ./toolwright.lock.yaml)
            circuit_breaker_path: Path to circuit breaker state file (KILL pillar)
            rules_path: Path to behavioral rules JSON file (CORRECT pillar)
            state_dir: Path to .toolwright/state/ for reconcile state and repair plans
        """
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else None
        self.state_dir: Path | None = Path(state_dir) if state_dir else None

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

        # KILL pillar: circuit breaker (optional)
        self.circuit_breaker: Any | None = None
        if circuit_breaker_path is not None:
            from toolwright.core.kill.breaker import CircuitBreakerRegistry

            self.circuit_breaker = CircuitBreakerRegistry(
                state_path=Path(circuit_breaker_path)
            )

        # CORRECT pillar: rule engine (optional)
        self.rule_engine: Any | None = None
        if rules_path is not None:
            from toolwright.core.correct.engine import RuleEngine

            self.rule_engine = RuleEngine(rules_path=Path(rules_path))

        # Proposals directory (for toolwright_request_capability)
        self.proposals_dir: Path | None = (
            self.state_dir / "proposals" if self.state_dir else None
        )

        # Create MCP server
        self.server = Server("toolwright-meta")

        # Register handlers
        self._register_handlers()

        logger.info("Initialized Toolwright Meta MCP server")

    # ------------------------------------------------------------------
    # Public handler methods (used by MCP protocol and tests)
    # ------------------------------------------------------------------

    async def _handle_list_tools(self) -> list[types.Tool]:
        """Return all meta tools."""
        tools = [
            # --- GOVERN ---
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
            # --- HEAL ---
            types.Tool(
                name="toolwright_diagnose_tool",
                description="Diagnose a tool by searching audit logs for DENY entries and returning a diagnosis.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tool_id": {
                            "type": "string",
                            "description": "ID of the tool to diagnose",
                        },
                    },
                    "required": ["tool_id"],
                },
            ),
            types.Tool(
                name="toolwright_health_check",
                description="Check if a tool exists in the manifest and is approved.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tool_id": {
                            "type": "string",
                            "description": "ID of the tool to check",
                        },
                    },
                    "required": ["tool_id"],
                },
            ),
            # --- KILL ---
            types.Tool(
                name="toolwright_kill_tool",
                description="Force a tool's circuit breaker open (kill switch).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tool_id": {
                            "type": "string",
                            "description": "ID of the tool to kill",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reason for killing the tool",
                        },
                    },
                    "required": ["tool_id"],
                },
            ),
            types.Tool(
                name="toolwright_enable_tool",
                description="Re-enable a killed tool by closing its circuit breaker.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tool_id": {
                            "type": "string",
                            "description": "ID of the tool to enable",
                        },
                    },
                    "required": ["tool_id"],
                },
            ),
            types.Tool(
                name="toolwright_quarantine_report",
                description="List all tools with tripped or manually killed circuit breakers.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            # --- CORRECT ---
            types.Tool(
                name="toolwright_add_rule",
                description="Create a behavioral rule for tool usage.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "prerequisite",
                                "prohibition",
                                "parameter",
                                "sequence",
                                "rate",
                                "approval",
                            ],
                            "description": "Rule type",
                        },
                        "target_tool_id": {
                            "type": "string",
                            "description": "Tool ID this rule applies to",
                        },
                        "description": {
                            "type": "string",
                            "description": "Human-readable description of the rule",
                        },
                        "required_tool_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Required prerequisite tool IDs (for prerequisite rules)",
                        },
                    },
                    "required": ["kind", "target_tool_id", "description"],
                },
            ),
            types.Tool(
                name="toolwright_list_rules",
                description="List all behavioral rules with optional kind filter.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "prerequisite",
                                "prohibition",
                                "parameter",
                                "sequence",
                                "rate",
                                "approval",
                            ],
                            "description": "Filter by rule kind",
                        },
                    },
                },
            ),
            types.Tool(
                name="toolwright_remove_rule",
                description="Remove a behavioral rule by ID.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "rule_id": {
                            "type": "string",
                            "description": "ID of the rule to remove",
                        },
                    },
                    "required": ["rule_id"],
                },
            ),
            types.Tool(
                name="toolwright_suggest_rule",
                description="Suggest a new behavioral rule. Creates a DRAFT rule that must be activated by a human.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "prerequisite",
                                "prohibition",
                                "parameter",
                                "sequence",
                                "rate",
                                "approval",
                            ],
                            "description": "Type of behavioral rule",
                        },
                        "description": {
                            "type": "string",
                            "description": "Human-readable description of the rule",
                        },
                        "target_tool_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tool IDs this rule applies to",
                        },
                        "config": {
                            "type": "object",
                            "description": "Rule-specific configuration (depends on kind)",
                        },
                    },
                    "required": ["kind", "description", "config"],
                },
            ),
            # --- RECONCILE ---
            types.Tool(
                name="toolwright_reconcile_status",
                description="Get reconciliation loop health status for all monitored tools.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filter_status": {
                            "type": "string",
                            "enum": ["healthy", "degraded", "unhealthy", "unknown"],
                            "description": "Filter tools by health status",
                        },
                    },
                },
            ),
            types.Tool(
                name="toolwright_pending_repairs",
                description="Get pending repair patches from the latest repair plan.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filter_kind": {
                            "type": "string",
                            "enum": ["safe", "approval_required", "manual"],
                            "description": "Filter patches by kind",
                        },
                    },
                },
            ),
            # --- REQUEST CAPABILITY ---
            types.Tool(
                name="toolwright_request_capability",
                description="Request a new API capability by probing a host for its OpenAPI spec. Creates a PENDING proposal for human review.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "description": "Host URL to probe for an OpenAPI spec (e.g., 'https://api.example.com')",
                        },
                    },
                    "required": ["host"],
                },
            ),
        ]
        return tools

    async def _handle_call_tool(
        self, name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Dispatch a meta tool call."""
        arguments = arguments or {}

        dispatch: dict[str, Any] = {
            "toolwright_list_actions": lambda: self._list_actions(arguments),
            "toolwright_check_policy": lambda: self._check_policy(arguments),
            "toolwright_get_approval_status": lambda: self._get_approval_status(arguments),
            "toolwright_list_pending_approvals": lambda: self._list_pending_approvals(),
            "toolwright_get_action_details": lambda: self._get_action_details(arguments),
            "toolwright_risk_summary": lambda: self._risk_summary(),
            "toolwright_get_flows": lambda: self._get_flows(arguments),
            # HEAL
            "toolwright_diagnose_tool": lambda: self._diagnose_tool(arguments),
            "toolwright_health_check": lambda: self._health_check(arguments),
            # KILL
            "toolwright_kill_tool": lambda: self._kill_tool(arguments),
            "toolwright_enable_tool": lambda: self._enable_tool(arguments),
            "toolwright_quarantine_report": lambda: self._quarantine_report(),
            # CORRECT
            "toolwright_add_rule": lambda: self._add_rule(arguments),
            "toolwright_list_rules": lambda: self._list_rules(arguments),
            "toolwright_remove_rule": lambda: self._remove_rule(arguments),
            "toolwright_suggest_rule": lambda: self._suggest_rule(arguments),
            # RECONCILE
            "toolwright_reconcile_status": lambda: self._reconcile_status(arguments),
            "toolwright_pending_repairs": lambda: self._pending_repairs(arguments),
            # REQUEST CAPABILITY
            "toolwright_request_capability": lambda: self._request_capability(arguments),
        }

        handler = dispatch.get(name)
        if handler:
            return await handler()

        return [types.TextContent(
            type="text",
            text=json.dumps({"error": f"Unknown tool: {name}"})
        )]

    def _register_handlers(self) -> None:
        """Register MCP protocol handlers."""

        @self.server.list_tools()  # type: ignore
        async def handle_list_tools() -> list[types.Tool]:
            return await self._handle_list_tools()

        @self.server.call_tool()  # type: ignore
        async def handle_call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
            return await self._handle_call_tool(name, arguments)

    # ------------------------------------------------------------------
    # GOVERN handlers (existing)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # HEAL handlers
    # ------------------------------------------------------------------

    async def _diagnose_tool(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Diagnose a tool by checking manifest, approval state, and endpoint."""
        tool_id = arguments.get("tool_id")
        if not tool_id:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "tool_id is required"})
            )]

        diagnosis: dict[str, Any] = {"tool_id": tool_id, "issues": []}

        # Check if tool exists in manifest
        found = False
        action_entry: dict[str, Any] | None = None
        if self.manifest:
            for action in self.manifest.get("actions", []):
                if action["name"] == tool_id:
                    found = True
                    action_entry = action
                    break

        if not found:
            diagnosis["issues"].append("Tool not found in manifest")
        else:
            diagnosis["in_manifest"] = True

        # Check approval status
        manager = LockfileManager(self.lockfile_path)
        if manager.exists():
            manager.load()
            tool = manager.get_tool(tool_id)
            if tool:
                diagnosis["approval_status"] = tool.status.value
                if tool.status == ApprovalStatus.REJECTED:
                    diagnosis["issues"].append(
                        f"Tool rejected: {tool.rejection_reason or 'no reason given'}"
                    )
                elif tool.status == ApprovalStatus.PENDING:
                    diagnosis["issues"].append("Tool pending approval")
            else:
                diagnosis["issues"].append("Tool not in lockfile")

        # Check circuit breaker
        if self.circuit_breaker is not None:
            allowed, reason = self.circuit_breaker.should_allow(tool_id)
            if not allowed:
                diagnosis["circuit_breaker"] = "open"
                diagnosis["issues"].append(f"Circuit breaker open: {reason}")

        # Probe endpoint if tool exists in manifest
        if found and action_entry is not None:
            from toolwright.core.health.checker import HealthChecker

            checker = HealthChecker()
            probe = await checker.check_tool(action_entry)
            diagnosis["endpoint_reachable"] = probe.healthy
            if not probe.healthy:
                fc = probe.failure_class.value if probe.failure_class else "unknown"
                diagnosis["issues"].append(
                    f"Endpoint unreachable: {probe.status_code or 'N/A'} {fc}"
                )

        diagnosis["healthy"] = len(diagnosis["issues"]) == 0

        return [types.TextContent(
            type="text",
            text=json.dumps(diagnosis, indent=2)
        )]

    async def _health_check(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Check if a tool exists, is approved, and its endpoint is reachable."""
        tool_id = arguments.get("tool_id")
        if not tool_id:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "tool_id is required"})
            )]

        exists = False
        approved = False
        action_entry: dict[str, Any] | None = None

        if self.manifest:
            for action in self.manifest.get("actions", []):
                if action["name"] == tool_id:
                    exists = True
                    action_entry = action
                    break

        if exists:
            manager = LockfileManager(self.lockfile_path)
            if manager.exists():
                manager.load()
                tool = manager.get_tool(tool_id)
                if tool and tool.status == ApprovalStatus.APPROVED:
                    approved = True

        result: dict[str, Any] = {
            "tool_id": tool_id,
            "exists": exists,
            "approved": approved,
        }

        # Probe endpoint if tool exists in manifest
        if exists and action_entry is not None:
            from toolwright.core.health.checker import HealthChecker

            checker = HealthChecker()
            probe = await checker.check_tool(action_entry)
            result["endpoint_reachable"] = probe.healthy
            result["status_code"] = probe.status_code
            result["response_time_ms"] = probe.response_time_ms
            if probe.failure_class is not None:
                result["failure_class"] = probe.failure_class.value

        result["healthy"] = exists and approved and result.get("endpoint_reachable", False)

        return [types.TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]

    # ------------------------------------------------------------------
    # KILL handlers
    # ------------------------------------------------------------------

    async def _kill_tool(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Kill a tool by forcing its circuit breaker open."""
        tool_id = arguments.get("tool_id")
        if not tool_id:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "tool_id is required"})
            )]

        if self.circuit_breaker is None:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "Circuit breaker not configured"})
            )]

        reason = arguments.get("reason", "killed via meta-tool")
        self.circuit_breaker.kill_tool(tool_id, reason)

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "tool_id": tool_id,
                "state": "open",
                "reason": reason,
            }, indent=2)
        )]

    async def _enable_tool(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Enable a tool by closing its circuit breaker."""
        tool_id = arguments.get("tool_id")
        if not tool_id:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "tool_id is required"})
            )]

        if self.circuit_breaker is None:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "Circuit breaker not configured"})
            )]

        self.circuit_breaker.enable_tool(tool_id)

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "tool_id": tool_id,
                "state": "closed",
            }, indent=2)
        )]

    async def _quarantine_report(
        self,
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """List all quarantined tools."""
        if self.circuit_breaker is None:
            return [types.TextContent(
                type="text",
                text=json.dumps({"total": 0, "tools": [], "message": "Circuit breaker not configured"})
            )]

        report = self.circuit_breaker.quarantine_report()
        tools = [
            {
                "tool_id": b.tool_id,
                "state": b.state.value,
                "failure_count": b.failure_count,
                "kill_reason": b.kill_reason,
                "last_failure_error": b.last_failure_error,
            }
            for b in report
        ]

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "total": len(tools),
                "tools": tools,
            }, indent=2)
        )]

    # ------------------------------------------------------------------
    # CORRECT handlers
    # ------------------------------------------------------------------

    async def _add_rule(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Add a behavioral rule."""
        kind = arguments.get("kind")
        if not kind:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "kind is required"})
            )]

        if self.rule_engine is None:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "Rule engine not configured"})
            )]

        from uuid import uuid4

        from toolwright.models.rule import BehavioralRule, RuleKind

        target = arguments.get("target_tool_id", "")
        description = arguments.get("description", "")

        # Build config based on kind
        config: dict[str, Any] = {}
        if kind == "prerequisite":
            config["required_tool_ids"] = arguments.get("required_tool_ids", [])
        elif kind == "prohibition":
            config["always"] = True
        elif kind == "parameter":
            config["param_name"] = arguments.get("param_name", "")
        elif kind == "sequence":
            config["required_order"] = arguments.get("required_order", [])
        elif kind == "rate":
            config["max_calls"] = arguments.get("max_calls", 10)

        rule = BehavioralRule(
            rule_id=str(uuid4()),
            kind=RuleKind(kind),
            description=description,
            target_tool_ids=[target] if target else [],
            config=config,
        )

        self.rule_engine.add_rule(rule)

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "rule_id": rule.rule_id,
                "kind": rule.kind.value,
                "description": rule.description,
                "target_tool_ids": rule.target_tool_ids,
            }, indent=2)
        )]

    async def _list_rules(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """List behavioral rules."""
        if self.rule_engine is None:
            return [types.TextContent(
                type="text",
                text=json.dumps({"total": 0, "rules": [], "message": "Rule engine not configured"})
            )]

        kind_filter = arguments.get("kind")
        rules = self.rule_engine.list_rules()
        if kind_filter:
            rules = [r for r in rules if r.kind.value == kind_filter]

        result = [
            {
                "rule_id": r.rule_id,
                "kind": r.kind.value,
                "description": r.description,
                "target_tool_ids": r.target_tool_ids,
                "status": r.status.value,
            }
            for r in rules
        ]

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "total": len(result),
                "rules": result,
            }, indent=2)
        )]

    async def _remove_rule(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Remove a behavioral rule by ID."""
        rule_id = arguments.get("rule_id")
        if not rule_id:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "rule_id is required"})
            )]

        if self.rule_engine is None:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": "Rule engine not configured"})
            )]

        try:
            self.rule_engine.remove_rule(rule_id)
            removed = True
        except KeyError:
            removed = False

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "rule_id": rule_id,
                "removed": removed,
            }, indent=2)
        )]

    async def _suggest_rule(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Suggest a new behavioral rule as DRAFT (agent cannot activate)."""
        if self.rule_engine is None:
            return [types.TextContent(
                type="text",
                text="Error: No rule engine configured.",
            )]

        kind = arguments.get("kind")
        if not kind:
            return [types.TextContent(
                type="text",
                text="Error: 'kind' parameter required.",
            )]

        description = arguments.get("description", "")
        config = arguments.get("config", {})
        target_tool_ids = arguments.get("target_tool_ids", [])

        from datetime import UTC, datetime
        from uuid import uuid4

        from toolwright.models.rule import (
            _KIND_TO_CONFIG,
            BehavioralRule,
            RuleKind,
            RuleStatus,
        )

        rule_id = f"rule_{uuid4().hex[:8]}"

        try:
            rule_kind = RuleKind(kind)
            config_cls = _KIND_TO_CONFIG.get(rule_kind)
            if config_cls is None:
                return [types.TextContent(
                    type="text",
                    text=f"Error: Unknown rule kind: {kind}",
                )]
            parsed_config = config_cls.model_validate(config)
        except Exception as e:
            return [types.TextContent(
                type="text",
                text=f"Error: Invalid config for {kind}: {e}",
            )]

        rule = BehavioralRule(
            rule_id=rule_id,
            kind=rule_kind,
            description=description,
            status=RuleStatus.DRAFT,
            target_tool_ids=target_tool_ids,
            target_methods=[],
            target_hosts=[],
            config=parsed_config,
            created_at=datetime.now(UTC),
            created_by="agent",
        )

        self.rule_engine.add_rule(rule)

        text = (
            f"Rule suggested: {rule_id} ({kind}, DRAFT)\n"
            f"{description}\n"
            f"Next: Activate with `toolwright rules activate {rule_id}`"
        )
        return [types.TextContent(type="text", text=text)]

    # ------------------------------------------------------------------
    # RECONCILE handlers
    # ------------------------------------------------------------------

    async def _reconcile_status(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Return concise per-tool health status from the reconciliation loop."""
        from toolwright.models.reconcile import ReconcileState

        state = ReconcileState()
        if self.state_dir is not None:
            state_path = self.state_dir / "reconcile.json"
            if state_path.exists():
                try:
                    state = ReconcileState.model_validate_json(
                        state_path.read_text(encoding="utf-8")
                    )
                except Exception:
                    logger.warning("Failed to parse reconcile state at %s", state_path)

        if not state.tools:
            return [types.TextContent(
                type="text",
                text="Reconciliation: no tools monitored (0 cycles)",
            )]

        # Summary counts
        counts: dict[str, int] = {}
        for ts in state.tools.values():
            s = str(ts.status)
            counts[s] = counts.get(s, 0) + 1

        filter_status = arguments.get("filter_status")

        # Header line
        parts = [f"{v} {k}" for k, v in sorted(counts.items())]
        header = f"Reconciliation: cycle #{state.reconcile_count}, {', '.join(parts)}"

        # Detail lines for non-healthy tools (or filtered)
        lines = [header]
        for ts in state.tools.values():
            if filter_status and str(ts.status) != filter_status:
                continue
            if str(ts.status) == "healthy" and not filter_status:
                continue
            detail = f"  {ts.tool_id}: {ts.failure_class or 'unknown'}"
            if str(ts.last_action) != "none":
                detail += f", {ts.last_action}"
            lines.append(detail)

        # Footer
        lines.append(
            f"Auto-repairs: {state.auto_repairs_applied}"
            f" | Approvals queued: {state.approvals_queued}"
            f" | Errors: {state.errors}"
        )

        return [types.TextContent(type="text", text="\n".join(lines))]

    async def _pending_repairs(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Return concise pending repair patches from the latest repair plan."""
        no_repairs = "No pending repairs."

        if self.state_dir is None:
            return [types.TextContent(type="text", text=no_repairs)]

        plan_path = self.state_dir / "repair_plan.json"
        if not plan_path.exists():
            return [types.TextContent(type="text", text=no_repairs)]

        try:
            plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to parse repair plan at %s", plan_path)
            return [types.TextContent(type="text", text=no_repairs)]

        plan_body = plan_data.get("plan", {})
        patches = plan_body.get("patches", [])

        # Apply kind filter
        filter_kind = arguments.get("filter_kind")
        if filter_kind:
            patches = [p for p in patches if p.get("kind") == filter_kind]

        if not patches:
            return [types.TextContent(type="text", text=no_repairs)]

        total = plan_body.get("total_patches", len(patches))
        safe = plan_body.get("safe_count", 0)
        approval = plan_body.get("approval_required_count", 0)
        manual = plan_body.get("manual_count", 0)

        # Header
        lines = [f"{total} repairs pending ({safe} safe, {approval} approval_required, {manual} manual):"]

        # Patch lines
        for p in patches:
            kind = p.get("kind", "?")
            title = p.get("title", "untitled")
            cmd = p.get("cli_command", "")
            lines.append(f"  [{kind}] {title} — {cmd}")

        lines.append("Run `toolwright repair apply` to apply.")

        return [types.TextContent(type="text", text="\n".join(lines))]

    # ------------------------------------------------------------------
    # REQUEST CAPABILITY handler
    # ------------------------------------------------------------------

    async def _request_capability(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Probe a host for an OpenAPI spec and create a PENDING proposal."""
        host = arguments.get("host")
        if not host:
            return [types.TextContent(type="text", text="Error: 'host' parameter required.")]

        from toolwright.core.discover.openapi import OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        session = await discovery.discover(host)

        if session is None:
            return [types.TextContent(
                type="text",
                text=f"No OpenAPI spec found at {host}. Manual capture may be needed.",
            )]

        if self.proposals_dir is None:
            return [types.TextContent(
                type="text",
                text="Error: No state directory configured for proposals.",
            )]

        from toolwright.core.proposal.engine import ProposalEngine
        from toolwright.models.proposal import MissingCapability

        capability = MissingCapability(
            reason_code="AGENT_REQUESTED",
            attempted_action=f"discover:{host}",
            suggested_host=host,
            risk_guess="medium",
            agent_context=f"Discovered {len(session.exchanges)} endpoints via OpenAPI",
        )

        engine = ProposalEngine(root=self.proposals_dir)
        proposal = engine.create_proposal(capability)

        n = len(session.exchanges)
        text = (
            f"Capability requested: {n} endpoints at {host}\n"
            f"Proposal: {proposal.proposal_id} (PENDING)\n"
            f"Next: Human must review and approve via `toolwright proposals approve {proposal.proposal_id}`"
        )
        return [types.TextContent(type="text", text=text)]

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

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
    circuit_breaker_path: str | None = None,
    rules_path: str | None = None,
) -> None:
    """Run the Toolwright Meta MCP server.

    Args:
        artifacts_dir: Directory containing Toolwright artifacts
        tools_path: Path to tools.json (overrides artifacts_dir)
        policy_path: Path to policy.yaml (overrides artifacts_dir)
        lockfile_path: Path to lockfile
        circuit_breaker_path: Path to circuit breaker state file
        rules_path: Path to behavioral rules JSON file
    """
    server = ToolwrightMetaMCPServer(
        artifacts_dir=artifacts_dir,
        tools_path=tools_path,
        policy_path=policy_path,
        lockfile_path=lockfile_path,
        circuit_breaker_path=circuit_breaker_path,
        rules_path=rules_path,
    )

    asyncio.run(server.run_stdio())

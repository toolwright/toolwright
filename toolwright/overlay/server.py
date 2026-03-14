"""OverlayServer: MCP governance proxy for upstream MCP servers.

Composes the same pipeline components as ToolwrightMCPServer (RequestPipeline,
DecisionEngine, Server, etc.) but wires them with an MCP proxy executor
instead of HTTP execution. Does NOT subclass ToolwrightMCPServer — that
class is too coupled to file-based manifests.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from toolwright.core.approval.lockfile import LockfileManager
from toolwright.core.audit import AuditLogger, DecisionTraceEmitter, MemoryAuditBackend
from toolwright.core.enforce import ConfirmationStore, DecisionEngine
from toolwright.mcp._compat import (
    InitializationOptions,
    NotificationOptions,
    Server,
    mcp_stdio,
)
from toolwright.mcp._compat import (
    mcp_types as types,
)
from toolwright.mcp.pipeline import PipelineResult, RequestPipeline
from toolwright.models.decision import DecisionContext, NetworkSafetyConfig
from toolwright.models.overlay import DiscoveryResult, WrapConfig
from toolwright.overlay.normalizer import normalize_mcp_result

logger = logging.getLogger(__name__)


class OverlayServer:
    """MCP governance proxy for upstream MCP servers."""

    def __init__(
        self,
        *,
        config: WrapConfig,
        connection: Any,
        dry_run: bool = False,
        rules_path: Path | None = None,
        circuit_breaker_path: Path | None = None,
    ) -> None:
        self.config = config
        self.connection = connection
        self.dry_run = dry_run
        self.run_id = f"run_{uuid4().hex[:12]}"

        # Actions dict populated by load_tools_from_discovery
        self.actions: dict[str, dict[str, Any]] = {}

        # Lockfile for approval tracking
        self._lockfile_manager: LockfileManager | None = None

        # Audit
        self._audit_logger = AuditLogger(MemoryAuditBackend())
        self._decision_trace = DecisionTraceEmitter(
            output_path=None,
            run_id=self.run_id,
            lockfile_digest=None,
            policy_digest=None,
        )

        # Decision engine (wired after tools are loaded)
        self._confirmation_store = ConfirmationStore(
            config.state_dir / "confirmations.db"
        )
        self._decision_engine = DecisionEngine(self._confirmation_store)

        # CORRECT pillar (optional)
        self._rule_engine = None
        self._session_history = None
        if rules_path is not None:
            from toolwright.core.correct.engine import RuleEngine
            from toolwright.core.correct.session import SessionHistory

            self._rule_engine = RuleEngine(rules_path=rules_path)
            self._session_history = SessionHistory()

        # KILL pillar (optional)
        self._circuit_breaker = None
        if circuit_breaker_path is not None:
            from toolwright.core.kill.breaker import CircuitBreakerRegistry

            self._circuit_breaker = CircuitBreakerRegistry(
                state_path=circuit_breaker_path
            )

        # Pipeline wired after tools loaded
        self._pipeline: RequestPipeline | None = None

        # MCP server instance (wired by _register_handlers)
        self._mcp_server: Server | None = None

    def load_tools_from_discovery(self, discovery: DiscoveryResult) -> None:
        """Populate actions dict from a DiscoveryResult."""
        from toolwright.overlay.discovery import build_synthetic_manifest

        manifest = build_synthetic_manifest(discovery, self.config)
        self.actions = {}
        for action in manifest.get("actions", []):
            self.actions[action["name"]] = action

        self._rebuild_pipeline()

    def sync_lockfile(self, manifest: dict[str, Any]) -> dict[str, list[str]]:
        """Sync a synthetic manifest to the lockfile.

        Creates or updates the lockfile at config.lockfile_path.
        Returns change summary from LockfileManager.sync_from_manifest().
        """
        lockfile_path = self.config.lockfile_path
        lockfile_path.parent.mkdir(parents=True, exist_ok=True)

        manager = LockfileManager(lockfile_path)
        if not manager.exists():
            manager.load()  # Creates empty lockfile in memory

        changes = manager.sync_from_manifest(manifest, deterministic=False)
        manager.save()

        self._lockfile_manager = manager
        return changes

    async def _proxy_call(
        self, action: dict[str, Any], arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a tool call via the upstream connection and normalize."""
        result = await self.connection.call_tool(action["name"], arguments)
        return normalize_mcp_result(action["name"], result)

    def _rebuild_pipeline(self) -> None:
        """Rebuild the RequestPipeline with current actions."""
        decision_context = DecisionContext(
            manifest_view=self.actions,
            policy=None,
            policy_engine=None,
            lockfile=self._lockfile_manager,
            toolsets=None,
            network_safety=NetworkSafetyConfig(),
            artifacts_digest_current=None,
            lockfile_digest_current=None,
            approval_root_path=str(self.config.state_dir),
            require_signed_approvals=False,
        )

        self._pipeline = RequestPipeline(
            actions=self.actions,
            decision_engine=self._decision_engine,
            decision_context=decision_context,
            decision_trace=self._decision_trace,
            audit_logger=self._audit_logger,
            dry_run=self.dry_run,
            rule_engine=self._rule_engine,
            session_history=self._session_history,
            circuit_breaker=self._circuit_breaker,
            execute_request_fn=lambda action, args: self._proxy_call(action, args),
        )

    def _register_handlers(self) -> None:
        """Create MCP Server and register list_tools/call_tool handlers."""
        self._mcp_server = Server(f"toolwright-overlay-{self.config.server_name}")

        @self._mcp_server.list_tools()  # type: ignore
        async def handle_list_tools() -> list[types.Tool]:
            tools = []
            for action in self.actions.values():
                tool = types.Tool(
                    name=action["name"],
                    description=action.get("description", ""),
                    inputSchema=action.get(
                        "input_schema", {"type": "object", "properties": {}}
                    ),
                )
                tools.append(tool)
            return tools

        @self._mcp_server.call_tool()  # type: ignore
        async def handle_call_tool(
            name: str,
            arguments: dict[str, Any] | None,
        ) -> Any:
            try:
                pipeline = self._pipeline
                assert pipeline is not None
                result = await pipeline.execute(
                    name,
                    arguments or {},
                    toolset_name=None,
                )
                return self._format_mcp_result(result)
            except Exception as exc:
                logger.error(
                    "Unhandled error in overlay tool call '%s': %s",
                    name,
                    exc,
                    exc_info=True,
                )
                text = f"Internal error: {type(exc).__name__}: {exc}"
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=text)],
                    isError=True,
                )

        # Store references for direct invocation (testing, internal use)
        self._handle_list_tools = handle_list_tools
        self._handle_call_tool = handle_call_tool

    def _format_mcp_result(self, result: Any) -> Any:
        """Convert a PipelineResult to MCP wire format."""
        if not isinstance(result, PipelineResult):
            return result

        # Raw: return as-is
        if result.is_raw:
            return result.payload

        # Standard success/error: wrap in CallToolResult with TextContent
        payload = result.payload
        text = json.dumps(payload) if not isinstance(payload, str) else payload
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            isError=result.is_error,
        )

    async def run_stdio(self) -> None:
        """Run the overlay server using stdio transport."""
        if self._mcp_server is None:
            self._register_handlers()
        mcp_server = self._mcp_server
        assert mcp_server is not None

        async with mcp_stdio.stdio_server() as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name=f"toolwright-overlay-{self.config.server_name}",
                    server_version="1.0.0",
                    capabilities=mcp_server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

    def run_http(self, *, host: str = "127.0.0.1", port: int = 8745) -> None:
        """Run the overlay server using HTTP transport.

        Not yet implemented — HTTP transport for overlay is deferred.
        Use run_stdio() instead.
        """
        raise NotImplementedError(
            "HTTP transport for overlay mode is not yet implemented. "
            "Use stdio transport (the default)."
        )

    async def close(self) -> None:
        """Clean up resources."""
        if self.connection:
            await self.connection.close()

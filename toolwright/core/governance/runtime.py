"""GovernanceRuntime — transport-agnostic governance factory.

Extracts all governance component wiring from ToolwrightMCPServer so that
any transport adapter (MCP, CLI, REST) can get a fully configured
GovernanceEngine without duplicating wiring logic.

Usage:
    runtime = GovernanceRuntime(
        tools_path="toolpack.json",
        lockfile_path=".toolwright/lockfile.json",
        ...
    )
    # runtime.engine is a GovernanceEngine ready to execute tool calls
    # runtime.actions is the filtered action set
    # All subsystems are accessible as attributes
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from toolwright.core.approval import (
    LockfileManager,
    compute_artifacts_digest_from_paths,
    compute_lockfile_digest,
)
from toolwright.core.approval.signing import resolve_approval_root
from toolwright.core.audit import (
    AuditLogger,
    DecisionTraceEmitter,
    FileAuditBackend,
    MemoryAuditBackend,
)
from toolwright.core.correct.engine import RuleEngine
from toolwright.core.correct.session import SessionHistory
from toolwright.core.enforce import ConfirmationStore, DecisionEngine, PolicyEngine
from toolwright.core.governance.engine import (
    ExecuteRequestFn,
    GovernanceEngine,
)
from toolwright.core.kill.breaker import CircuitBreakerRegistry
from toolwright.core.toolpack import ToolpackAuthRequirement
from toolwright.models.decision import (
    DecisionContext,
    NetworkSafetyConfig,
)
from toolwright.utils.schema_version import resolve_schema_version

logger = logging.getLogger(__name__)


class GovernanceRuntime:
    """Wire up all governance subsystems and produce a GovernanceEngine.

    This is the factory that every transport adapter uses to get a
    fully-configured governance pipeline. The adapter only needs to
    supply an ``execute_request_fn`` callback for its transport.

    Attributes exposed for adapter use:
        engine: GovernanceEngine — the pipeline (set after set_execute_fn)
        actions: dict — filtered tool actions from manifest
        actions_by_tool_id: dict — tool_id → action mapping
        manifest: dict — raw parsed manifest
        lockfile_manager: LockfileManager | None
        audit_logger: AuditLogger
        decision_trace: DecisionTraceEmitter
        policy_engine: PolicyEngine | None
        decision_engine: DecisionEngine
        decision_context: DecisionContext
        rule_engine: RuleEngine | None
        session_history: SessionHistory | None
        circuit_breaker: CircuitBreakerRegistry | None
        run_id: str
        dry_run: bool
        transport_type: str
    """

    def __init__(
        self,
        tools_path: str | Path,
        *,
        toolsets_path: str | Path | None = None,
        toolset_name: str | None = None,
        policy_path: str | Path | None = None,
        lockfile_path: str | Path | None = None,
        base_url: str | None = None,
        auth_header: str | None = None,
        audit_log: str | Path | None = None,
        dry_run: bool = False,
        confirmation_store_path: str | Path = ".toolwright/state/confirmations.db",
        allow_private_cidrs: list[str] | None = None,
        allow_redirects: bool = False,
        rules_path: str | Path | None = None,
        circuit_breaker_path: str | Path | None = None,
        extra_headers: dict[str, str] | None = None,
        schema_validation: str = "warn",
        auth_requirements: list[ToolpackAuthRequirement] | None = None,
        transport_type: str = "mcp",
        execute_request_fn: ExecuteRequestFn | None = None,
        console_event_store: Any | None = None,
    ) -> None:
        self.transport_type = transport_type
        self.schema_validation = schema_validation
        self._auth_requirements = auth_requirements or []
        self.tools_path = Path(tools_path)
        self.toolsets_path = Path(toolsets_path) if toolsets_path else None
        self.toolset_name = toolset_name
        self.policy_path = Path(policy_path) if policy_path else None
        self.lockfile_path = Path(lockfile_path) if lockfile_path else None
        self.base_url = base_url
        self.auth_header = auth_header
        self.extra_headers = extra_headers
        self.dry_run = dry_run
        self.allow_private_networks = [
            ipaddress.ip_network(cidr)
            for cidr in (allow_private_cidrs or [])
        ]
        self.allow_redirects = allow_redirects
        self.approval_root_path = resolve_approval_root(
            lockfile_path=self.lockfile_path,
            fallback_root=confirmation_store_path,
        )
        self.run_id = f"run_{uuid4().hex[:12]}"

        # ── Load manifest ─────────────────────────────────────────────
        with open(self.tools_path) as f:
            self.manifest: dict[str, Any] = json.load(f)
        resolve_schema_version(
            self.manifest,
            artifact="tools manifest",
            allow_legacy=True,
        )

        # ── Load toolsets (optional) ──────────────────────────────────
        self.toolsets_payload: dict[str, Any] | None = None
        selected_action_names: set[str] | None = None
        if self.toolsets_path is not None:
            with open(self.toolsets_path) as f:
                self.toolsets_payload = yaml.safe_load(f) or {}
            resolve_schema_version(
                self.toolsets_payload,
                artifact="toolsets artifact",
                allow_legacy=False,
            )
            if self.toolset_name:
                toolsets = self.toolsets_payload.get("toolsets", {})
                if self.toolset_name not in toolsets:
                    available = ", ".join(sorted(toolsets))
                    raise ValueError(
                        f"Unknown toolset '{self.toolset_name}'. Available: {available}"
                    )
                selected_action_names = set(
                    toolsets[self.toolset_name].get("actions", [])
                )

        # ── Lockfile setup ────────────────────────────────────────────
        self.lockfile_manager: LockfileManager | None = None
        self.lockfile_digest_current: str | None = None
        self._lockfile_mtime: float = 0.0
        self._last_lockfile_check: float = 0.0
        if self.lockfile_path is not None:
            manager = LockfileManager(self.lockfile_path)
            if not manager.exists():
                raise ValueError(f"Lockfile not found: {manager.lockfile_path}")
            lockfile = manager.load()

            sig_passed, sig_message = manager.verify_signatures(
                root_path=self.approval_root_path,
            )
            if not sig_passed:
                logger.warning(
                    "Lockfile signature verification failed at startup: %s "
                    "Per-request signature verification is still enforced.",
                    sig_message,
                )

            self.lockfile_manager = manager
            self.lockfile_digest_current = compute_lockfile_digest(
                lockfile.model_dump(mode="json")
            )
            if self.lockfile_path.exists():
                self._lockfile_mtime = self.lockfile_path.stat().st_mtime

        # ── Filter actions ────────────────────────────────────────────
        self.actions: dict[str, dict[str, Any]] = {}
        self.actions_by_tool_id: dict[str, dict[str, Any]] = {}
        for action in self.manifest.get("actions", []):
            if (
                selected_action_names is not None
                and action.get("name") not in selected_action_names
            ):
                continue
            if not self._is_action_exposed(action):
                continue
            self.actions[action["name"]] = action
            tool_id = str(
                action.get("tool_id")
                or action.get("signature_id")
                or action.get("name")
            )
            self.actions_by_tool_id[tool_id] = action
            self.actions_by_tool_id[action["name"]] = action

        if selected_action_names is not None:
            missing = sorted(selected_action_names - set(self.actions))
            if missing:
                raise ValueError(
                    f"Toolset '{self.toolset_name}' references missing tools: "
                    f"{', '.join(missing)}"
                )

        # ── Audit subsystem ───────────────────────────────────────────
        backend = FileAuditBackend(audit_log) if audit_log else MemoryAuditBackend()
        self.audit_logger = AuditLogger(backend)
        self.policy_digest = (
            hashlib.sha256(self.policy_path.read_bytes()).hexdigest()
            if self.policy_path and self.policy_path.exists()
            else None
        )
        self.decision_trace = DecisionTraceEmitter(
            output_path=audit_log,
            run_id=self.run_id,
            lockfile_digest=self.lockfile_digest_current,
            policy_digest=self.policy_digest,
        )

        # ── Policy engine ─────────────────────────────────────────────
        self.policy_engine: PolicyEngine | None = None
        if self.policy_path and self.policy_path.exists():
            self.policy_engine = PolicyEngine.from_file(str(self.policy_path))
        self.enforcer = self.policy_engine  # backward-compat alias

        # ── Artifacts digest ──────────────────────────────────────────
        toolsets_for_digest: str | None = (
            str(self.toolsets_path) if self.toolsets_path else None
        )
        policy_for_digest: str | None = (
            str(self.policy_path) if self.policy_path else None
        )
        self.artifacts_digest_current = compute_artifacts_digest_from_paths(
            tools_path=self.tools_path,
            toolsets_path=toolsets_for_digest,
            policy_path=policy_for_digest,
        )

        # ── Decision engine + context ─────────────────────────────────
        self.confirmation_store = ConfirmationStore(confirmation_store_path)
        self.decision_engine = DecisionEngine(self.confirmation_store)
        self.decision_context = DecisionContext(
            manifest_view=self.actions_by_tool_id,
            policy=self.policy_engine.policy if self.policy_engine else None,
            policy_engine=self.policy_engine,
            lockfile=self.lockfile_manager,
            toolsets=self.toolsets_payload,
            network_safety=NetworkSafetyConfig(
                allow_private_cidrs=allow_private_cidrs or [],
                allow_redirects=allow_redirects,
                max_redirects=3,
            ),
            artifacts_digest_current=self.artifacts_digest_current,
            lockfile_digest_current=self.lockfile_digest_current,
            approval_root_path=str(self.approval_root_path),
            require_signed_approvals=True,
        )

        # ── CORRECT pillar: behavioral rule engine (optional) ─────────
        self.rule_engine: RuleEngine | None = None
        self.session_history: SessionHistory | None = None
        if rules_path is not None:
            self.rule_engine = RuleEngine(rules_path=Path(rules_path))
            self.session_history = SessionHistory()

        # ── KILL pillar: circuit breaker (optional) ───────────────────
        self.circuit_breaker: CircuitBreakerRegistry | None = None
        if circuit_breaker_path is not None:
            self.circuit_breaker = CircuitBreakerRegistry(
                state_path=Path(circuit_breaker_path)
            )

        # ── Build the governance engine ───────────────────────────────
        self.engine = GovernanceEngine(
            actions=self.actions,
            decision_engine=self.decision_engine,
            decision_context=self.decision_context,
            decision_trace=self.decision_trace,
            audit_logger=self.audit_logger,
            dry_run=self.dry_run,
            rule_engine=self.rule_engine,
            session_history=self.session_history,
            circuit_breaker=self.circuit_breaker,
            execute_request_fn=execute_request_fn,
            console_event_store=console_event_store,
            transport_type=self.transport_type,
        )

        logger.info(
            "GovernanceRuntime initialized: %d tools, transport=%s",
            len(self.actions),
            self.transport_type,
        )

    # -- Action filtering --------------------------------------------------

    def _is_action_exposed(self, action: dict[str, Any]) -> bool:
        """Check if an action should be exposed based on lockfile status.

        Uses the same multi-key lookup strategy as ToolwrightMCPServer:
        signature_id → tool_id → name, with toolset-aware filtering.
        """
        if self.lockfile_manager is None:
            return True

        from toolwright.core.approval import ApprovalStatus

        action_name = str(action.get("name", ""))
        action_signature = str(action.get("signature_id", ""))
        action_tool_id = str(
            action.get("tool_id") or action_signature or action_name
        )

        tool = (
            self.lockfile_manager.get_tool(action_signature)
            if action_signature
            else None
        )
        if tool is None:
            tool = self.lockfile_manager.get_tool(action_tool_id)
        if tool is None:
            tool = self.lockfile_manager.get_tool(action_name)
        if tool is None:
            return False

        if self.toolset_name:
            if tool.status == ApprovalStatus.REJECTED:
                return False
            if tool.toolsets and self.toolset_name not in tool.toolsets:
                return False
            if tool.approved_toolsets:
                return self.toolset_name in tool.approved_toolsets
            return tool.status == ApprovalStatus.APPROVED

        return tool.status == ApprovalStatus.APPROVED

    def maybe_reload_lockfile(self) -> None:
        """Hot-reload lockfile if it changed on disk. Call periodically."""
        import time

        if self.lockfile_path is None or self.lockfile_manager is None:
            return
        now = time.monotonic()
        if now - self._last_lockfile_check < 5.0:
            return
        self._last_lockfile_check = now
        try:
            current_mtime = self.lockfile_path.stat().st_mtime
        except OSError:
            return  # File gone or unreadable — keep last known good
        if current_mtime == self._lockfile_mtime:
            return
        try:
            lockfile = self.lockfile_manager.load()
            self.lockfile_digest_current = compute_lockfile_digest(
                lockfile.model_dump(mode="json")
            )
            self._lockfile_mtime = current_mtime
            self.decision_context.lockfile_digest_current = self.lockfile_digest_current
            logger.info("Reloaded lockfile (mtime changed)")
        except Exception as exc:
            logger.error("Failed to reload lockfile: %s", exc)

    @property
    def tool_count(self) -> int:
        """Number of exposed tools."""
        return len(self.actions)

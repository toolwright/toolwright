"""Request pipeline extracted from handle_call_tool.

Encapsulates the full tool-call lifecycle as a reusable pipeline that both
stdio and HTTP transports can invoke:

1. Action lookup + endpoint resolution
2. DecisionEngine evaluation (lockfile + policy)
3. Confirmation gate
4. Behavioral rule check (CORRECT pillar)
5. Circuit breaker check (KILL pillar)
6. Dry-run short circuit
7. HTTP execution
8. Response processing + recording (audit, session, breaker)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from toolwright.models.decision import (
    DecisionRequest,
    DecisionType,
    ReasonCode,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PipelineContext:
    """Parsed context for a single tool call."""

    name: str
    arguments: dict[str, Any]
    toolset_name: str | None

    # Separated from arguments during __post_init__
    confirmation_token_id: str | None = field(init=False, default=None)
    call_args: dict[str, Any] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        token = self.arguments.get("confirmation_token_id") or self.arguments.get(
            "_confirmation_token_id"
        )
        self.confirmation_token_id = str(token) if token else None
        self.call_args = {
            k: v
            for k, v in self.arguments.items()
            if k not in {"confirmation_token_id", "_confirmation_token_id"}
        }


@dataclass
class PipelineResult:
    """Result of pipeline execution."""

    payload: Any
    is_error: bool = False
    is_structured: bool = False
    is_raw: bool = False

    @classmethod
    def success(cls, payload: Any) -> PipelineResult:
        return cls(payload=payload, is_error=False)

    @classmethod
    def error(cls, payload: Any) -> PipelineResult:
        return cls(payload=payload, is_error=True)

    @classmethod
    def structured(cls, payload: dict[str, Any]) -> PipelineResult:
        return cls(payload=payload, is_error=False, is_structured=True)

    @classmethod
    def raw(cls, payload: Any) -> PipelineResult:
        return cls(payload=payload, is_error=False, is_raw=True)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

# Type alias for the execute_request callback
ExecuteRequestFn = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]


class RequestPipeline:
    """Reusable request pipeline for tool calls.

    Extracts the logic from handle_call_tool into a transport-agnostic pipeline
    that both stdio and HTTP transports can invoke.
    """

    def __init__(
        self,
        *,
        actions: dict[str, dict[str, Any]],
        decision_engine: Any,
        decision_context: Any,
        decision_trace: Any,
        audit_logger: Any,
        dry_run: bool = False,
        rule_engine: Any | None = None,
        session_history: Any | None = None,
        circuit_breaker: Any | None = None,
        execute_request_fn: ExecuteRequestFn | None = None,
        console_event_store: Any | None = None,
    ) -> None:
        self.actions = actions
        self.decision_engine = decision_engine
        self.decision_context = decision_context
        self.decision_trace = decision_trace
        self.audit_logger = audit_logger
        self.dry_run = dry_run
        self.rule_engine = rule_engine
        self.session_history = session_history
        self.circuit_breaker = circuit_breaker
        self._execute_request_fn = execute_request_fn
        self._console_event_store = console_event_store

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        toolset_name: str | None = None,
    ) -> PipelineResult:
        """Execute the full pipeline for a tool call."""
        ctx = PipelineContext(
            name=name,
            arguments=arguments or {},
            toolset_name=toolset_name,
        )

        # Stage 1: Action lookup
        action = self.actions.get(name)
        if not action:
            return self._handle_unknown_tool(ctx)

        # Stage 1b: Validate arguments against input_schema (if present)
        input_schema = action.get("input_schema")
        if input_schema and isinstance(input_schema, dict):
            try:
                import jsonschema

                jsonschema.validate(instance=ctx.call_args, schema=input_schema)
            except jsonschema.ValidationError as ve:
                return PipelineResult(
                    payload=f"Invalid arguments: {ve.message}",
                    is_error=True,
                )
            except ImportError:
                logger.warning("jsonschema not installed — skipping input validation for %s", name)

        # Resolve endpoint and tool_id
        method, path, host = self._resolve_action_endpoint(action)
        tool_id = str(
            action.get("tool_id") or action.get("signature_id") or name
        )
        effective_args = self._apply_fixed_body(action, ctx.call_args)

        # Stage 2: DecisionEngine evaluation
        request = DecisionRequest(
            tool_id=tool_id,
            action_name=name,
            method=method,
            path=path,
            host=host,
            params=effective_args,
            toolset_name=toolset_name,
            confirmation_token_id=ctx.confirmation_token_id,
            source="mcp",
            mode="execute",
        )
        decision = self.decision_engine.evaluate(request, self.decision_context)

        # Stage 3: Confirmation gate
        if decision.decision == DecisionType.CONFIRM:
            return self._handle_confirm(ctx, decision, tool_id)

        # Stage 2b: DENY
        if decision.decision == DecisionType.DENY:
            return self._handle_deny(ctx, decision, tool_id)

        # Stage 4: Behavioral rule check (CORRECT pillar)
        if self.rule_engine is not None and self.session_history is not None:
            rule_result = self._check_behavioral_rules(
                tool_id, method, host, effective_args, name
            )
            if rule_result is not None:
                return rule_result

        # Stage 5: Circuit breaker check (KILL pillar)
        if self.circuit_breaker is not None:
            cb_result = self._check_circuit_breaker(tool_id, name)
            if cb_result is not None:
                return cb_result

        # Stage 6: Dry-run short circuit
        if self.dry_run:
            return self._handle_dry_run(ctx, decision, tool_id, method, path, effective_args)

        # Stage 7+8: HTTP execution + response processing
        return await self._execute_and_process(
            action, effective_args, decision, tool_id, method, host, name
        )

    # -- Stage handlers ----------------------------------------------------

    def _handle_unknown_tool(self, ctx: PipelineContext) -> PipelineResult:
        self._emit_trace(
            tool_id=ctx.name,
            scope_id=ctx.toolset_name,
            request_fingerprint=None,
            decision=DecisionType.DENY.value,
            reason_code=ReasonCode.DENIED_UNKNOWN_ACTION.value,
            reason=f"Unknown tool: {ctx.name}",
        )
        return PipelineResult.error({"error": f"Unknown tool: {ctx.name}"})

    def _handle_confirm(
        self, ctx: PipelineContext, decision: Any, tool_id: str
    ) -> PipelineResult:
        self._emit_trace(
            tool_id=tool_id,
            scope_id=ctx.toolset_name,
            request_fingerprint=self._request_fingerprint(decision),
            decision=decision.decision.value,
            reason_code=decision.reason_code.value,
            reason=decision.reason_message,
        )

        # Create CONFIRMATION work item in console EventStore
        if self._console_event_store is not None and decision.confirmation_token_id:
            from toolwright.core.work_items import create_confirmation_item

            item = create_confirmation_item(
                token_id=decision.confirmation_token_id,
                tool_id=tool_id,
                arguments=ctx.call_args,
                risk_tier=str(
                    ctx.arguments.get("risk_tier", "medium")
                ),
            )
            self._console_event_store.publish_work_item(item)
            self._emit_console_event(
                "decision_confirm_required", "warn",
                f"Confirmation required: {tool_id}",
                tool_id=tool_id,
                work_item_id=item.id,
            )

        return PipelineResult.success({
            "status": "confirmation_required",
            "decision": decision.decision.value,
            "reason_code": decision.reason_code.value,
            "reason": decision.reason_message,
            "confirmation_token_id": decision.confirmation_token_id,
            "action": ctx.name,
        })

    def _handle_deny(
        self, ctx: PipelineContext, decision: Any, tool_id: str
    ) -> PipelineResult:
        self._emit_trace(
            tool_id=tool_id,
            scope_id=ctx.toolset_name,
            request_fingerprint=self._request_fingerprint(decision),
            decision=decision.decision.value,
            reason_code=decision.reason_code.value,
            reason=decision.reason_message,
        )
        return PipelineResult.error({
            "status": "blocked",
            "decision": decision.decision.value,
            "reason_code": decision.reason_code.value,
            "reason": decision.reason_message,
            "action": ctx.name,
            "audit_fields": decision.audit_fields,
        })

    def _check_behavioral_rules(
        self,
        tool_id: str,
        method: str,
        host: str,
        effective_args: dict[str, Any],
        name: str,
    ) -> PipelineResult | None:
        rule_eval = self.rule_engine.evaluate(
            tool_id, method, host, effective_args, self.session_history
        )
        if not rule_eval.allowed:
            self._emit_trace(
                tool_id=tool_id,
                scope_id=None,
                request_fingerprint=None,
                decision=DecisionType.DENY.value,
                reason_code=ReasonCode.DENIED_BEHAVIORAL_RULE.value,
                reason=rule_eval.feedback,
            )
            return PipelineResult.error({
                "status": "blocked",
                "decision": DecisionType.DENY.value,
                "reason_code": ReasonCode.DENIED_BEHAVIORAL_RULE.value,
                "reason": rule_eval.feedback,
                "action": name,
            })
        return None

    def _check_circuit_breaker(
        self, tool_id: str, name: str
    ) -> PipelineResult | None:
        cb_allowed, cb_reason = self.circuit_breaker.should_allow(tool_id)
        if not cb_allowed:
            self._emit_trace(
                tool_id=tool_id,
                scope_id=None,
                request_fingerprint=None,
                decision=DecisionType.DENY.value,
                reason_code=ReasonCode.DENIED_CIRCUIT_BREAKER_OPEN.value,
                reason=cb_reason,
            )
            return PipelineResult.error({
                "status": "blocked",
                "decision": DecisionType.DENY.value,
                "reason_code": ReasonCode.DENIED_CIRCUIT_BREAKER_OPEN.value,
                "reason": cb_reason,
                "action": name,
            })
        return None

    def _handle_dry_run(
        self,
        ctx: PipelineContext,
        decision: Any,
        tool_id: str,
        method: str,
        path: str,
        effective_args: dict[str, Any],
    ) -> PipelineResult:
        self._emit_trace(
            tool_id=tool_id,
            scope_id=ctx.toolset_name,
            request_fingerprint=self._request_fingerprint(decision),
            decision=DecisionType.ALLOW.value,
            reason_code=decision.reason_code.value,
            reason="Dry run execution",
        )
        return PipelineResult.success({
            "status": "dry_run",
            "action": ctx.name,
            "method": method,
            "path": path,
            "arguments": effective_args,
            "message": "Request would be sent (dry run mode)",
            "decision": decision.decision.value,
            "reason_code": decision.reason_code.value,
        })

    async def _execute_and_process(
        self,
        action: dict[str, Any],
        effective_args: dict[str, Any],
        decision: Any,
        tool_id: str,
        method: str,
        host: str,
        name: str,
    ) -> PipelineResult:
        from toolwright.core.network_safety import RuntimeBlockError

        try:
            if self._execute_request_fn is None:
                raise RuntimeError("No execute_request_fn configured")

            response = await self._execute_request_fn(action, effective_args)

            self._emit_trace(
                tool_id=tool_id,
                scope_id=None,
                request_fingerprint=self._request_fingerprint(decision),
                decision=DecisionType.ALLOW.value,
                reason_code=decision.reason_code.value,
                reason="Execution allowed",
            )
            self._emit_console_event(
                "tool_call_success", "success",
                f"{name} succeeded", tool_id=tool_id,
            )

            # Record in session history (CORRECT pillar)
            if self.session_history is not None:
                result_summary = (
                    str(response.get("status_code", ""))[:100]
                    if isinstance(response, dict)
                    else ""
                )
                self.session_history.record(
                    tool_id, method, host, effective_args, result_summary
                )

            # Record success in circuit breaker (KILL pillar)
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_success(tool_id)

            return self._process_response(action, response)

        except RuntimeBlockError as blocked:
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_failure(tool_id, blocked.message)
            self._emit_trace(
                tool_id=tool_id,
                scope_id=None,
                request_fingerprint=self._request_fingerprint(decision),
                decision=DecisionType.DENY.value,
                reason_code=blocked.reason_code.value,
                reason=blocked.message,
            )
            self._emit_console_event(
                "tool_call_failed", "error",
                f"{name} blocked: {blocked.message}", tool_id=tool_id,
            )
            return PipelineResult.error({
                "status": "blocked",
                "action": name,
                "decision": DecisionType.DENY.value,
                "reason_code": blocked.reason_code.value,
                "reason": blocked.message,
            })

        except Exception as e:
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_failure(tool_id, str(e))
            logger.exception("Error executing %s", name)
            self._emit_trace(
                tool_id=tool_id,
                scope_id=None,
                request_fingerprint=self._request_fingerprint(decision),
                decision=DecisionType.DENY.value,
                reason_code=ReasonCode.ERROR_INTERNAL.value,
                reason=str(e),
            )
            self._emit_console_event(
                "tool_call_failed", "error",
                f"{name} error: {e}", tool_id=tool_id,
            )
            return PipelineResult.error({
                "status": "error",
                "action": name,
                "reason_code": ReasonCode.ERROR_INTERNAL.value,
                "error": str(e),
            })

    def _process_response(
        self, action: dict[str, Any], response: Any
    ) -> PipelineResult:
        """Process execute_request response into PipelineResult.

        Matches the exact response formatting logic from handle_call_tool:
        - Non-dict responses → success
        - Dicts without status_code/data/action (non-envelope) → raw
        - 4xx+ → error
        - With output_schema + dict data → structured
        - Otherwise → success with full envelope
        """
        if not isinstance(response, dict):
            return PipelineResult.success(response)

        is_envelope = (
            "status_code" in response
            and "data" in response
            and "action" in response
        )
        if not is_envelope:
            return PipelineResult.raw(response)

        status_code = response.get("status_code")
        payload_data = response.get("data")

        if isinstance(status_code, int) and status_code >= 400:
            return PipelineResult.error(response)

        if "output_schema" in action:
            if isinstance(payload_data, dict):
                return PipelineResult.structured(payload_data)
            # Non-object data with output_schema → return data as success
            return PipelineResult.success(payload_data)

        return PipelineResult.success(response)

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _resolve_action_endpoint(action: dict[str, Any]) -> tuple[str, str, str]:
        endpoint = action.get("endpoint")
        endpoint_data = endpoint if isinstance(endpoint, dict) else {}
        method = endpoint_data.get("method") or action.get("method") or "GET"
        path = endpoint_data.get("path") or action.get("path") or "/"
        host = endpoint_data.get("host") or action.get("host") or ""
        return str(method), str(path), str(host)

    @staticmethod
    def _apply_fixed_body(
        action: dict[str, Any], arguments: dict[str, Any]
    ) -> dict[str, Any]:
        resolved = dict(arguments)
        fixed_body = action.get("fixed_body")
        if not isinstance(fixed_body, dict):
            return resolved
        for key, value in fixed_body.items():
            resolved[str(key)] = value
        return resolved

    def _emit_trace(
        self,
        *,
        tool_id: str | None,
        scope_id: str | None,
        request_fingerprint: str | None,
        decision: str,
        reason_code: str,
        reason: str | None,
    ) -> None:
        self.decision_trace.emit(
            tool_id=tool_id,
            scope_id=scope_id,
            request_fingerprint=request_fingerprint,
            decision=decision,
            reason_code=reason_code,
            provenance_mode="runtime",
            extra={"reason": reason} if reason else None,
        )

    @staticmethod
    def _request_fingerprint(decision: Any) -> str | None:
        audit_fields = getattr(decision, "audit_fields", None) or {}
        digest = audit_fields.get("request_digest")
        return str(digest) if digest else None

    def _emit_console_event(
        self,
        event_type: str,
        severity: str,
        summary: str,
        tool_id: str | None = None,
        work_item_id: str | None = None,
    ) -> None:
        """Emit an event to the console EventStore if available."""
        if self._console_event_store is None:
            return
        import time

        from toolwright.mcp.event_store import ConsoleEvent

        self._console_event_store.publish_event(
            ConsoleEvent(
                id="",
                timestamp=time.time(),
                event_type=event_type,
                severity=severity,
                summary=summary,
                tool_id=tool_id,
                work_item_id=work_item_id,
            )
        )

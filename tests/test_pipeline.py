"""Tests for the RequestPipeline extracted from handle_call_tool.

TDD RED phase: these tests define the expected behavior of the pipeline
before any implementation exists.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from toolwright.models.decision import DecisionType, ReasonCode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action(
    name: str = "get_users",
    method: str = "GET",
    path: str = "/api/users",
    host: str = "api.example.com",
    risk_tier: str = "low",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "name": name,
        "method": method,
        "path": path,
        "host": host,
        "risk_tier": risk_tier,
        "endpoint_id": f"ep_{name}",
        "input_schema": {"type": "object", "properties": {}},
        **extra,
    }


def _make_decision(
    decision: DecisionType = DecisionType.ALLOW,
    reason_code: ReasonCode = ReasonCode.ALLOWED_POLICY,
    reason_message: str = "allowed",
    confirmation_token_id: str | None = None,
    audit_fields: dict | None = None,
) -> MagicMock:
    d = MagicMock()
    d.decision = decision
    d.reason_code = reason_code
    d.reason_message = reason_message
    d.confirmation_token_id = confirmation_token_id
    d.audit_fields = audit_fields or {}
    return d


# ---------------------------------------------------------------------------
# PipelineContext + PipelineResult dataclasses
# ---------------------------------------------------------------------------


class TestPipelineContext:
    """Test PipelineContext construction and field access."""

    def test_context_from_call_args(self) -> None:
        from toolwright.mcp.pipeline import PipelineContext

        ctx = PipelineContext(
            name="get_users",
            arguments={"limit": 10},
            toolset_name=None,
        )
        assert ctx.name == "get_users"
        assert ctx.arguments == {"limit": 10}
        assert ctx.toolset_name is None

    def test_context_strips_confirmation_token(self) -> None:
        from toolwright.mcp.pipeline import PipelineContext

        ctx = PipelineContext(
            name="get_users",
            arguments={"limit": 10, "confirmation_token_id": "tok_123"},
            toolset_name=None,
        )
        # PipelineContext should separate the token from call args
        assert ctx.confirmation_token_id == "tok_123"
        assert "confirmation_token_id" not in ctx.call_args

    def test_context_strips_underscore_confirmation_token(self) -> None:
        from toolwright.mcp.pipeline import PipelineContext

        ctx = PipelineContext(
            name="get_users",
            arguments={"limit": 10, "_confirmation_token_id": "tok_456"},
            toolset_name=None,
        )
        assert ctx.confirmation_token_id == "tok_456"
        assert "_confirmation_token_id" not in ctx.call_args


class TestPipelineResult:
    """Test PipelineResult construction."""

    def test_success_result(self) -> None:
        from toolwright.mcp.pipeline import PipelineResult

        result = PipelineResult.success({"status": "success", "data": {"users": []}})
        assert result.is_error is False
        assert result.payload["status"] == "success"

    def test_error_result(self) -> None:
        from toolwright.mcp.pipeline import PipelineResult

        result = PipelineResult.error({"status": "blocked", "reason": "denied"})
        assert result.is_error is True
        assert result.payload["status"] == "blocked"

    def test_structured_result(self) -> None:
        from toolwright.mcp.pipeline import PipelineResult

        result = PipelineResult.structured({"users": []})
        assert result.is_error is False
        assert result.is_structured is True
        assert result.payload == {"users": []}


# ---------------------------------------------------------------------------
# Stage 1: Unknown tool
# ---------------------------------------------------------------------------


class TestPipelineUnknownTool:
    """Pipeline should return error for unknown tools."""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        pipeline = RequestPipeline(
            actions={},
            decision_engine=MagicMock(),
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
        )
        result = await pipeline.execute("nonexistent", {}, toolset_name=None)

        assert result.is_error is True
        assert "Unknown tool" in json.dumps(result.payload)


# ---------------------------------------------------------------------------
# Stage 2: DecisionEngine evaluation — DENY
# ---------------------------------------------------------------------------


class TestPipelineDeny:
    """Pipeline should return blocked payload when DecisionEngine denies."""

    @pytest.mark.asyncio
    async def test_deny_returns_blocked(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action()
        decision = _make_decision(
            decision=DecisionType.DENY,
            reason_code=ReasonCode.DENIED_NOT_APPROVED,
            reason_message="Not approved",
        )
        engine = MagicMock()
        engine.evaluate.return_value = decision

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
        )
        result = await pipeline.execute("get_users", {}, toolset_name=None)

        assert result.is_error is True
        assert result.payload["status"] == "blocked"
        assert result.payload["decision"] == DecisionType.DENY.value


# ---------------------------------------------------------------------------
# Stage 3: DecisionEngine evaluation — CONFIRM
# ---------------------------------------------------------------------------


class TestPipelineConfirm:
    """Pipeline should return confirmation_required when DecisionEngine confirms."""

    @pytest.mark.asyncio
    async def test_confirm_returns_confirmation_required(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action(name="create_user", method="POST", risk_tier="high")
        decision = _make_decision(
            decision=DecisionType.CONFIRM,
            reason_code=ReasonCode.CONFIRMATION_REQUIRED,
            reason_message="Confirmation needed",
            confirmation_token_id="tok_confirm_123",
        )
        engine = MagicMock()
        engine.evaluate.return_value = decision

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
        )
        result = await pipeline.execute("create_user", {}, toolset_name=None)

        assert result.is_error is False
        assert result.payload["status"] == "confirmation_required"
        assert result.payload["confirmation_token_id"] == "tok_confirm_123"


# ---------------------------------------------------------------------------
# Stage 4: Behavioral rule check (CORRECT pillar)
# ---------------------------------------------------------------------------


class TestPipelineBehavioralRules:
    """Pipeline should block when a behavioral rule is violated."""

    @pytest.mark.asyncio
    async def test_rule_violation_blocks(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action()
        decision = _make_decision()  # ALLOW
        engine = MagicMock()
        engine.evaluate.return_value = decision

        rule_engine = MagicMock()
        rule_eval = MagicMock()
        rule_eval.allowed = False
        rule_eval.feedback = "Must call get_repo before update_issue"
        rule_engine.evaluate.return_value = rule_eval

        session_history = MagicMock()

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
            rule_engine=rule_engine,
            session_history=session_history,
        )
        result = await pipeline.execute("get_users", {}, toolset_name=None)

        assert result.is_error is True
        assert result.payload["reason_code"] == ReasonCode.DENIED_BEHAVIORAL_RULE.value
        assert "get_repo" in result.payload["reason"]

    @pytest.mark.asyncio
    async def test_rule_passes_when_satisfied(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action()
        decision = _make_decision()
        engine = MagicMock()
        engine.evaluate.return_value = decision

        rule_engine = MagicMock()
        rule_eval = MagicMock()
        rule_eval.allowed = True
        rule_engine.evaluate.return_value = rule_eval

        session_history = MagicMock()
        execute_fn = AsyncMock(return_value={"status": "success", "status_code": 200, "action": "get_users", "data": {}})

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
            rule_engine=rule_engine,
            session_history=session_history,
            execute_request_fn=execute_fn,
        )
        result = await pipeline.execute("get_users", {}, toolset_name=None)

        assert result.is_error is False


# ---------------------------------------------------------------------------
# Stage 5: Circuit breaker check (KILL pillar)
# ---------------------------------------------------------------------------


class TestPipelineCircuitBreaker:
    """Pipeline should block when circuit breaker is open."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_blocks(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action()
        decision = _make_decision()
        engine = MagicMock()
        engine.evaluate.return_value = decision

        circuit_breaker = MagicMock()
        circuit_breaker.should_allow.return_value = (False, "Circuit open: 5 consecutive failures")

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
            circuit_breaker=circuit_breaker,
        )
        result = await pipeline.execute("get_users", {}, toolset_name=None)

        assert result.is_error is True
        assert result.payload["reason_code"] == ReasonCode.DENIED_CIRCUIT_BREAKER_OPEN.value

    @pytest.mark.asyncio
    async def test_circuit_breaker_closed_allows(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action()
        decision = _make_decision()
        engine = MagicMock()
        engine.evaluate.return_value = decision

        circuit_breaker = MagicMock()
        circuit_breaker.should_allow.return_value = (True, "")

        execute_fn = AsyncMock(return_value={"status": "success", "status_code": 200, "action": "get_users", "data": {}})

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
            circuit_breaker=circuit_breaker,
            execute_request_fn=execute_fn,
        )
        result = await pipeline.execute("get_users", {}, toolset_name=None)

        assert result.is_error is False
        circuit_breaker.record_success.assert_called_once_with("get_users")


# ---------------------------------------------------------------------------
# Stage 6: Dry-run short circuit
# ---------------------------------------------------------------------------


class TestPipelineDryRun:
    """Pipeline should return dry_run payload without executing request."""

    @pytest.mark.asyncio
    async def test_dry_run_does_not_execute(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action()
        decision = _make_decision()
        engine = MagicMock()
        engine.evaluate.return_value = decision

        execute_fn = AsyncMock()

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
            dry_run=True,
            execute_request_fn=execute_fn,
        )
        result = await pipeline.execute("get_users", {"limit": 10}, toolset_name=None)

        assert result.is_error is False
        assert result.payload["status"] == "dry_run"
        assert result.payload["method"] == "GET"
        execute_fn.assert_not_called()


# ---------------------------------------------------------------------------
# Stage 7+8: HTTP execution + response processing
# ---------------------------------------------------------------------------


class TestPipelineExecution:
    """Pipeline should execute the request and return processed response."""

    @pytest.mark.asyncio
    async def test_successful_execution(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action()
        decision = _make_decision()
        engine = MagicMock()
        engine.evaluate.return_value = decision

        response_data = {
            "status": "success",
            "status_code": 200,
            "action": "get_users",
            "data": {"users": [{"id": 1, "name": "Alice"}]},
        }
        execute_fn = AsyncMock(return_value=response_data)

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
            execute_request_fn=execute_fn,
        )
        result = await pipeline.execute("get_users", {"limit": 10}, toolset_name=None)

        assert result.is_error is False
        execute_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_history_recorded_on_success(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action()
        decision = _make_decision()
        engine = MagicMock()
        engine.evaluate.return_value = decision

        session_history = MagicMock()
        rule_engine = MagicMock()
        rule_eval = MagicMock()
        rule_eval.allowed = True
        rule_engine.evaluate.return_value = rule_eval

        execute_fn = AsyncMock(return_value={
            "status": "success",
            "status_code": 200,
            "action": "get_users",
            "data": {},
        })

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
            rule_engine=rule_engine,
            session_history=session_history,
            execute_request_fn=execute_fn,
        )
        result = await pipeline.execute("get_users", {}, toolset_name=None)

        assert result.is_error is False
        session_history.record.assert_called_once()

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_failure_on_error(self) -> None:
        from toolwright.core.network_safety import RuntimeBlockError
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action()
        decision = _make_decision()
        engine = MagicMock()
        engine.evaluate.return_value = decision

        circuit_breaker = MagicMock()
        circuit_breaker.should_allow.return_value = (True, "")

        execute_fn = AsyncMock(side_effect=RuntimeBlockError(
            ReasonCode.DENIED_REDIRECT_NOT_ALLOWLISTED,
            "Redirect blocked",
        ))

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
            circuit_breaker=circuit_breaker,
            execute_request_fn=execute_fn,
        )
        result = await pipeline.execute("get_users", {}, toolset_name=None)

        assert result.is_error is True
        circuit_breaker.record_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_generic_exception_records_failure(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action()
        decision = _make_decision()
        engine = MagicMock()
        engine.evaluate.return_value = decision

        circuit_breaker = MagicMock()
        circuit_breaker.should_allow.return_value = (True, "")

        execute_fn = AsyncMock(side_effect=ConnectionError("Connection refused"))

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
            circuit_breaker=circuit_breaker,
            execute_request_fn=execute_fn,
        )
        result = await pipeline.execute("get_users", {}, toolset_name=None)

        assert result.is_error is True
        assert result.payload["status"] == "error"
        circuit_breaker.record_failure.assert_called_once()


# ---------------------------------------------------------------------------
# Response processing: structured output, 4xx handling, envelope detection
# ---------------------------------------------------------------------------


class TestPipelineResponseProcessing:
    """Pipeline response formatting matches original handle_call_tool behavior."""

    @pytest.mark.asyncio
    async def test_4xx_response_returns_error(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action()
        decision = _make_decision()
        engine = MagicMock()
        engine.evaluate.return_value = decision

        execute_fn = AsyncMock(return_value={
            "status": "success",
            "status_code": 404,
            "action": "get_users",
            "data": {"error": "Not Found"},
        })

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
            execute_request_fn=execute_fn,
        )
        result = await pipeline.execute("get_users", {}, toolset_name=None)

        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_structured_output_when_output_schema(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action(output_schema={"type": "object", "properties": {"users": {"type": "array"}}})
        decision = _make_decision()
        engine = MagicMock()
        engine.evaluate.return_value = decision

        execute_fn = AsyncMock(return_value={
            "status": "success",
            "status_code": 200,
            "action": "get_users",
            "data": {"users": [{"id": 1}]},
        })

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
            execute_request_fn=execute_fn,
        )
        result = await pipeline.execute("get_users", {}, toolset_name=None)

        assert result.is_structured is True
        assert result.payload == {"users": [{"id": 1}]}

    @pytest.mark.asyncio
    async def test_non_envelope_dict_returned_as_is(self) -> None:
        """When _execute_request returns a dict without status_code/data/action keys,
        it's not an envelope — return as-is."""
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action()
        decision = _make_decision()
        engine = MagicMock()
        engine.evaluate.return_value = decision

        execute_fn = AsyncMock(return_value={"raw": "data"})

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
            execute_request_fn=execute_fn,
        )
        result = await pipeline.execute("get_users", {}, toolset_name=None)

        assert result.is_error is False
        # Non-envelope dicts are returned as raw payload
        assert result.payload == {"raw": "data"}
        assert result.is_raw is True


# ---------------------------------------------------------------------------
# Decision trace emission
# ---------------------------------------------------------------------------


class TestPipelineDecisionTrace:
    """Pipeline should emit decision traces at each gate."""

    @pytest.mark.asyncio
    async def test_trace_emitted_on_unknown_tool(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        trace = MagicMock()
        pipeline = RequestPipeline(
            actions={},
            decision_engine=MagicMock(),
            decision_context=MagicMock(),
            decision_trace=trace,
            audit_logger=MagicMock(),
        )
        await pipeline.execute("nonexistent", {}, toolset_name=None)

        trace.emit.assert_called_once()
        call_kwargs = trace.emit.call_args[1]
        assert call_kwargs["decision"] == DecisionType.DENY.value
        assert call_kwargs["reason_code"] == ReasonCode.DENIED_UNKNOWN_ACTION.value

    @pytest.mark.asyncio
    async def test_trace_emitted_on_allow(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action()
        decision = _make_decision()
        engine = MagicMock()
        engine.evaluate.return_value = decision
        trace = MagicMock()

        execute_fn = AsyncMock(return_value={
            "status": "success",
            "status_code": 200,
            "action": "get_users",
            "data": {},
        })

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=trace,
            audit_logger=MagicMock(),
            execute_request_fn=execute_fn,
        )
        await pipeline.execute("get_users", {}, toolset_name=None)

        # Trace should be called for the ALLOW decision
        allow_calls = [
            c for c in trace.emit.call_args_list
            if c[1].get("decision") == DecisionType.ALLOW.value
        ]
        assert len(allow_calls) >= 1


# ---------------------------------------------------------------------------
# Fixed body application
# ---------------------------------------------------------------------------


class TestPipelineFixedBody:
    """Pipeline should merge fixed_body fields into arguments."""

    @pytest.mark.asyncio
    async def test_fixed_body_merged(self) -> None:
        from toolwright.mcp.pipeline import RequestPipeline

        action = _make_action(fixed_body={"api_version": "v2"})
        decision = _make_decision()
        engine = MagicMock()
        engine.evaluate.return_value = decision

        captured_args: dict = {}

        async def mock_execute(_action: dict, args: dict) -> dict:
            captured_args.update(args)
            return {"status": "success", "status_code": 200, "action": "get_users", "data": {}}

        pipeline = RequestPipeline(
            actions={action["name"]: action},
            decision_engine=engine,
            decision_context=MagicMock(),
            decision_trace=MagicMock(),
            audit_logger=MagicMock(),
            execute_request_fn=mock_execute,
        )
        await pipeline.execute("get_users", {"limit": 10}, toolset_name=None)

        assert captured_args.get("api_version") == "v2"
        assert captured_args.get("limit") == 10

"""Tests for input schema validation on tool calls (Phase 4.4).

The pipeline should validate tool call arguments against the tool's
input_schema before executing the decision engine evaluation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from toolwright.mcp.pipeline import PipelineResult, RequestPipeline
from toolwright.models.decision import DecisionType, ReasonCode


def _make_action(
    name: str = "search",
    method: str = "GET",
    path: str = "/api/search",
    host: str = "api.example.com",
    input_schema: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    action: dict[str, Any] = {
        "name": name,
        "method": method,
        "path": path,
        "host": host,
        "risk_tier": "low",
        "endpoint_id": f"ep_{name}",
    }
    if input_schema is not None:
        action["input_schema"] = input_schema
    else:
        action["input_schema"] = {"type": "object", "properties": {}}
    action.update(extra)
    return action


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


def _make_pipeline(
    actions: dict[str, dict[str, Any]],
    decision: Any | None = None,
    execute_fn: Any | None = None,
) -> RequestPipeline:
    """Create a pipeline with mocked dependencies."""
    decision_engine = MagicMock()
    if decision is not None:
        decision_engine.evaluate.return_value = decision

    decision_context = MagicMock()
    decision_trace = MagicMock()
    audit_logger = MagicMock()

    return RequestPipeline(
        actions=actions,
        decision_engine=decision_engine,
        decision_context=decision_context,
        decision_trace=decision_trace,
        audit_logger=audit_logger,
        dry_run=True,  # dry_run avoids needing an actual HTTP client
        execute_request_fn=execute_fn or AsyncMock(return_value={"status": "ok"}),
    )


class TestInputSchemaValidation:
    """Tests for validating tool call arguments against input_schema."""

    @pytest.mark.asyncio
    async def test_missing_required_field_returns_error(self) -> None:
        """Calling a tool with a required field missing should return an error."""
        action = _make_action(
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        )
        pipeline = _make_pipeline(
            actions={"search": action},
            decision=_make_decision(),
        )

        result = await pipeline.execute("search", {})

        assert isinstance(result, PipelineResult)
        assert result.is_error is True
        assert "Invalid arguments" in str(result.payload)

    @pytest.mark.asyncio
    async def test_wrong_type_returns_error(self) -> None:
        """Calling a tool with wrong argument type should return an error."""
        action = _make_action(
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                },
                "required": ["limit"],
            },
        )
        pipeline = _make_pipeline(
            actions={"search": action},
            decision=_make_decision(),
        )

        result = await pipeline.execute("search", {"limit": "not-an-int"})

        assert isinstance(result, PipelineResult)
        assert result.is_error is True
        assert "Invalid arguments" in str(result.payload)

    @pytest.mark.asyncio
    async def test_valid_args_pass_validation(self) -> None:
        """Valid arguments should pass schema validation and proceed."""
        action = _make_action(
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        )
        pipeline = _make_pipeline(
            actions={"search": action},
            decision=_make_decision(),
        )

        result = await pipeline.execute("search", {"query": "hello"})

        assert isinstance(result, PipelineResult)
        # Should NOT be an error — validation passed, dry_run result
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_no_input_schema_skips_validation(self) -> None:
        """If no input_schema is present, validation should be skipped."""
        action = _make_action(name="noop")
        # Remove input_schema entirely
        del action["input_schema"]

        pipeline = _make_pipeline(
            actions={"noop": action},
            decision=_make_decision(),
        )

        result = await pipeline.execute("noop", {"anything": "goes"})

        assert isinstance(result, PipelineResult)
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_empty_schema_passes_any_args(self) -> None:
        """An empty object schema should accept any arguments."""
        action = _make_action(
            input_schema={"type": "object", "properties": {}},
        )
        pipeline = _make_pipeline(
            actions={"search": action},
            decision=_make_decision(),
        )

        result = await pipeline.execute("search", {"foo": "bar", "baz": 123})

        assert isinstance(result, PipelineResult)
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_validation_happens_before_decision_engine(self) -> None:
        """Schema validation should happen before the decision engine is called."""
        action = _make_action(
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        )
        decision_engine = MagicMock()
        pipeline = _make_pipeline(
            actions={"search": action},
            decision=_make_decision(),
        )
        # Replace decision engine to track calls
        pipeline.decision_engine = decision_engine

        result = await pipeline.execute("search", {})

        # Validation should fail BEFORE decision engine is called
        assert result.is_error is True
        assert "Invalid arguments" in str(result.payload)
        decision_engine.evaluate.assert_not_called()

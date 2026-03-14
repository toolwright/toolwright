"""Transport conformance tests — governance parity across transports.

Ensures that GovernanceEngine produces identical DecisionTrace output
regardless of transport (MCP, CLI, REST). This is the critical safety net
preventing governance behavior from silently drifting between transports.

Currently tests MCP transport. As CLI and REST adapters are added,
each scenario will be parameterized across all transports.

Scenarios:
  - approve: approved tool executes successfully
  - deny_unknown: unknown tool is denied
  - deny_unapproved: unapproved tool (not in lockfile) is denied
  - deny_dry_run: dry-run mode short-circuits execution
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_manifest(tmp_path: Path, actions: list[dict[str, Any]]) -> Path:
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "name": "Conformance Tools",
                "actions": actions,
            }
        )
    )
    return tools_path


BASIC_ACTION = {
    "name": "get_users",
    "tool_id": "sig_get_users",
    "description": "Get users",
    "method": "GET",
    "path": "/users",
    "host": "api.example.com",
    "input_schema": {"type": "object", "properties": {}},
    "risk_tier": "low",
}


# ---------------------------------------------------------------------------
# Conformance scenarios — currently MCP-only, parameterize when adding CLI/REST
# ---------------------------------------------------------------------------

# Transport identifiers — add new transports here as adapters are built
TRANSPORTS = ["mcp", "cli"]


@pytest.fixture(params=TRANSPORTS)
def transport_type(request: pytest.FixtureRequest) -> str:
    return request.param


class TestConformance_Approve:
    """Approved tool executes through the pipeline."""

    @pytest.mark.anyio
    async def test_approved_tool_executes(
        self, tmp_path: Path, transport_type: str
    ) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_manifest(tmp_path, [BASIC_ACTION])
        mock_execute = AsyncMock(
            return_value={"status": 200, "body": '{"users": []}'}
        )
        runtime = GovernanceRuntime(
            tools_path=tools_path,
            transport_type=transport_type,
            execute_request_fn=mock_execute,
        )

        result = await runtime.engine.execute("get_users", {})
        assert result is not None
        assert runtime.engine.transport_type == transport_type


class TestConformance_DenyUnknown:
    """Unknown tool is denied across all transports."""

    @pytest.mark.anyio
    async def test_unknown_tool_denied(
        self, tmp_path: Path, transport_type: str
    ) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_manifest(tmp_path, [BASIC_ACTION])
        runtime = GovernanceRuntime(
            tools_path=tools_path,
            transport_type=transport_type,
        )

        result = await runtime.engine.execute("nonexistent_tool", {})
        assert result.is_error
        assert "Unknown tool" in str(result.payload)


class TestConformance_DryRun:
    """Dry-run mode short-circuits execution across all transports."""

    @pytest.mark.anyio
    async def test_dry_run_no_execution(
        self, tmp_path: Path, transport_type: str
    ) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_manifest(tmp_path, [BASIC_ACTION])
        mock_execute = AsyncMock()
        runtime = GovernanceRuntime(
            tools_path=tools_path,
            transport_type=transport_type,
            execute_request_fn=mock_execute,
            dry_run=True,
        )

        result = await runtime.engine.execute("get_users", {})
        # Dry run should not call the execute function
        mock_execute.assert_not_called()
        assert result is not None


class TestConformance_TransportTypeInDecision:
    """DecisionRequest.source reflects the transport type."""

    @pytest.mark.anyio
    async def test_source_matches_transport(
        self, tmp_path: Path, transport_type: str
    ) -> None:
        """The DecisionRequest.source field matches the transport_type."""
        from unittest.mock import MagicMock, patch

        from toolwright.core.governance.runtime import GovernanceRuntime
        from toolwright.models.decision import DecisionType, ReasonCode

        tools_path = _write_manifest(tmp_path, [BASIC_ACTION])
        runtime = GovernanceRuntime(
            tools_path=tools_path,
            transport_type=transport_type,
        )

        # Patch decision_engine.evaluate to capture the DecisionRequest
        captured_requests: list[Any] = []
        original_evaluate = runtime.engine.decision_engine.evaluate

        def capture_evaluate(request: Any, context: Any) -> Any:
            captured_requests.append(request)
            return original_evaluate(request, context)

        runtime.engine.decision_engine.evaluate = capture_evaluate

        await runtime.engine.execute("get_users", {})

        assert len(captured_requests) == 1
        assert captured_requests[0].source == transport_type

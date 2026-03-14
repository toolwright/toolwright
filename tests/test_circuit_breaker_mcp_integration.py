"""Tests for circuit breaker integration with the MCP server.

Tests that the MCP server correctly checks circuit breakers before execution
and records successes/failures after execution.
"""

from __future__ import annotations

from pathlib import Path

from toolwright.core.kill.breaker import CircuitBreakerRegistry
from toolwright.models.decision import ReasonCode

# ---------------------------------------------------------------------------
# Tests: ReasonCode enum has new entry
# ---------------------------------------------------------------------------


class TestReasonCodeEnum:
    """Test that DENIED_CIRCUIT_BREAKER_OPEN exists in ReasonCode."""

    def test_circuit_breaker_reason_code_exists(self):
        assert hasattr(ReasonCode, "DENIED_CIRCUIT_BREAKER_OPEN")
        assert ReasonCode.DENIED_CIRCUIT_BREAKER_OPEN == "denied_circuit_breaker_open"


# ---------------------------------------------------------------------------
# Tests: Server accepts circuit_breaker_path parameter
# ---------------------------------------------------------------------------


class TestServerInit:
    """Test MCP server accepts circuit breaker configuration."""

    def test_server_init_without_circuit_breaker(self):
        """Server should work fine without circuit breaker config."""
        from toolwright.mcp.server import ToolwrightMCPServer

        server = ToolwrightMCPServer(
            tools_path=str(Path(__file__).parent / "fixtures" / "tools_minimal.json"),
        )
        assert server.circuit_breaker is None

    def test_server_init_with_circuit_breaker_path(self, tmp_path: Path):
        """Server should initialize circuit breaker when path provided."""
        from toolwright.mcp.server import ToolwrightMCPServer

        tools_fixture = Path(__file__).parent / "fixtures" / "tools_minimal.json"
        state_path = tmp_path / "breakers.json"
        server = ToolwrightMCPServer(
            tools_path=str(tools_fixture),
            circuit_breaker_path=str(state_path),
        )
        assert server.circuit_breaker is not None
        assert isinstance(server.circuit_breaker, CircuitBreakerRegistry)


# ---------------------------------------------------------------------------
# Tests: Circuit breaker blocks killed tools
# ---------------------------------------------------------------------------


class TestCircuitBreakerBlocking:
    """Test that killed tools are blocked by the circuit breaker."""

    def test_killed_tool_should_be_blocked(self, tmp_path: Path):
        """When a tool is killed, the circuit breaker should block it."""
        state_path = tmp_path / "breakers.json"
        reg = CircuitBreakerRegistry(state_path=state_path)
        reg.kill_tool("get_users", reason="testing")

        allowed, reason = reg.should_allow("get_users")
        assert allowed is False
        assert "killed" in reason.lower()

    def test_healthy_tool_should_pass(self, tmp_path: Path):
        """When a tool has no breaker issues, it should pass."""
        state_path = tmp_path / "breakers.json"
        reg = CircuitBreakerRegistry(state_path=state_path)

        allowed, reason = reg.should_allow("healthy_tool")
        assert allowed is True

    def test_tripped_breaker_blocks_tool(self, tmp_path: Path):
        """When a tool has tripped its circuit breaker, it should be blocked."""
        state_path = tmp_path / "breakers.json"
        reg = CircuitBreakerRegistry(state_path=state_path)

        # Trip the breaker
        for i in range(5):
            reg.record_failure("flaky_tool", f"error_{i}")

        allowed, reason = reg.should_allow("flaky_tool")
        assert allowed is False


# ---------------------------------------------------------------------------
# Tests: run_mcp_server accepts circuit_breaker_path
# ---------------------------------------------------------------------------


class TestRunMcpServer:
    """Test that run_mcp_server accepts circuit_breaker_path parameter."""

    def test_run_mcp_server_signature_includes_circuit_breaker_path(self):
        """Verify the function signature includes the new parameter."""
        import inspect

        from toolwright.mcp.server import run_mcp_server

        sig = inspect.signature(run_mcp_server)
        assert "circuit_breaker_path" in sig.parameters

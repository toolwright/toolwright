"""End-to-end integration test for the full Toolwright pipeline.

Tests the complete loop:
  connect → use → correct → break → heal → kill → recover

This validates that all five pillars work together seamlessly.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from toolwright.core.correct.engine import RuleEngine
from toolwright.core.correct.session import SessionHistory
from toolwright.core.health.checker import FailureClass, HealthChecker
from toolwright.core.kill.breaker import CircuitBreakerRegistry
from toolwright.mcp.meta_server import ToolwrightMetaMCPServer
from toolwright.models.rule import BehavioralRule, PrerequisiteConfig, RuleKind

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_tools(tmp_path: Path) -> Path:
    """Create a minimal tool manifest."""
    manifest = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "E2E Test Tools",
        "allowed_hosts": ["api.example.com"],
        "actions": [
            {
                "name": "get_user",
                "method": "GET",
                "path": "/api/users/{user_id}",
                "host": "api.example.com",
                "risk_tier": "low",
            },
            {
                "name": "update_user",
                "method": "PUT",
                "path": "/api/users/{user_id}",
                "host": "api.example.com",
                "risk_tier": "medium",
            },
            {
                "name": "delete_user",
                "method": "DELETE",
                "path": "/api/users/{user_id}",
                "host": "api.example.com",
                "risk_tier": "high",
            },
        ],
    }
    p = tmp_path / "tools.json"
    p.write_text(json.dumps(manifest))
    return p


@pytest.fixture
def tmp_rules(tmp_path: Path) -> Path:
    return tmp_path / "rules.json"


@pytest.fixture
def tmp_breakers(tmp_path: Path) -> Path:
    return tmp_path / "breakers.json"


# ---------------------------------------------------------------------------
# E2E: CORRECT + Session tracking
# ---------------------------------------------------------------------------


class TestCorrectPillarE2E:
    """Agent calls tools → session recorded → rules enforced."""

    def test_session_recording(self, tmp_rules: Path):
        """Tool calls are recorded in session history."""
        _ = tmp_rules
        session = SessionHistory()
        session.record("get_user", "GET", "api.example.com", {"user_id": "123"}, "ok")

        assert session.has_called("get_user") is True
        assert session.has_called("update_user") is False
        assert session.call_count() == 1

    def test_prerequisite_blocks_without_prior_call(
        self, tmp_rules: Path
    ):
        """update_user blocked when get_user hasn't been called."""
        engine = RuleEngine(tmp_rules)
        session = SessionHistory()

        # Add prerequisite rule
        rule = BehavioralRule(
            rule_id=str(uuid4()),
            kind=RuleKind.PREREQUISITE,
            description="Must call get_user before update_user",
            target_tool_ids=["update_user"],
            config=PrerequisiteConfig(required_tool_ids=["get_user"]),
        )
        engine.add_rule(rule)

        # Try update without prior get -- should be blocked
        result = engine.evaluate("update_user", "PUT", "api.example.com", {}, session)
        assert result.allowed is False
        assert len(result.violations) == 1
        assert "prerequisite" in result.feedback.lower()

    def test_prerequisite_allows_after_prior_call(
        self, tmp_rules: Path
    ):
        """update_user allowed after get_user has been called."""
        engine = RuleEngine(tmp_rules)
        session = SessionHistory()

        rule = BehavioralRule(
            rule_id=str(uuid4()),
            kind=RuleKind.PREREQUISITE,
            description="Must call get_user before update_user",
            target_tool_ids=["update_user"],
            config=PrerequisiteConfig(required_tool_ids=["get_user"]),
        )
        engine.add_rule(rule)

        # Call get_user first
        session.record("get_user", "GET", "api.example.com", {"user_id": "123"}, "ok")

        # Now update should be allowed
        result = engine.evaluate("update_user", "PUT", "api.example.com", {}, session)
        assert result.allowed is True
        assert len(result.violations) == 0


# ---------------------------------------------------------------------------
# E2E: KILL (circuit breaker) lifecycle
# ---------------------------------------------------------------------------


class TestKillPillarE2E:
    """Circuit breaker trips → quarantine → enable → recovery."""

    def test_breaker_trips_after_failures(self, tmp_breakers: Path):
        """5 consecutive failures trip the breaker OPEN."""
        registry = CircuitBreakerRegistry(state_path=tmp_breakers)

        # 5 failures should trip the breaker
        for i in range(5):
            allowed, _ = registry.should_allow("flaky_api")
            assert allowed is True, f"Should allow on attempt {i}"
            registry.record_failure("flaky_api", f"Error #{i}")

        allowed, reason = registry.should_allow("flaky_api")
        assert allowed is False
        assert "open" in reason.lower()

    def test_quarantine_shows_tripped_tool(self, tmp_breakers: Path):
        """Quarantine report lists tripped tools."""
        registry = CircuitBreakerRegistry(state_path=tmp_breakers)

        for _ in range(5):
            registry.should_allow("flaky_api")
            registry.record_failure("flaky_api", "Error")

        report = registry.quarantine_report()
        tool_ids = [entry.tool_id for entry in report]
        assert "flaky_api" in tool_ids

    def test_manual_kill_and_enable(self, tmp_breakers: Path):
        """Manual kill → enable restores the tool."""
        registry = CircuitBreakerRegistry(state_path=tmp_breakers)

        # Kill
        registry.kill_tool("get_user", "Testing kill switch")
        allowed, _ = registry.should_allow("get_user")
        assert allowed is False

        # Enable
        registry.enable_tool("get_user")
        allowed, _ = registry.should_allow("get_user")
        assert allowed is True


# ---------------------------------------------------------------------------
# E2E: HEAL (health checker)
# ---------------------------------------------------------------------------


class TestHealPillarE2E:
    """Health checker classifies failures correctly."""

    def test_classify_common_failures(self):
        """Different status codes map to correct failure classes."""
        checks = [
            (401, FailureClass.AUTH_EXPIRED),
            (403, FailureClass.AUTH_EXPIRED),
            (404, FailureClass.ENDPOINT_GONE),
            (429, FailureClass.RATE_LIMITED),
            (500, FailureClass.SERVER_ERROR),
            (503, FailureClass.SERVER_ERROR),
        ]
        for status, expected in checks:
            result = HealthChecker.classify_failure(status)
            assert result == expected, f"Status {status} should be {expected}, got {result}"


# ---------------------------------------------------------------------------
# E2E: Meta-server integration (all pillars via MCP)
# ---------------------------------------------------------------------------


class TestMetaServerE2E:
    """Meta-server exposes all pillar operations as MCP tools."""

    @pytest.mark.asyncio
    async def test_full_meta_loop(
        self, tmp_tools: Path, tmp_rules: Path, tmp_breakers: Path
    ):
        """Full loop via meta-server:
        1. List tools → sees get_user
        2. Add prerequisite rule → rule created
        3. List rules → confirms rule exists
        4. Kill get_user → breaker opens
        5. Quarantine → sees get_user
        6. Enable get_user → breaker closes
        7. Remove rule → cleaned up
        """
        server = ToolwrightMetaMCPServer(
            tools_path=str(tmp_tools),
            rules_path=str(tmp_rules),
            circuit_breaker_path=str(tmp_breakers),
        )

        # 1. List tools
        tools = await server._handle_list_tools()
        tool_names = [t.name for t in tools]
        assert "toolwright_list_actions" in tool_names

        # 2. Add prerequisite rule
        result = await server._handle_call_tool(
            "toolwright_add_rule",
            {
                "kind": "prerequisite",
                "target_tool_id": "update_user",
                "description": "Must fetch user first",
                "required_tool_ids": ["get_user"],
            },
        )
        data = json.loads(result[0].text)
        assert "rule_id" in data
        rule_id = data["rule_id"]

        # 3. List rules
        result = await server._handle_call_tool("toolwright_list_rules", {})
        data = json.loads(result[0].text)
        assert data["total"] == 1
        assert data["rules"][0]["rule_id"] == rule_id

        # 4. Kill get_user
        result = await server._handle_call_tool(
            "toolwright_kill_tool",
            {"tool_id": "get_user", "reason": "E2E test"},
        )
        data = json.loads(result[0].text)
        assert data["state"] == "open"

        # 5. Quarantine shows get_user
        result = await server._handle_call_tool("toolwright_quarantine_report", {})
        data = json.loads(result[0].text)
        assert data["total"] == 1
        assert data["tools"][0]["tool_id"] == "get_user"

        # 6. Enable via agent is blocked (removed for security)
        result = await server._handle_call_tool(
            "toolwright_enable_tool", {"tool_id": "get_user"}
        )
        data = json.loads(result[0].text)
        assert "error" in data, "enable_tool should be rejected for agents"

        # 7. Re-enable via circuit breaker directly (simulates human CLI path)
        server.circuit_breaker.enable_tool("get_user")

        # 8. Quarantine now empty
        result = await server._handle_call_tool("toolwright_quarantine_report", {})
        data = json.loads(result[0].text)
        assert data["total"] == 0

        # 8. Remove rule
        result = await server._handle_call_tool(
            "toolwright_remove_rule", {"rule_id": rule_id}
        )
        data = json.loads(result[0].text)
        assert data["removed"] is True

        # 9. Confirm rules are empty
        result = await server._handle_call_tool("toolwright_list_rules", {})
        data = json.loads(result[0].text)
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_diagnose_tool(self, tmp_tools: Path):
        """Diagnose tool provides useful information."""
        server = ToolwrightMetaMCPServer(tools_path=str(tmp_tools))
        result = await server._handle_call_tool(
            "toolwright_diagnose_tool", {"tool_id": "get_user"}
        )
        data = json.loads(result[0].text)
        assert data["tool_id"] == "get_user"
        assert "in_manifest" in data

    @pytest.mark.asyncio
    async def test_health_check(self, tmp_tools: Path):
        """Health check reports tool existence."""
        server = ToolwrightMetaMCPServer(tools_path=str(tmp_tools))
        result = await server._handle_call_tool(
            "toolwright_health_check", {"tool_id": "get_user"}
        )
        data = json.loads(result[0].text)
        assert data["tool_id"] == "get_user"
        assert data["exists"] is True


# ---------------------------------------------------------------------------
# E2E: Cross-pillar scenario
# ---------------------------------------------------------------------------


class TestCrossPillarE2E:
    """Tests that involve multiple pillars working together."""

    def test_correct_then_kill_then_heal(
        self, tmp_rules: Path, tmp_breakers: Path
    ):
        """Scenario: rule blocks call, then tool is killed, then healed.

        1. Create prerequisite rule for update_user
        2. Verify rule blocks update without prior get
        3. Kill update_user via breaker
        4. Verify breaker blocks independently of rules
        5. Enable update_user
        6. Verify rule still applies after breaker reset
        """
        engine = RuleEngine(tmp_rules)
        session = SessionHistory()
        registry = CircuitBreakerRegistry(state_path=tmp_breakers)

        # 1. Add prerequisite rule
        rule = BehavioralRule(
            rule_id="prereq-1",
            kind=RuleKind.PREREQUISITE,
            description="Must get before update",
            target_tool_ids=["update_user"],
            config=PrerequisiteConfig(required_tool_ids=["get_user"]),
        )
        engine.add_rule(rule)

        # 2. Rule blocks
        result = engine.evaluate("update_user", "PUT", "api.example.com", {}, session)
        assert result.allowed is False

        # 3. Kill tool
        registry.kill_tool("update_user", "Maintenance")
        allowed, _ = registry.should_allow("update_user")
        assert allowed is False

        # 5. Enable tool
        registry.enable_tool("update_user")
        allowed, _ = registry.should_allow("update_user")
        assert allowed is True

        # 6. Rule still applies (breaker is independent)
        result = engine.evaluate("update_user", "PUT", "api.example.com", {}, session)
        assert result.allowed is False

        # Now satisfy the prerequisite
        session.record("get_user", "GET", "api.example.com", {"user_id": "1"}, "ok")
        result = engine.evaluate("update_user", "PUT", "api.example.com", {}, session)
        assert result.allowed is True

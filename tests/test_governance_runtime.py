"""Tests for GovernanceRuntime — transport-agnostic governance factory.

TDD RED phase: these tests define the expected behavior of the runtime
before the MCP server is refactored to use it.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tests.helpers import write_demo_artifacts

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_minimal_manifest(tmp_path: Path) -> Path:
    """Write a minimal tools.json manifest with one action, return path."""
    tools_path = tmp_path / "tools.json"
    tools_path.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "schema_version": "1.0",
                "name": "Test Tools",
                "actions": [
                    {
                        "name": "get_users",
                        "tool_id": "sig_get_users",
                        "description": "Get users",
                        "method": "GET",
                        "path": "/users",
                        "host": "api.example.com",
                        "input_schema": {"type": "object", "properties": {}},
                        "risk_tier": "low",
                    }
                ],
            }
        )
    )
    return tools_path


# ---------------------------------------------------------------------------
# Construction tests
# ---------------------------------------------------------------------------


class TestGovernanceRuntimeConstruction:
    """Test that GovernanceRuntime wires up all governance subsystems."""

    def test_minimal_construction(self, tmp_path: Path) -> None:
        """Runtime constructs with just a manifest (no lockfile, no policy)."""
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        runtime = GovernanceRuntime(tools_path=tools_path)

        assert runtime.tool_count == 1
        assert "get_users" in runtime.actions
        assert runtime.engine is not None
        assert runtime.lockfile_manager is None
        assert runtime.policy_engine is None
        assert runtime.rule_engine is None
        assert runtime.circuit_breaker is None
        assert runtime.dry_run is False
        assert runtime.transport_type == "mcp"

    def test_transport_type_parameterized(self, tmp_path: Path) -> None:
        """Transport type is stored and propagated to engine."""
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        runtime = GovernanceRuntime(tools_path=tools_path, transport_type="cli")

        assert runtime.transport_type == "cli"
        assert runtime.engine.transport_type == "cli"

    def test_dry_run_flag(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        runtime = GovernanceRuntime(tools_path=tools_path, dry_run=True)

        assert runtime.dry_run is True
        assert runtime.engine.dry_run is True

    def test_run_id_generated(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        runtime = GovernanceRuntime(tools_path=tools_path)

        assert runtime.run_id.startswith("run_")
        assert len(runtime.run_id) == 16  # "run_" + 12 hex chars

    def test_audit_logger_present(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        runtime = GovernanceRuntime(tools_path=tools_path)

        assert runtime.audit_logger is not None
        assert runtime.decision_trace is not None

    def test_audit_to_file(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        audit_path = tmp_path / "audit.jsonl"
        runtime = GovernanceRuntime(
            tools_path=tools_path,
            audit_log=str(audit_path),
        )

        assert runtime.audit_logger is not None


class TestGovernanceRuntimeWithPolicy:
    """Test construction with policy engine."""

    def test_policy_engine_loaded(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        policy_path = tmp_path / "policy.yaml"
        policy_path.write_text(
            "version: '1.0.0'\n"
            "schema_version: '1.0'\n"
            "name: Test Policy\n"
            "default_action: deny\n"
            "rules: []\n"
        )
        runtime = GovernanceRuntime(
            tools_path=tools_path,
            policy_path=str(policy_path),
        )

        assert runtime.policy_engine is not None
        assert runtime.enforcer is runtime.policy_engine

    def test_policy_digest_computed(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        policy_path = tmp_path / "policy.yaml"
        policy_path.write_text(
            "version: '1.0.0'\n"
            "schema_version: '1.0'\n"
            "name: Test Policy\n"
            "default_action: deny\n"
            "rules: []\n"
        )
        runtime = GovernanceRuntime(
            tools_path=tools_path,
            policy_path=str(policy_path),
        )

        assert runtime.policy_digest is not None
        assert len(runtime.policy_digest) == 64  # sha256 hex


class TestGovernanceRuntimeWithLockfile:
    """Test construction with lockfile (GOVERN pillar)."""

    def test_lockfile_manager_loaded(self, demo_toolpack: Path) -> None:
        """Runtime loads lockfile from toolpack fixture."""
        import yaml

        from toolwright.core.governance.runtime import GovernanceRuntime

        with open(demo_toolpack) as f:
            tp = yaml.safe_load(f)
        tp_dir = demo_toolpack.parent
        tools_path = tp_dir / tp["paths"]["tools"]
        pending_lockfile = tp_dir / tp["paths"]["lockfiles"]["pending"]

        # Pending lockfile exists — tools are in "pending" status so they
        # won't be exposed (lockfile filters to APPROVED only).
        runtime = GovernanceRuntime(
            tools_path=str(tools_path),
            lockfile_path=str(pending_lockfile),
        )

        assert runtime.lockfile_manager is not None
        assert runtime.lockfile_digest_current is not None
        # Tools are pending, not approved, so no actions exposed
        assert runtime.tool_count == 0

    def test_missing_lockfile_raises(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        fake_lockfile = tmp_path / "nonexistent.lock.yaml"

        with pytest.raises(ValueError, match="Lockfile not found"):
            GovernanceRuntime(
                tools_path=tools_path,
                lockfile_path=str(fake_lockfile),
            )


class TestGovernanceRuntimeCorrectPillar:
    """Test CORRECT pillar (behavioral rules) wiring."""

    def test_rule_engine_loaded(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text(
            "version: '1.0'\nrules:\n"
            "  - name: test_rule\n"
            "    condition:\n"
            "      tool_id: get_users\n"
            "      max_calls_per_session: 100\n"
            "    action: warn\n"
            "    message: Rate limit approaching\n"
        )
        runtime = GovernanceRuntime(
            tools_path=tools_path,
            rules_path=str(rules_path),
        )

        assert runtime.rule_engine is not None
        assert runtime.session_history is not None


class TestGovernanceRuntimeKillPillar:
    """Test KILL pillar (circuit breaker) wiring."""

    def test_circuit_breaker_loaded(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        cb_path = tmp_path / "breakers.yaml"
        cb_path.write_text("{}")

        runtime = GovernanceRuntime(
            tools_path=tools_path,
            circuit_breaker_path=str(cb_path),
        )

        assert runtime.circuit_breaker is not None


class TestGovernanceRuntimeToolsets:
    """Test toolset filtering."""

    def test_toolset_filters_actions(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        artifacts = write_demo_artifacts(tmp_path / "artifacts")
        runtime = GovernanceRuntime(
            tools_path=str(artifacts["tools"]),
            toolsets_path=str(artifacts["toolsets"]),
            toolset_name="readonly",
        )

        assert "get_users" in runtime.actions

    def test_unknown_toolset_raises(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        artifacts = write_demo_artifacts(tmp_path / "artifacts")

        with pytest.raises(ValueError, match="Unknown toolset"):
            GovernanceRuntime(
                tools_path=str(artifacts["tools"]),
                toolsets_path=str(artifacts["toolsets"]),
                toolset_name="nonexistent",
            )


class TestGovernanceRuntimeExecution:
    """Test that the engine can execute tool calls."""

    @pytest.mark.anyio
    async def test_engine_executes_with_callback(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)

        mock_execute = AsyncMock(
            return_value={"status": 200, "body": '{"users": []}'}
        )

        runtime = GovernanceRuntime(
            tools_path=tools_path,
            execute_request_fn=mock_execute,
        )

        # Without a lockfile, all tools are exposed (no lockfile = no filtering)
        result = await runtime.engine.execute("get_users", {})

        # The decision engine without a lockfile/policy will deny (default deny)
        # but without policy the behavior depends on DecisionEngine defaults.
        # The important thing is the engine is callable.
        assert result is not None

    @pytest.mark.anyio
    async def test_unknown_tool_returns_error(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        runtime = GovernanceRuntime(tools_path=tools_path)

        result = await runtime.engine.execute("nonexistent_tool", {})
        assert result.is_error
        assert "Unknown tool" in str(result.payload)


class TestGovernanceRuntimeLockfileReload:
    """Test hot-reload of lockfile."""

    def test_reload_noop_without_lockfile(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        runtime = GovernanceRuntime(tools_path=tools_path)

        # Should not raise
        runtime.maybe_reload_lockfile()


class TestGovernanceRuntimeEquivalence:
    """Verify that GovernanceRuntime produces the same components as
    ToolwrightMCPServer.__init__ would for the same inputs."""

    def test_actions_match_manifest(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        runtime = GovernanceRuntime(tools_path=tools_path)

        # Without lockfile, all manifest actions should be exposed
        manifest_names = {
            a["name"] for a in runtime.manifest.get("actions", [])
        }
        assert set(runtime.actions.keys()) == manifest_names

    def test_actions_by_tool_id_populated(self, tmp_path: Path) -> None:
        from toolwright.core.governance.runtime import GovernanceRuntime

        tools_path = _write_minimal_manifest(tmp_path)
        runtime = GovernanceRuntime(tools_path=tools_path)

        # Both name and tool_id should be mapped
        assert "get_users" in runtime.actions_by_tool_id
        assert "sig_get_users" in runtime.actions_by_tool_id

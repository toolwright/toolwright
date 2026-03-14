"""Tests for the token estimator module."""

from __future__ import annotations

import json

from toolwright.core.token_estimator import TokenEstimator, TransportEstimate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action(
    name: str = "get_users",
    description: str = "List all users",
    method: str = "GET",
    input_schema: dict | None = None,
) -> dict:
    """Build a minimal tools.json action dict."""
    return {
        "name": name,
        "description": description,
        "method": method,
        "input_schema": input_schema or {"type": "object", "properties": {}},
    }


def _make_manifest(actions: list[dict]) -> dict:
    return {"actions": actions}


def _make_toolpack_yaml(
    toolpack_id: str = "test-api",
    display_name: str = "Test API",
    allowed_hosts: list[str] | None = None,
    extra_paths: dict | None = None,
) -> dict:
    """Build a valid toolpack.yaml dict with all required fields."""
    paths = {
        "tools": "artifacts/tools.json",
        "toolsets": "artifacts/toolsets.yaml",
        "policy": "artifacts/policy.yaml",
        "baseline": "artifacts/baseline.yaml",
    }
    if extra_paths:
        paths.update(extra_paths)
    return {
        "schema_version": "1.0",
        "toolpack_id": toolpack_id,
        "display_name": display_name,
        "created_at": "2026-01-01T00:00:00Z",
        "capture_id": "test-capture-001",
        "artifact_id": "test-artifact-001",
        "scope": "full",
        "origin": {"start_url": "https://api.test.com"},
        "allowed_hosts": allowed_hosts or ["api.test.com"],
        "paths": paths,
    }


def _make_groups(groups: list[dict], ungrouped: list[str] | None = None) -> dict:
    return {
        "groups": groups,
        "ungrouped": ungrouped or [],
        "generated_from": "auto",
    }


# ---------------------------------------------------------------------------
# Unit tests: TransportEstimate dataclass
# ---------------------------------------------------------------------------


class TestTransportEstimate:
    def test_total(self):
        e = TransportEstimate(
            transport="MCP (stdio)",
            tokens_per_tool=500,
            context_overhead=21000,
        )
        assert e.total == 21500

    def test_total_zero(self):
        e = TransportEstimate(transport="CLI", tokens_per_tool=0, context_overhead=0)
        assert e.total == 0


# ---------------------------------------------------------------------------
# Unit tests: TokenEstimator core logic
# ---------------------------------------------------------------------------


class TestTokenEstimatorBasic:
    def test_from_empty_manifest(self):
        estimator = TokenEstimator.from_manifest({"actions": []})
        assert estimator.tool_count == 0
        assert estimator.categories == {}

    def test_from_single_tool(self):
        actions = [_make_action()]
        estimator = TokenEstimator.from_manifest(_make_manifest(actions))
        assert estimator.tool_count == 1

    def test_categories_counted(self):
        actions = [
            _make_action(name="get_users", method="GET"),
            _make_action(name="create_user", method="POST"),
            _make_action(name="update_user", method="PUT"),
            _make_action(name="delete_user", method="DELETE"),
            _make_action(name="list_items", method="GET"),
        ]
        estimator = TokenEstimator.from_manifest(_make_manifest(actions))
        assert estimator.categories["read"] == 2
        assert estimator.categories["write"] == 2
        assert estimator.categories["admin"] == 1

    def test_mcp_per_tool_tokens_from_schema(self):
        """Per-tool tokens based on name + description + schema char count / 4."""
        action = _make_action(
            name="get_users",
            description="List all users in the system",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                },
            },
        )
        estimator = TokenEstimator.from_manifest(_make_manifest([action]))
        # Should compute from actual content, not default to 500
        estimates = estimator.estimates()
        mcp_stdio = next(e for e in estimates if e.transport == "MCP (stdio)")
        # Per-tool should be computed from schema content
        assert mcp_stdio.tokens_per_tool > 0

    def test_many_tools(self):
        """1000+ tools should still work correctly."""
        actions = [
            _make_action(name=f"tool_{i}", method="GET" if i % 3 == 0 else "POST")
            for i in range(1000)
        ]
        estimator = TokenEstimator.from_manifest(_make_manifest(actions))
        assert estimator.tool_count == 1000
        estimates = estimator.estimates()
        assert len(estimates) >= 3  # MCP, CLI, REST at minimum


class TestTokenEstimatorEstimates:
    def test_estimates_returns_all_transports(self):
        actions = [_make_action()]
        estimator = TokenEstimator.from_manifest(_make_manifest(actions))
        estimates = estimator.estimates()
        transport_names = {e.transport for e in estimates}
        assert "MCP (stdio)" in transport_names
        assert "CLI" in transport_names
        assert "REST" in transport_names

    def test_mcp_context_overhead_scales_with_tools(self):
        small = TokenEstimator.from_manifest(
            _make_manifest([_make_action(name=f"t{i}") for i in range(5)])
        )
        big = TokenEstimator.from_manifest(
            _make_manifest([_make_action(name=f"t{i}") for i in range(50)])
        )
        small_mcp = next(e for e in small.estimates() if e.transport == "MCP (stdio)")
        big_mcp = next(e for e in big.estimates() if e.transport == "MCP (stdio)")
        assert big_mcp.context_overhead > small_mcp.context_overhead

    def test_cli_cheaper_than_mcp(self):
        """CLI is cheaper when tools have realistic schemas."""
        actions = [
            _make_action(
                name=f"get_resource_{i}_with_details",
                description=f"Retrieve resource {i} with all related metadata and nested objects",
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Resource identifier"},
                        "include": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer", "description": "Max results"},
                    },
                },
            )
            for i in range(10)
        ]
        estimator = TokenEstimator.from_manifest(_make_manifest(actions))
        estimates = estimator.estimates()
        mcp = next(e for e in estimates if e.transport == "MCP (stdio)")
        cli = next(e for e in estimates if e.transport == "CLI")
        assert cli.total < mcp.total

    def test_rest_cheaper_than_cli(self):
        actions = [_make_action(name=f"t{i}") for i in range(10)]
        estimator = TokenEstimator.from_manifest(_make_manifest(actions))
        estimates = estimator.estimates()
        cli = next(e for e in estimates if e.transport == "CLI")
        rest = next(e for e in estimates if e.transport == "REST")
        assert rest.total < cli.total


class TestTokenEstimatorScoped:
    def test_scoped_estimate_from_groups(self):
        actions = [_make_action(name=f"t{i}") for i in range(42)]
        groups = _make_groups(
            [
                {"name": "read", "tools": [f"t{i}" for i in range(12)], "path_prefix": "/read"},
                {
                    "name": "write",
                    "tools": [f"t{i}" for i in range(12, 37)],
                    "path_prefix": "/write",
                },
                {
                    "name": "admin",
                    "tools": [f"t{i}" for i in range(37, 42)],
                    "path_prefix": "/admin",
                },
            ]
        )
        estimator = TokenEstimator.from_manifest(_make_manifest(actions), groups_data=groups)
        estimates = estimator.estimates()
        transport_names = {e.transport for e in estimates}
        assert "MCP (scoped)" in transport_names

    def test_scoped_cheaper_than_full_mcp(self):
        actions = [_make_action(name=f"t{i}") for i in range(42)]
        groups = _make_groups(
            [
                {"name": "read", "tools": [f"t{i}" for i in range(12)], "path_prefix": "/read"},
                {
                    "name": "write",
                    "tools": [f"t{i}" for i in range(12, 37)],
                    "path_prefix": "/write",
                },
            ]
        )
        estimator = TokenEstimator.from_manifest(_make_manifest(actions), groups_data=groups)
        estimates = estimator.estimates()
        full = next(e for e in estimates if e.transport == "MCP (stdio)")
        scoped = next(e for e in estimates if e.transport == "MCP (scoped)")
        assert scoped.total < full.total

    def test_no_scoped_without_groups(self):
        actions = [_make_action()]
        estimator = TokenEstimator.from_manifest(_make_manifest(actions))
        estimates = estimator.estimates()
        transport_names = {e.transport for e in estimates}
        assert "MCP (scoped)" not in transport_names


class TestTokenEstimatorRecommendations:
    def test_recommendations_not_empty(self):
        actions = [_make_action(name=f"t{i}") for i in range(42)]
        groups = _make_groups(
            [
                {"name": "read", "tools": [f"t{i}" for i in range(12)], "path_prefix": "/read"},
                {
                    "name": "write",
                    "tools": [f"t{i}" for i in range(12, 37)],
                    "path_prefix": "/write",
                },
            ]
        )
        estimator = TokenEstimator.from_manifest(_make_manifest(actions), groups_data=groups)
        recs = estimator.recommendations()
        assert len(recs) > 0

    def test_scope_recommendation_when_groups_exist(self):
        actions = [_make_action(name=f"t{i}") for i in range(42)]
        groups = _make_groups(
            [
                {"name": "read", "tools": [f"t{i}" for i in range(12)], "path_prefix": "/read"},
            ]
        )
        estimator = TokenEstimator.from_manifest(_make_manifest(actions), groups_data=groups)
        recs = estimator.recommendations()
        scope_rec = [r for r in recs if "--scope" in r]
        assert len(scope_rec) > 0

    def test_cli_recommendation_always_present(self):
        actions = [
            _make_action(
                name=f"get_resource_{i}_details",
                description=f"Retrieve resource {i} with full metadata and nested relations",
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "include": {"type": "array", "items": {"type": "string"}},
                    },
                },
            )
            for i in range(10)
        ]
        estimator = TokenEstimator.from_manifest(_make_manifest(actions))
        recs = estimator.recommendations()
        cli_rec = [r for r in recs if "CLI" in r]
        assert len(cli_rec) > 0


class TestTokenEstimatorName:
    def test_name_from_manifest(self):
        manifest = {"name": "github-api", "actions": [_make_action()]}
        estimator = TokenEstimator.from_manifest(manifest)
        assert estimator.name == "github-api"

    def test_name_default(self):
        estimator = TokenEstimator.from_manifest({"actions": []})
        assert estimator.name == "toolpack"


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestEstimateTokensCLI:
    """Integration tests for the ``estimate-tokens`` CLI command."""

    def test_command_exists(self):
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["estimate-tokens", "--help"])
        assert result.exit_code == 0
        assert "estimate" in result.output.lower() or "token" in result.output.lower()

    def test_with_toolpack(self, tmp_path):
        """End-to-end: create a toolpack + tools.json, run estimate-tokens."""
        import yaml
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        manifest = _make_manifest(
            [
                _make_action(
                    name=f"get_resource_{i}", description=f"Get resource {i}", method="GET"
                )
                for i in range(5)
            ]
            + [
                _make_action(
                    name=f"create_resource_{i}", description=f"Create resource {i}", method="POST"
                )
                for i in range(3)
            ]
        )
        tools_path = tmp_path / "artifacts" / "tools.json"
        tools_path.parent.mkdir(parents=True)
        tools_path.write_text(json.dumps(manifest))

        tp = _make_toolpack_yaml()
        tp_path = tmp_path / "toolpack.yaml"
        tp_path.write_text(yaml.safe_dump(tp))

        runner = CliRunner()
        result = runner.invoke(cli, ["estimate-tokens", "--toolpack", str(tp_path)])
        assert result.exit_code == 0
        assert "Token Budget" in result.output
        assert "MCP (stdio)" in result.output
        assert "CLI" in result.output
        assert "REST" in result.output

    def test_with_groups(self, tmp_path):
        """Scoped row appears when groups.json exists."""
        import yaml
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        manifest = _make_manifest([_make_action(name=f"t{i}", method="GET") for i in range(20)])
        tools_path = tmp_path / "artifacts" / "tools.json"
        tools_path.parent.mkdir(parents=True)
        tools_path.write_text(json.dumps(manifest))

        groups = _make_groups(
            [
                {"name": "read", "tools": [f"t{i}" for i in range(10)], "path_prefix": "/read"},
                {
                    "name": "write",
                    "tools": [f"t{i}" for i in range(10, 20)],
                    "path_prefix": "/write",
                },
            ]
        )
        groups_path = tmp_path / "artifacts" / "groups.json"
        groups_path.write_text(json.dumps(groups))

        tp = _make_toolpack_yaml(extra_paths={"groups": "artifacts/groups.json"})
        tp_path = tmp_path / "toolpack.yaml"
        tp_path.write_text(yaml.safe_dump(tp))

        runner = CliRunner()
        result = runner.invoke(cli, ["estimate-tokens", "--toolpack", str(tp_path)])
        assert result.exit_code == 0
        assert "MCP (scoped)" in result.output

    def test_missing_toolpack_error(self, tmp_path):
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(
            cli, ["estimate-tokens", "--toolpack", str(tmp_path / "nonexistent.yaml")]
        )
        assert result.exit_code != 0

    def test_empty_toolpack(self, tmp_path):
        """Empty tools manifest (0 actions) still produces output."""
        import yaml
        from click.testing import CliRunner

        from toolwright.cli.main import cli

        manifest = _make_manifest([])
        tools_path = tmp_path / "artifacts" / "tools.json"
        tools_path.parent.mkdir(parents=True)
        tools_path.write_text(json.dumps(manifest))

        tp = _make_toolpack_yaml(
            toolpack_id="empty-api",
            display_name="Empty API",
            allowed_hosts=[],
        )
        tp_path = tmp_path / "toolpack.yaml"
        tp_path.write_text(yaml.safe_dump(tp))

        runner = CliRunner()
        result = runner.invoke(cli, ["estimate-tokens", "--toolpack", str(tp_path)])
        assert result.exit_code == 0
        assert "0" in result.output  # Should show 0 tools

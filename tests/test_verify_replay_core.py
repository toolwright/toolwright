"""Tests for toolwright.core.verify.replay :: run_replay()."""

from __future__ import annotations

import json
from pathlib import Path

from toolwright.core.verify.replay import run_replay
from toolwright.models.verify import VerifyStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _baseline(endpoints: list[dict]) -> dict:
    """Build a minimal baseline document."""
    return {"endpoints": endpoints}


def _manifest(actions: list[dict]) -> dict:
    """Build a minimal tools manifest document."""
    return {"actions": actions}


def _ep(method: str = "GET", host: str = "api.example.com", path: str = "/users",
        response_schema: dict | None = None) -> dict:
    """Build a baseline endpoint entry."""
    ep: dict = {"method": method, "host": host, "path": path}
    if response_schema is not None:
        ep["response_schema"] = response_schema
    return ep


def _action(method: str = "GET", host: str = "api.example.com", path: str = "/users",
            output_schema: dict | None = None) -> dict:
    """Build a tools manifest action entry."""
    act: dict = {"method": method, "host": host, "path": path}
    if output_schema is not None:
        act["output_schema"] = output_schema
    return act


# ---------------------------------------------------------------------------
# endpoint_present checks
# ---------------------------------------------------------------------------

def test_matching_endpoint_returns_pass(tmp_path: Path) -> None:
    """Baseline endpoint found in manifest produces PASS."""
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(_baseline([_ep()])))

    manifest = _manifest([_action()])

    result = run_replay(baseline_path=baseline_path, tools_manifest=manifest)

    assert result.status == VerifyStatus.PASS
    assert result.pass_count >= 1
    assert result.fail_count == 0
    assert any(
        c.check_type == "endpoint_present" and c.status == VerifyStatus.PASS
        for c in result.checks
    )


def test_endpoint_missing_from_manifest_returns_fail(tmp_path: Path) -> None:
    """Baseline endpoint NOT in manifest produces FAIL."""
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(_baseline([
        _ep(method="DELETE", path="/admin/users"),
    ])))

    manifest = _manifest([_action(method="GET", path="/users")])

    result = run_replay(baseline_path=baseline_path, tools_manifest=manifest)

    assert result.status == VerifyStatus.FAIL
    assert result.fail_count >= 1
    assert any(
        c.check_type == "endpoint_present"
        and c.status == VerifyStatus.FAIL
        and c.actual == "missing"
        for c in result.checks
    )


# ---------------------------------------------------------------------------
# schema compatibility checks
# ---------------------------------------------------------------------------

def test_schema_structurally_compatible_returns_pass(tmp_path: Path) -> None:
    """Schemas with same properties are structurally compatible -> PASS."""
    baseline_schema = {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
    }
    current_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "email": {"type": "string"},  # additive is OK
        },
    }

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(
        _baseline([_ep(response_schema=baseline_schema)])
    ))

    manifest = _manifest([_action(output_schema=current_schema)])

    result = run_replay(baseline_path=baseline_path, tools_manifest=manifest)

    schema_checks = [c for c in result.checks if c.check_type == "schema_match"]
    assert len(schema_checks) == 1
    assert schema_checks[0].status == VerifyStatus.PASS
    assert result.status == VerifyStatus.PASS


def test_schema_with_removed_properties_returns_fail(tmp_path: Path) -> None:
    """Schema that lost properties compared to baseline -> FAIL."""
    baseline_schema = {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
    }
    # Current schema is missing 'name'
    current_schema = {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
    }

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(
        _baseline([_ep(response_schema=baseline_schema)])
    ))

    manifest = _manifest([_action(output_schema=current_schema)])

    result = run_replay(baseline_path=baseline_path, tools_manifest=manifest)

    schema_checks = [c for c in result.checks if c.check_type == "schema_match"]
    assert len(schema_checks) == 1
    assert schema_checks[0].status == VerifyStatus.FAIL
    assert result.status == VerifyStatus.FAIL


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

def test_missing_baseline_file_returns_unknown(tmp_path: Path) -> None:
    """Non-existent baseline file -> UNKNOWN."""
    baseline_path = tmp_path / "does_not_exist.json"

    result = run_replay(baseline_path=baseline_path, tools_manifest=_manifest([]))

    assert result.status == VerifyStatus.UNKNOWN
    assert result.unknown_count == 1


def test_invalid_json_baseline_returns_fail(tmp_path: Path) -> None:
    """Baseline file with invalid JSON -> FAIL."""
    baseline_path = tmp_path / "bad.json"
    baseline_path.write_text("{not valid json!!!")

    result = run_replay(baseline_path=baseline_path, tools_manifest=_manifest([]))

    assert result.status == VerifyStatus.FAIL
    assert result.fail_count == 1


def test_empty_endpoints_list_returns_unknown(tmp_path: Path) -> None:
    """Baseline with empty endpoints list -> UNKNOWN (no checks executed)."""
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(_baseline([])))

    manifest = _manifest([_action()])

    result = run_replay(baseline_path=baseline_path, tools_manifest=manifest)

    assert result.status == VerifyStatus.UNKNOWN
    assert result.pass_count == 0
    assert result.fail_count == 0
    assert len(result.checks) == 0


# ---------------------------------------------------------------------------
# additional coverage
# ---------------------------------------------------------------------------

def test_baseline_path_recorded_in_result(tmp_path: Path) -> None:
    """Result includes the baseline path string."""
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(_baseline([])))

    result = run_replay(baseline_path=baseline_path, tools_manifest=_manifest([]))

    assert result.baseline_path == str(baseline_path)


def test_baseline_not_a_dict_returns_fail(tmp_path: Path) -> None:
    """Baseline that parses as a list instead of dict -> FAIL."""
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps([1, 2, 3]))

    result = run_replay(baseline_path=baseline_path, tools_manifest=_manifest([]))

    assert result.status == VerifyStatus.FAIL
    assert result.fail_count == 1


def test_multiple_endpoints_mixed_results(tmp_path: Path) -> None:
    """Mix of present and missing endpoints -> overall FAIL."""
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(_baseline([
        _ep(method="GET", path="/users"),
        _ep(method="POST", path="/orders"),
    ])))

    # Only /users is in the manifest, /orders is missing
    manifest = _manifest([_action(method="GET", path="/users")])

    result = run_replay(baseline_path=baseline_path, tools_manifest=manifest)

    assert result.status == VerifyStatus.FAIL
    assert result.pass_count >= 1
    assert result.fail_count >= 1


def test_schema_check_only_when_both_have_schemas(tmp_path: Path) -> None:
    """Schema check is only emitted when both baseline and current have schemas."""
    baseline_path = tmp_path / "baseline.json"
    # Baseline has no response_schema
    baseline_path.write_text(json.dumps(_baseline([_ep()])))

    manifest = _manifest([_action(output_schema={"type": "object", "properties": {"x": {}}})])

    result = run_replay(baseline_path=baseline_path, tools_manifest=manifest)

    schema_checks = [c for c in result.checks if c.check_type == "schema_match"]
    assert len(schema_checks) == 0
    assert result.status == VerifyStatus.PASS

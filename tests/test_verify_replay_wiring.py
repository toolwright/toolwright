"""Tests for verify replay CLI wiring to core run_replay().

P1-2: The CLI _replay_result() must call core run_replay() and return
real endpoint checks, not just check if the baseline file exists.
"""

from __future__ import annotations

import json
from pathlib import Path

from toolwright.cli.verify import _replay_result


def _write_baseline(path: Path, endpoints: list[dict]) -> None:
    """Write a baseline.json with given endpoints."""
    path.write_text(json.dumps({"schema_version": "1.0", "endpoints": endpoints}))


def _write_tools(path: Path, actions: list[dict]) -> None:
    """Write a tools.json with given actions."""
    path.write_text(json.dumps({
        "version": "1.0.0",
        "schema_version": "1.0",
        "actions": actions,
    }))


def test_replay_returns_endpoint_checks_when_present(tmp_path: Path) -> None:
    """Replay should return pass_count/fail_count when baseline has endpoints."""
    baseline = tmp_path / "baseline.json"
    tools = tmp_path / "tools.json"

    _write_baseline(baseline, [
        {"method": "GET", "host": "api.example.com", "path": "/users"},
    ])
    _write_tools(tools, [
        {"method": "GET", "host": "api.example.com", "path": "/users",
         "tool_id": "get_users", "name": "get_users"},
    ])

    result = _replay_result(baseline, tools)
    assert result["status"] == "pass"
    assert "pass_count" in result["checks"]
    assert result["checks"]["pass_count"] >= 1


def test_replay_detects_missing_endpoint(tmp_path: Path) -> None:
    """Replay should report fail when a baseline endpoint is missing from tools."""
    baseline = tmp_path / "baseline.json"
    tools = tmp_path / "tools.json"

    _write_baseline(baseline, [
        {"method": "GET", "host": "api.example.com", "path": "/users"},
        {"method": "DELETE", "host": "api.example.com", "path": "/users/{id}"},
    ])
    # Only the GET endpoint exists in tools — DELETE is missing
    _write_tools(tools, [
        {"method": "GET", "host": "api.example.com", "path": "/users",
         "tool_id": "get_users", "name": "get_users"},
    ])

    result = _replay_result(baseline, tools)
    assert result["status"] == "fail"
    assert result["checks"]["fail_count"] >= 1


def test_replay_missing_baseline_returns_unknown(tmp_path: Path) -> None:
    """Replay should return unknown when baseline file doesn't exist."""
    baseline = tmp_path / "nonexistent.json"
    tools = tmp_path / "tools.json"
    _write_tools(tools, [])

    result = _replay_result(baseline, tools)
    assert result["status"] == "unknown"


def test_replay_missing_tools_returns_unknown(tmp_path: Path) -> None:
    """Replay should return unknown when tools file doesn't exist."""
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, [])
    tools = tmp_path / "nonexistent.json"

    result = _replay_result(baseline, tools)
    assert result["status"] == "unknown"

"""Tests for the verify engine orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

from toolwright.core.verify.engine import VerifyEngine
from toolwright.models.verify import VerifyStatus


def _make_manifest(actions: list[dict] | None = None) -> dict:
    return {
        "version": "1.0.0",
        "schema_version": "1.0",
        "name": "Test Tools",
        "actions": actions or [
            {
                "tool_id": "get_users",
                "name": "get_users",
                "method": "GET",
                "path": "/users",
                "host": "api.example.com",
            }
        ],
    }


def _write_contract_file(path: Path, contracts: list[dict] | None = None) -> None:
    payload = {
        "version": "1.0.0",
        "schema_version": "1.0",
        "contracts": contracts or [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_baseline(path: Path, endpoints: list[dict] | None = None) -> None:
    payload = {
        "schema_version": "1.0",
        "endpoints": endpoints or [
            {"method": "GET", "host": "api.example.com", "path": "/users"},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


# --- Engine instantiation ---

def test_engine_creates_with_toolpack_id() -> None:
    engine = VerifyEngine(toolpack_id="tp_test")
    assert engine.toolpack_id == "tp_test"


# --- Mode expansion ---

def test_engine_mode_all_runs_all_modes(tmp_path: Path) -> None:
    contract_path = tmp_path / "contracts.yaml"
    _write_contract_file(contract_path)
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path)

    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="all",
        tools_manifest=_make_manifest(),
        contract_path=contract_path,
        baseline_path=baseline_path,
    )
    assert report.contracts is not None
    assert report.replay is not None
    assert report.outcomes is not None
    assert report.provenance is not None


def test_engine_single_mode_only_runs_selected(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path)

    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="replay",
        tools_manifest=_make_manifest(),
        baseline_path=baseline_path,
    )
    assert report.replay is not None
    assert report.contracts is None
    assert report.outcomes is None
    assert report.provenance is None


# --- Contracts mode ---

def test_contracts_pass_with_valid_file(tmp_path: Path) -> None:
    contract_path = tmp_path / "contracts.yaml"
    _write_contract_file(contract_path, contracts=[])

    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="contracts",
        tools_manifest=_make_manifest(),
        contract_path=contract_path,
    )
    assert report.contracts is not None
    assert report.contracts.status == VerifyStatus.PASS


def test_contracts_unknown_when_no_file() -> None:
    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="contracts",
        tools_manifest=_make_manifest(),
        contract_path=None,
    )
    assert report.contracts is not None
    assert report.contracts.status == VerifyStatus.UNKNOWN


def test_contracts_fail_strict_when_no_file() -> None:
    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="contracts",
        tools_manifest=_make_manifest(),
        contract_path=None,
        strict=True,
    )
    assert report.contracts is not None
    assert report.contracts.status == VerifyStatus.FAIL


# --- Replay mode ---

def test_replay_pass_when_all_endpoints_present(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path)

    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="replay",
        tools_manifest=_make_manifest(),
        baseline_path=baseline_path,
    )
    assert report.replay is not None
    assert report.replay.status == VerifyStatus.PASS


def test_replay_fail_when_endpoint_missing(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path, endpoints=[
        {"method": "GET", "host": "api.example.com", "path": "/users"},
        {"method": "POST", "host": "api.example.com", "path": "/users"},
    ])

    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="replay",
        tools_manifest=_make_manifest(),  # only has GET /users
        baseline_path=baseline_path,
    )
    assert report.replay is not None
    assert report.replay.status == VerifyStatus.FAIL
    assert report.replay.fail_count >= 1


def test_replay_unknown_when_no_baseline(tmp_path: Path) -> None:
    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="replay",
        tools_manifest=_make_manifest(),
        baseline_path=tmp_path / "nonexistent.json",
    )
    assert report.replay is not None
    assert report.replay.status == VerifyStatus.UNKNOWN


# --- Outcomes mode ---

def test_outcomes_pass_with_matching_assertions(tmp_path: Path) -> None:
    contract_path = tmp_path / "contracts.json"
    _write_contract_file(contract_path, contracts=[
        {
            "contract_id": "vc_test",
            "targets": ["get_users"],
            "assertions": [
                {
                    "type": "field_match",
                    "field_path": "endpoints.0.method",
                    "op": "equals",
                    "value": "GET",
                }
            ],
        }
    ])
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path)

    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="outcomes",
        tools_manifest=_make_manifest(),
        contract_path=contract_path,
        baseline_path=baseline_path,
    )
    assert report.outcomes is not None
    assert report.outcomes.status == VerifyStatus.PASS


def test_outcomes_fail_with_wrong_value(tmp_path: Path) -> None:
    contract_path = tmp_path / "contracts.json"
    _write_contract_file(contract_path, contracts=[
        {
            "contract_id": "vc_test",
            "targets": ["get_users"],
            "assertions": [
                {
                    "type": "field_match",
                    "field_path": "endpoints.0.method",
                    "op": "equals",
                    "value": "POST",  # wrong
                }
            ],
        }
    ])
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path)

    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="outcomes",
        tools_manifest=_make_manifest(),
        contract_path=contract_path,
        baseline_path=baseline_path,
    )
    assert report.outcomes is not None
    assert report.outcomes.status == VerifyStatus.FAIL


def test_outcomes_unknown_when_no_contracts() -> None:
    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="outcomes",
        tools_manifest=_make_manifest(),
    )
    assert report.outcomes is not None
    assert report.outcomes.status == VerifyStatus.UNKNOWN


# --- Provenance mode ---

def test_provenance_runs_with_assertions() -> None:
    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="provenance",
        tools_manifest=_make_manifest(),
        assertions=[
            {
                "name": "check_users",
                "locator": {"by": "role", "value": "list"},
                "expect": {"type": "contains_text", "value": "user"},
            }
        ],
    )
    assert report.provenance is not None
    assert report.provenance["status"] in {"pass", "unknown", "fail"}


def test_provenance_no_assertions_returns_pass() -> None:
    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="provenance",
        tools_manifest=_make_manifest(),
        assertions=[],
    )
    assert report.provenance is not None
    assert report.provenance["status"] == "pass"


# --- Exit code evaluation ---

def test_exit_code_0_when_all_pass(tmp_path: Path) -> None:
    contract_path = tmp_path / "contracts.yaml"
    _write_contract_file(contract_path)
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path)

    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="all",
        tools_manifest=_make_manifest(),
        contract_path=contract_path,
        baseline_path=baseline_path,
    )
    assert report.exit_code == 0
    assert report.overall_status == VerifyStatus.PASS


def test_exit_code_2_when_fail(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path, endpoints=[
        {"method": "DELETE", "host": "api.example.com", "path": "/admin"},
    ])

    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="replay",
        tools_manifest=_make_manifest(),
        baseline_path=baseline_path,
    )
    assert report.exit_code == 2
    assert report.overall_status == VerifyStatus.FAIL


def test_exit_code_1_strict_unknown() -> None:
    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="contracts",
        tools_manifest=_make_manifest(),
        contract_path=None,
        strict=True,
    )
    # strict + no contract = fail, exit 2
    assert report.exit_code == 2


# --- Evidence bundle ---

def test_evidence_bundle_created(tmp_path: Path) -> None:
    contract_path = tmp_path / "contracts.yaml"
    _write_contract_file(contract_path)
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(baseline_path)
    evidence_dir = tmp_path / "evidence"

    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="all",
        tools_manifest=_make_manifest(),
        contract_path=contract_path,
        baseline_path=baseline_path,
        evidence_dir=evidence_dir,
    )
    assert report.evidence_bundle_id is not None
    assert evidence_dir.exists()
    bundle_files = list(evidence_dir.glob("*.jsonl"))
    assert len(bundle_files) == 1


# --- Report structure ---

def test_report_includes_tool_ids() -> None:
    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="contracts",
        tools_manifest=_make_manifest(),
    )
    assert "get_users" in report.tool_ids


def test_report_config_populated() -> None:
    engine = VerifyEngine(toolpack_id="tp_test")
    report = engine.run(
        mode="contracts",
        tools_manifest=_make_manifest(),
        strict=True,
        top_k=5,
        min_confidence=0.7,
        unknown_budget=0.2,
    )
    assert report.config["strict"] is True
    assert report.config["top_k"] == 5
    assert report.config["min_confidence"] == 0.7
    assert report.config["unknown_budget"] == 0.2

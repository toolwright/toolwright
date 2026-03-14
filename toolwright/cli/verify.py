"""Verification command implementation.

This is a thin CLI wrapper. Core logic lives in toolwright.core.verify.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import yaml

from toolwright.core.toolpack import load_toolpack, resolve_toolpack_paths
from toolwright.utils.schema_version import resolve_generated_at

VERIFY_MODES = {"contracts", "replay", "baseline-check", "outcomes", "provenance", "all"}
SOURCE_KINDS = {"http_response", "cache_or_sw", "websocket_or_sse", "local_state"}
SUPPORTED_PLAYBOOK_STEPS = {"goto", "click", "fill", "wait", "select", "submit", "scroll", "extract"}
SUPPORTED_LOCATORS = ("role", "label", "text", "css", "xpath")
SUPPORTED_EXPECT_TYPES = {"contains_text", "equals", "regex", "json_shape"}


@dataclass(frozen=True)
class VerifySummary:
    """Final verification summary."""

    exit_code: int
    report_path: Path
    overall_status: str


def run_verify(
    *,
    toolpack_path: str,
    mode: str,
    lockfile_path: str | None,
    playbook_path: str | None,
    ui_assertions_path: str | None,
    output_dir: str,
    strict: bool,
    top_k: int,
    min_confidence: float,
    unknown_budget: float,
    verbose: bool,
) -> None:
    """Run verification and emit a deterministic report artifact."""
    if mode not in VERIFY_MODES:
        click.echo(f"Error: unsupported verify mode '{mode}'", err=True)
        sys.exit(3)
    if mode == "replay":
        click.echo(
            "Warning: --mode replay is deprecated. Use --mode baseline-check instead.",
            err=True,
        )
    if top_k <= 0:
        click.echo("Error: --top-k must be greater than zero", err=True)
        sys.exit(3)
    if min_confidence < 0.0 or min_confidence > 1.0:
        click.echo("Error: --min-confidence must be between 0 and 1", err=True)
        sys.exit(3)
    if unknown_budget < 0.0 or unknown_budget > 1.0:
        click.echo("Error: --unknown-budget must be between 0 and 1", err=True)
        sys.exit(3)

    try:
        toolpack = load_toolpack(Path(toolpack_path))
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(3)

    resolved = resolve_toolpack_paths(toolpack=toolpack, toolpack_path=toolpack_path)
    if lockfile_path:
        selected_lockfile = Path(lockfile_path)
    elif resolved.approved_lockfile_path and resolved.approved_lockfile_path.exists():
        selected_lockfile = resolved.approved_lockfile_path
    elif resolved.pending_lockfile_path and resolved.pending_lockfile_path.exists():
        selected_lockfile = resolved.pending_lockfile_path
    else:
        selected_lockfile = None

    governance_mode = (
        "pre-approval"
        if selected_lockfile and ".pending." in selected_lockfile.name
        else "approved"
    )

    try:
        report = _build_report(
            toolpack_id=toolpack.toolpack_id,
            mode=mode,
            tools_path=resolved.tools_path,
            contract_path=resolved.contracts_path or resolved.contract_yaml_path,
            baseline_path=resolved.baseline_path,
            playbook_path=Path(playbook_path) if playbook_path else None,
            ui_assertions_path=Path(ui_assertions_path) if ui_assertions_path else None,
            top_k=top_k,
            min_confidence=min_confidence,
            governance_mode=governance_mode,
            strict=strict,
            unknown_budget=unknown_budget,
        )
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(3)

    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / f"verify_{toolpack.toolpack_id}.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    summary = _evaluate_report(report, strict=strict, unknown_budget=unknown_budget)
    summary = VerifySummary(
        exit_code=summary.exit_code,
        report_path=report_path,
        overall_status=summary.overall_status,
    )

    click.echo(f"Verification complete: {toolpack.toolpack_id}")
    click.echo(f"  Mode: {mode}")
    click.echo(f"  Governance mode: {governance_mode}")
    click.echo(f"  Status: {summary.overall_status}")
    click.echo(f"  Report: {summary.report_path}")
    click.echo(f"  Exit code: {summary.exit_code}")
    if verbose and selected_lockfile is not None:
        click.echo(f"  Lockfile: {selected_lockfile}")

    sys.exit(summary.exit_code)


def _build_report(
    *,
    toolpack_id: str,
    mode: str,
    tools_path: Path,
    contract_path: Path | None,
    baseline_path: Path,
    playbook_path: Path | None,
    ui_assertions_path: Path | None,
    top_k: int,
    min_confidence: float,
    governance_mode: str,
    strict: bool,
    unknown_budget: float,
) -> dict[str, Any]:
    with open(tools_path, encoding="utf-8") as f:
        manifest = json.load(f)
    actions = manifest.get("actions", [])
    tool_ids = [
        str(action.get("tool_id") or action.get("signature_id") or action.get("name"))
        for action in actions
    ]

    active_modes = _expand_modes(mode, has_playbook=playbook_path is not None)
    contract_result = _contracts_result(contract_path, strict=strict) if "contracts" in active_modes else None
    replay_result = _replay_result(baseline_path, tools_path) if "replay" in active_modes else None
    outcome_result = _outcomes_result() if "outcomes" in active_modes else None
    provenance_result = (
        _provenance_result(
            actions=actions,
            playbook_path=playbook_path,
            ui_assertions_path=ui_assertions_path,
            top_k=top_k,
            min_confidence=min_confidence,
        )
        if "provenance" in active_modes
        else {"status": "skipped", "results": []}
    )

    return {
        "schema_version": "1.0",
        "generated_at": resolve_generated_at(deterministic=False).isoformat(),
        "toolpack_id": toolpack_id,
        "mode": mode,
        "governance_mode": governance_mode,
        "config": {
            "strict": strict,
            "top_k": top_k,
            "min_confidence": min_confidence,
            "unknown_budget": unknown_budget,
        },
        "contracts": contract_result,
        "replay": replay_result,
        "outcomes": outcome_result,
        "provenance": provenance_result,
        "evidence_index": {
            "trace_refs": [],
            "response_slices": [],
            "screenshots": [],
            "dom_snapshots": [],
        },
        "tool_ids": tool_ids,
    }


def _expand_modes(mode: str, *, has_playbook: bool = True) -> set[str]:
    if mode == "all":
        modes = {"contracts", "replay", "outcomes", "provenance"}
        if not has_playbook:
            modes.discard("provenance")
        return modes
    if mode == "baseline-check":
        return {"replay"}
    return {mode}


def _contracts_result(contract_path: Path | None, strict: bool) -> dict[str, Any]:
    exists = bool(contract_path and contract_path.exists())
    if not exists:
        return {
            "status": "fail" if strict else "unknown",
            "contract_path": str(contract_path) if contract_path else None,
            "checks": {
                "schema_present": False,
                "invariants_valid": False,
                "unknown_schema_count": 1,
                "version": None,
                "schema_version": None,
            },
        }

    payload: dict[str, Any] | None = None
    assert contract_path is not None
    raw = contract_path.read_text(encoding="utf-8")
    if contract_path.suffix in {".yaml", ".yml"}:
        loaded = yaml.safe_load(raw) or {}
        if isinstance(loaded, dict):
            payload = loaded
    else:
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            payload = loaded

    has_schema = bool(payload and payload.get("schema_version"))
    has_version = bool(payload and payload.get("version"))
    status = "pass" if (has_schema and has_version) else ("fail" if strict else "unknown")
    return {
        "status": status,
        "contract_path": str(contract_path) if contract_path else None,
        "checks": {
            "schema_present": has_schema,
            "invariants_valid": bool(payload and ("contracts" in payload or "paths" in payload)),
            "unknown_schema_count": 0 if has_schema else 1,
            "version": payload.get("version") if payload else None,
            "schema_version": payload.get("schema_version") if payload else None,
        },
    }


def _replay_result(baseline_path: Path, tools_path: Path) -> dict[str, Any]:
    if not tools_path.exists():
        return {
            "status": "unknown",
            "baseline_path": str(baseline_path),
            "checks": {"baseline_present": baseline_path.exists()},
        }

    from toolwright.core.verify.replay import run_replay

    tools_manifest = json.loads(tools_path.read_text(encoding="utf-8"))
    result = run_replay(baseline_path=baseline_path, tools_manifest=tools_manifest)
    return {
        "status": result.status.value,
        "baseline_path": str(baseline_path),
        "checks": {
            "baseline_present": baseline_path.exists(),
            "pass_count": result.pass_count,
            "fail_count": result.fail_count,
            "unknown_count": result.unknown_count,
            "details": [
                {
                    "endpoint_ref": c.endpoint_ref,
                    "check_type": c.check_type,
                    "status": c.status.value,
                    "message": c.message,
                }
                for c in result.checks
            ],
        },
    }


def _outcomes_result() -> dict[str, Any]:
    return {
        "status": "skipped",
        "checks": {"semantic_assertions": "not_configured"},
    }


def _load_playbook(path: Path) -> tuple[str, dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"Playbook file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    payload_raw = (
        yaml.safe_load(raw) or {}
        if path.suffix in {".yaml", ".yml"}
        else json.loads(raw)
    )
    if not isinstance(payload_raw, dict):
        raise ValueError("playbook payload must be a mapping")
    version = str(payload_raw.get("version", "")).strip()
    if not version:
        raise ValueError("playbook must include a version")
    steps = payload_raw.get("steps", [])
    if not isinstance(steps, list):
        raise ValueError("playbook steps must be a list")
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"playbook step at index {idx} must be a mapping")
        step_type = str(step.get("type", "")).strip().lower()
        if step_type not in SUPPORTED_PLAYBOOK_STEPS:
            raise ValueError(f"unsupported playbook step type '{step_type}' at index {idx}")
    return version, payload_raw


def _load_ui_assertions(path: Path) -> tuple[str, list[dict[str, Any]]]:
    if not path.exists():
        raise ValueError(f"UI assertions file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    payload_raw = (
        yaml.safe_load(raw) or []
        if path.suffix in {".yaml", ".yml"}
        else json.loads(raw)
    )
    version = "1.0"
    if isinstance(payload_raw, dict):
        version = str(payload_raw.get("version", "1.0")).strip() or "1.0"
        payload = payload_raw.get("ui_assertions", [])
    else:
        payload = payload_raw
    if not isinstance(payload, list):
        raise ValueError("UI assertions payload must be a list")
    assertions: list[dict[str, Any]] = []
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        locator = item.get("locator")
        expect = item.get("expect")
        if not isinstance(locator, dict):
            raise ValueError(f"ui assertion at index {idx} missing locator mapping")
        locator_type = str(locator.get("by", "")).strip().lower()
        if locator_type not in SUPPORTED_LOCATORS:
            raise ValueError(
                f"ui assertion at index {idx} has unsupported locator type '{locator_type}'"
            )
        if not isinstance(expect, dict):
            raise ValueError(f"ui assertion at index {idx} missing expect mapping")
        expect_type = str(expect.get("type", "")).strip().lower()
        if expect_type not in SUPPORTED_EXPECT_TYPES:
            raise ValueError(
                f"ui assertion at index {idx} has unsupported expect type '{expect_type}'"
            )
        assertions.append(item)
    return version, assertions


def _score_candidate(
    *,
    action: dict[str, Any],
    assertion: dict[str, Any],
    order_index: int,
) -> dict[str, Any]:
    assertion_name = str(assertion.get("name", "unnamed_assertion"))
    expect = assertion.get("expect", {})
    expected_value = str(expect.get("value", "")).strip().lower()

    method = str(action.get("method", "GET")).upper()
    host = str(action.get("host", ""))
    path = str(action.get("path", "/"))
    tool_id = str(action.get("tool_id") or action.get("signature_id") or action.get("name"))
    searchable = " ".join(
        [
            tool_id,
            str(action.get("name", "")),
            host,
            path,
        ]
    ).lower()

    content_match = 1.0 if expected_value and expected_value in searchable else 0.35
    path_lower = path.lower()
    if "search" in path_lower:
        shape_match = 0.9
    elif any(token in path_lower for token in ("facet", "filter")):
        shape_match = 0.85
    elif any(token in path_lower for token in ("product", "detail", "item")):
        shape_match = 0.8
    else:
        shape_match = 0.5

    timing = max(0.2, round(1.0 - (order_index * 0.12), 3))
    repetition = 0.7 if method == "GET" else 0.5
    score = round((timing * 0.3) + (content_match * 0.35) + (shape_match * 0.25) + (repetition * 0.1), 3)
    source_kind = "http_response" if score >= 0.55 else "local_state"

    return {
        "tool_id": tool_id,
        "request_fingerprint": "|".join([method, host, path]),
        "score": score,
        "source_kind": source_kind,
        "signals": {
            "timing": round(timing, 3),
            "content_match": round(content_match, 3),
            "shape_match": round(shape_match, 3),
            "repetition": round(repetition, 3),
        },
        "evidence_refs": [
            f"evidence://trace/{assertion_name}",
            f"evidence://dom/{assertion_name}",
            f"evidence://response/{tool_id}",
        ],
    }


def _provenance_result(
    *,
    actions: list[dict[str, Any]],
    playbook_path: Path | None,
    ui_assertions_path: Path | None,
    top_k: int,
    min_confidence: float,
) -> dict[str, Any]:
    if playbook_path is None or not playbook_path.exists():
        raise ValueError("--playbook is required for provenance mode")
    if ui_assertions_path is None:
        raise ValueError("--ui-assertions is required for provenance mode")

    playbook_version, _playbook = _load_playbook(playbook_path)
    assertions_version, assertions = _load_ui_assertions(ui_assertions_path)
    results: list[dict[str, Any]] = []
    action_candidates = actions if actions else []
    for assertion in assertions:
        assertion_name = str(assertion.get("name", "unnamed_assertion"))
        candidates = sorted(
            [
                _score_candidate(action=action, assertion=assertion, order_index=idx)
                for idx, action in enumerate(action_candidates)
            ],
            key=lambda candidate: candidate["score"],
            reverse=True,
        )[:top_k]
        chosen = candidates[0] if candidates else None
        status = "unknown"
        if chosen and chosen["score"] >= min_confidence:
            strong_signals = [
                value
                for value in chosen["signals"].values()
                if isinstance(value, float) and value >= min_confidence
            ]
            if len(strong_signals) >= 2 and chosen["source_kind"] == "http_response":
                status = "pass"
            else:
                status = "unknown"
        elif not candidates:
            status = "fail"
        results.append(
            {
                "assertion_name": assertion_name,
                "status": status,
                "top_candidates": candidates,
                "chosen_candidate": chosen,
                "notes": [] if status == "pass" else ["insufficient confidence for deterministic mapping"],
            }
        )

    overall = "pass"
    if any(item["status"] == "fail" for item in results):
        overall = "fail"
    elif any(item["status"] == "unknown" for item in results):
        overall = "unknown"

    return {
        "status": overall,
        "playbook_path": str(playbook_path),
        "ui_assertions_path": str(ui_assertions_path),
        "playbook_version": playbook_version,
        "assertions_version": assertions_version,
        "results": results,
        "source_kinds": sorted(SOURCE_KINDS),
    }


def _evaluate_report(report: dict[str, Any], *, strict: bool, unknown_budget: float) -> VerifySummary:
    report_path = Path("unknown")
    statuses = []
    for key in ("contracts", "replay", "outcomes", "provenance"):
        section = report.get(key)
        if isinstance(section, dict):
            status = section.get("status")
            if isinstance(status, str) and status != "skipped":
                statuses.append(status)

    if "fail" in statuses:
        return VerifySummary(exit_code=2, report_path=report_path, overall_status="fail")

    provenance = report.get("provenance", {})
    unknown_ratio = 0.0
    if isinstance(provenance, dict):
        results = provenance.get("results", [])
        if isinstance(results, list) and results:
            unknown_count = sum(1 for item in results if isinstance(item, dict) and item.get("status") == "unknown")
            unknown_ratio = unknown_count / len(results)

    if unknown_ratio > unknown_budget:
        return VerifySummary(exit_code=1, report_path=report_path, overall_status="gated")

    if strict and "unknown" in statuses:
        return VerifySummary(exit_code=1, report_path=report_path, overall_status="gated")

    return VerifySummary(exit_code=0, report_path=report_path, overall_status="pass")

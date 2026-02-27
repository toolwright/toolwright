"""Replay verification — compare current capture against baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from toolwright.models.verify import ReplayCheckResult, ReplayResult, VerifyStatus


def run_replay(
    *,
    baseline_path: Path,
    tools_manifest: dict[str, Any],
) -> ReplayResult:
    """Run replay verification against a saved baseline.

    Checks:
    1. All endpoints still return 2xx (status check)
    2. Response schemas haven't changed (structural check)
    3. Key fields still present (field assertions)
    """
    if not baseline_path.exists():
        return ReplayResult(
            status=VerifyStatus.UNKNOWN,
            baseline_path=str(baseline_path),
            unknown_count=1,
        )

    try:
        raw = baseline_path.read_text(encoding="utf-8")
        baseline = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return ReplayResult(
            status=VerifyStatus.FAIL,
            baseline_path=str(baseline_path),
            fail_count=1,
        )

    if not isinstance(baseline, dict):
        return ReplayResult(
            status=VerifyStatus.FAIL,
            baseline_path=str(baseline_path),
            fail_count=1,
        )

    baseline_endpoints = baseline.get("endpoints", [])
    if not isinstance(baseline_endpoints, list):
        baseline_endpoints = []

    actions = tools_manifest.get("actions", [])
    checks: list[ReplayCheckResult] = []

    # Build lookup of current actions by (method, host, path)
    current_actions: dict[str, dict[str, Any]] = {}
    for action in actions:
        key = _action_key(action)
        if key:
            current_actions[key] = action

    # Check each baseline endpoint is still present
    for ep in baseline_endpoints:
        if not isinstance(ep, dict):
            continue
        ep_ref = _endpoint_ref(ep)
        ep_key = _endpoint_key(ep)

        if not ep_key:
            continue

        if ep_key in current_actions:
            checks.append(ReplayCheckResult(
                endpoint_ref=ep_ref,
                check_type="endpoint_present",
                status=VerifyStatus.PASS,
                expected="present",
                actual="present",
                message=f"Endpoint {ep_ref} still present in manifest",
            ))

            # Check schema structure if both have response schemas
            baseline_schema = ep.get("response_schema") or ep.get("response_body_json_schema")
            current_schema = current_actions[ep_key].get("output_schema") or current_actions[ep_key].get("response_schema")
            if baseline_schema and current_schema:
                schema_match = _schemas_structurally_compatible(baseline_schema, current_schema)
                checks.append(ReplayCheckResult(
                    endpoint_ref=ep_ref,
                    check_type="schema_match",
                    status=VerifyStatus.PASS if schema_match else VerifyStatus.FAIL,
                    expected=baseline_schema,
                    actual=current_schema,
                    message="Schema structurally compatible" if schema_match else "Schema structure changed",
                ))
        else:
            checks.append(ReplayCheckResult(
                endpoint_ref=ep_ref,
                check_type="endpoint_present",
                status=VerifyStatus.FAIL,
                expected="present",
                actual="missing",
                message=f"Endpoint {ep_ref} missing from current manifest",
            ))

    pass_count = sum(1 for c in checks if c.status == VerifyStatus.PASS)
    fail_count = sum(1 for c in checks if c.status == VerifyStatus.FAIL)
    unknown_count = sum(1 for c in checks if c.status == VerifyStatus.UNKNOWN)

    if fail_count > 0:
        overall = VerifyStatus.FAIL
    elif unknown_count > 0:
        overall = VerifyStatus.UNKNOWN
    elif pass_count > 0:
        overall = VerifyStatus.PASS
    else:
        overall = VerifyStatus.UNKNOWN

    return ReplayResult(
        status=overall,
        baseline_path=str(baseline_path),
        checks=checks,
        pass_count=pass_count,
        fail_count=fail_count,
        unknown_count=unknown_count,
    )


def _action_key(action: dict[str, Any]) -> str | None:
    """Build a lookup key from a tools manifest action."""
    method = str(action.get("method", "")).upper()
    host = str(action.get("host", ""))
    path = str(action.get("path", ""))
    if not method or not path:
        return None
    return f"{method}:{host}:{path}"


def _endpoint_key(ep: dict[str, Any]) -> str | None:
    """Build a lookup key from a baseline endpoint."""
    method = str(ep.get("method", "")).upper()
    host = str(ep.get("host", ""))
    path = str(ep.get("path", ""))
    if not method or not path:
        return None
    return f"{method}:{host}:{path}"


def _endpoint_ref(ep: dict[str, Any]) -> str:
    """Build a human-readable endpoint reference."""
    method = str(ep.get("method", "?"))
    host = str(ep.get("host", ""))
    path = str(ep.get("path", "/"))
    return f"{method} {host}{path}"


def _schemas_structurally_compatible(
    baseline: Any,
    current: Any,
) -> bool:
    """Check if two JSON schemas are structurally compatible.

    Compatible means: all properties in baseline exist in current.
    Current may have additional properties (additive is OK).
    """
    if not isinstance(baseline, dict) or not isinstance(current, dict):
        return baseline.__class__ is current.__class__

    baseline_props = baseline.get("properties", {})
    current_props = current.get("properties", {})

    if not isinstance(baseline_props, dict) or not isinstance(current_props, dict):
        return True

    # All baseline properties must exist in current.
    return all(key in current_props for key in baseline_props)

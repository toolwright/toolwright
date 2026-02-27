"""Provenance scoring — moved from cli/verify.py into core engine."""

from __future__ import annotations

from typing import Any

SOURCE_KINDS = {"http_response", "cache_or_sw", "websocket_or_sse", "local_state"}


def score_candidate(
    *,
    action: dict[str, Any],
    assertion: dict[str, Any],
    order_index: int,
) -> dict[str, Any]:
    """Score an action as a candidate match for an assertion.

    Returns a dict with score (0-1.0), source_kind, signals, and evidence refs.
    """
    assertion_name = str(assertion.get("name", "unnamed_assertion"))
    expect = assertion.get("expect", {})
    expected_value = str(expect.get("value", "")).strip().lower()

    method = str(action.get("method", "GET")).upper()
    host = str(action.get("host", ""))
    path = str(action.get("path", "/"))
    tool_id = str(
        action.get("tool_id") or action.get("signature_id") or action.get("name")
    )
    searchable = " ".join([tool_id, str(action.get("name", "")), host, path]).lower()

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
    score = round(
        (timing * 0.3) + (content_match * 0.35) + (shape_match * 0.25) + (repetition * 0.1),
        3,
    )
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


def run_provenance(
    *,
    actions: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    top_k: int,
    min_confidence: float,
    playbook_version: str,
    assertions_version: str,
    playbook_path: str | None = None,
    ui_assertions_path: str | None = None,
) -> dict[str, Any]:
    """Run provenance verification: match UI assertions to captured actions.

    Returns a provenance result dict compatible with the verify report format.
    """
    results: list[dict[str, Any]] = []
    action_candidates = actions if actions else []

    for assertion in assertions:
        assertion_name = str(assertion.get("name", "unnamed_assertion"))
        candidates = sorted(
            [
                score_candidate(action=action, assertion=assertion, order_index=idx)
                for idx, action in enumerate(action_candidates)
            ],
            key=lambda c: c["score"],
            reverse=True,
        )[:top_k]

        chosen = candidates[0] if candidates else None
        status = "unknown"
        if chosen and chosen["score"] >= min_confidence:
            strong_signals = [
                v
                for v in chosen["signals"].values()
                if isinstance(v, float) and v >= min_confidence
            ]
            if len(strong_signals) >= 2 and chosen["source_kind"] == "http_response":
                status = "pass"
        elif not candidates:
            status = "fail"

        results.append({
            "assertion_name": assertion_name,
            "status": status,
            "top_candidates": candidates,
            "chosen_candidate": chosen,
            "notes": [] if status == "pass" else ["insufficient confidence for deterministic mapping"],
        })

    overall = "pass"
    if any(item["status"] == "fail" for item in results):
        overall = "fail"
    elif any(item["status"] == "unknown" for item in results):
        overall = "unknown"

    return {
        "status": overall,
        "playbook_path": playbook_path,
        "ui_assertions_path": ui_assertions_path,
        "playbook_version": playbook_version,
        "assertions_version": assertions_version,
        "results": results,
        "source_kinds": sorted(SOURCE_KINDS),
    }

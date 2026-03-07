"""Drift handler — severity→action mapping for shape drift.

Routes DriftResult outcomes to the correct action:
  SAFE            → auto-merge via merge_observation(), save baseline
  APPROVAL_REQUIRED → log to drift_events.jsonl for human review
  MANUAL          → log to drift_events.jsonl for human review
  No changes      → no-op
  Error           → no-op (pass through error)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any

from toolwright.core.drift.baselines import DriftResult
from toolwright.core.drift.shape_diff import DriftSeverity
from toolwright.core.drift.shape_inference import merge_observation
from toolwright.models.baseline import BaselineIndex

logger = logging.getLogger("toolwright.drift.handler")


@dataclass
class DriftAction:
    """Result of handling a drift result."""

    tool_name: str
    action: str  # "auto_merged", "logged", "no_drift", "error"
    severity: DriftSeverity | None = None
    error: str | None = None


def handle_drift(
    *,
    drift_result: DriftResult,
    response_body: Any,
    baseline_index: BaselineIndex,
    baselines_path: Path,
    events_path: Path | None = None,
) -> DriftAction:
    """Handle a drift result by routing to the correct action.

    Args:
        drift_result: Result from detect_drift_for_tool().
        response_body: The JSON response body that was probed.
        baseline_index: The in-memory baseline index to update.
        baselines_path: Path to save updated baselines.
        events_path: Path for drift_events.jsonl (required for non-SAFE drift).

    Returns:
        DriftAction describing what was done.
    """
    tool_name = drift_result.tool_name

    # Error result — pass through
    if drift_result.error:
        return DriftAction(
            tool_name=tool_name,
            action="error",
            error=drift_result.error,
        )

    # No changes — no-op
    if not drift_result.changes:
        return DriftAction(
            tool_name=tool_name,
            action="no_drift",
        )

    severity = drift_result.severity

    # SAFE → auto-merge
    if severity == DriftSeverity.SAFE:
        return _auto_merge(
            tool_name=tool_name,
            response_body=response_body,
            baseline_index=baseline_index,
            baselines_path=baselines_path,
        )

    # APPROVAL_REQUIRED or MANUAL → log event
    _log_drift_event(
        tool_name=tool_name,
        drift_result=drift_result,
        events_path=events_path,
    )

    return DriftAction(
        tool_name=tool_name,
        action="logged",
        severity=severity,
    )


def _auto_merge(
    *,
    tool_name: str,
    response_body: Any,
    baseline_index: BaselineIndex,
    baselines_path: Path,
) -> DriftAction:
    """Auto-merge a SAFE drift into the baseline."""
    baseline = baseline_index.baselines[tool_name]

    # Merge the new observation into the existing shape
    merge_observation(baseline.shape, response_body)

    # Update content hash
    baseline.content_hash = baseline.shape.content_hash()

    # Save atomically
    baseline_index.save(baselines_path)

    logger.info(
        "Auto-merged SAFE drift for %s (sample_count=%d)",
        tool_name,
        baseline.shape.sample_count,
    )

    return DriftAction(
        tool_name=tool_name,
        action="auto_merged",
        severity=DriftSeverity.SAFE,
    )


def _log_drift_event(
    *,
    tool_name: str,
    drift_result: DriftResult,
    events_path: Path | None,
) -> None:
    """Append a drift event to the JSONL event log."""
    if events_path is None:
        logger.warning(
            "Drift detected for %s (severity=%s) but no events_path configured",
            tool_name,
            drift_result.severity,
        )
        return

    from datetime import datetime

    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tool_name": tool_name,
        "severity": drift_result.severity.value if drift_result.severity else "unknown",
        "changes": [
            {
                "change_type": c.change_type.value,
                "severity": c.severity.value,
                "path": c.path,
                "description": c.description,
            }
            for c in drift_result.changes
        ],
    }

    events_path.parent.mkdir(parents=True, exist_ok=True)
    with open(events_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

    logger.info(
        "Logged drift event for %s: severity=%s, changes=%d",
        tool_name,
        drift_result.severity,
        len(drift_result.changes),
    )

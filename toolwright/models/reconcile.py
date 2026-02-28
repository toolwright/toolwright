"""Reconciliation loop models for the HEAL pillar (Phase 9).

Level-triggered reconciliation state, configuration, and events.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ToolStatus(StrEnum):
    """Health status of a tool as determined by the reconciliation loop."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class AutoHealPolicy(StrEnum):
    """Auto-heal policy for the reconciliation loop."""

    OFF = "off"
    SAFE = "safe"
    ALL = "all"


class ReconcileAction(StrEnum):
    """Last action taken by the reconciliation loop for a tool."""

    NONE = "none"
    AUTO_REPAIRED = "auto_repaired"
    APPROVAL_QUEUED = "approval_queued"
    QUARANTINED = "quarantined"
    BREAKER_TRIPPED = "breaker_tripped"


class EventKind(StrEnum):
    """Kind of reconciliation event."""

    PROBE_HEALTHY = "probe_healthy"
    PROBE_UNHEALTHY = "probe_unhealthy"
    DRIFT_DETECTED = "drift_detected"
    AUTO_REPAIRED = "auto_repaired"
    REPAIR_FAILED = "repair_failed"
    APPROVAL_QUEUED = "approval_queued"
    QUARANTINED = "quarantined"
    BREAKER_TRIPPED = "breaker_tripped"
    BREAKER_RECOVERED = "breaker_recovered"
    CAPABILITY_REQUESTED = "capability_requested"
    CAPABILITY_DRAFTED = "capability_drafted"
    RULE_SUGGESTED = "rule_suggested"
    ROLLBACK = "rollback"


# ---------------------------------------------------------------------------
# Per-tool reconciliation state
# ---------------------------------------------------------------------------


class ToolReconcileState(BaseModel):
    """Reconciliation state for a single tool."""

    tool_id: str
    status: ToolStatus = ToolStatus.UNKNOWN
    failure_class: str | None = None
    consecutive_healthy: int = 0
    consecutive_unhealthy: int = 0
    last_probe_at: str | None = None
    last_action: ReconcileAction = ReconcileAction.NONE
    pending_repair: str | None = None
    version: int = 0

    # Repair retry budget
    consecutive_repair_failures: int = 0
    repair_suspended: bool = False
    first_failure_at: float | None = None


# ---------------------------------------------------------------------------
# Aggregate reconciliation state
# ---------------------------------------------------------------------------


class ReconcileState(BaseModel):
    """Full reconciliation state for a toolpack."""

    tools: dict[str, ToolReconcileState] = Field(default_factory=dict)
    last_full_reconcile: str | None = None
    reconcile_count: int = 0
    auto_repairs_applied: int = 0
    approvals_queued: int = 0
    errors: int = 0


# ---------------------------------------------------------------------------
# Watch configuration
# ---------------------------------------------------------------------------


class WatchConfig(BaseModel):
    """Configuration for the reconciliation watch loop."""

    auto_heal: AutoHealPolicy = AutoHealPolicy.SAFE

    probe_intervals: dict[str, int] = Field(
        default_factory=lambda: {
            "critical": 120,
            "high": 300,
            "medium": 600,
            "low": 1800,
        }
    )

    max_concurrent_probes: int = 5
    snapshot_before_repair: bool = True

    unhealthy_backoff_multiplier: float = 2.0
    unhealthy_backoff_max: int = 3600

    def probe_interval_for_risk(self, risk_tier: str) -> int:
        """Return the probe interval in seconds for a given risk tier."""
        return self.probe_intervals.get(risk_tier, self.probe_intervals.get("medium", 600))

    @classmethod
    def from_yaml(cls, path: str) -> WatchConfig:
        """Load config from a YAML file. Returns defaults if file is missing."""
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        if not isinstance(data, dict):
            return cls()
        # YAML parses bare `off` as False and `on` as True.
        # Coerce booleans back to the string the enum expects.
        if "auto_heal" in data and isinstance(data["auto_heal"], bool):
            data["auto_heal"] = "off" if not data["auto_heal"] else "all"
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Reconciliation event
# ---------------------------------------------------------------------------


class ReconcileEvent(BaseModel):
    """A single reconciliation event for the JSONL log."""

    kind: EventKind
    tool_id: str
    description: str
    classification: str | None = None
    snapshot_id: str | None = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

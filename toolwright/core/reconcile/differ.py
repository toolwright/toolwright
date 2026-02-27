"""DriftDiffer - wraps DriftEngine for the reconciliation loop.

Determines when drift detection is warranted (only on SCHEMA_CHANGED)
and delegates comparison to the existing DriftEngine.
"""

from __future__ import annotations

from toolwright.core.drift.engine import DriftEngine
from toolwright.core.health.checker import FailureClass, HealthResult
from toolwright.models.drift import DriftReport
from toolwright.models.endpoint import Endpoint


class DriftDiffer:
    """Thin wrapper around DriftEngine for reconcile-loop use.

    Decides whether drift detection should run based on a health probe
    result, and delegates the actual comparison to DriftEngine.
    """

    def __init__(self) -> None:
        self._engine = DriftEngine()

    def should_check_drift(self, health_result: HealthResult) -> bool:
        """Return True only when the failure class is SCHEMA_CHANGED.

        Other failure classes (server errors, auth expired, etc.) are
        not indicative of API drift - they represent operational issues.
        """
        return health_result.failure_class == FailureClass.SCHEMA_CHANGED

    def check_drift(
        self,
        from_endpoints: list[Endpoint],
        to_endpoints: list[Endpoint],
    ) -> DriftReport:
        """Compare two sets of endpoints and return a DriftReport.

        Uses deterministic mode for stable report/drift IDs.
        """
        return self._engine.compare(
            from_endpoints=from_endpoints,
            to_endpoints=to_endpoints,
            deterministic=True,
        )

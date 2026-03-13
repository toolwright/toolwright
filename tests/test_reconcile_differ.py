"""Tests for DriftDiffer — wraps DriftEngine for reconcile loop."""

from __future__ import annotations

from toolwright.core.health.checker import FailureClass, HealthResult
from toolwright.models.drift import DriftReport
from toolwright.models.endpoint import AuthType, Endpoint, Parameter, ParameterLocation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_endpoint(
    *,
    method: str = "GET",
    path: str = "/users",
    host: str = "api.example.com",
    auth_type: AuthType = AuthType.BEARER,
    risk_tier: str = "low",
    parameters: list[Parameter] | None = None,
) -> Endpoint:
    return Endpoint(
        method=method,
        path=path,
        host=host,
        auth_type=auth_type,
        risk_tier=risk_tier,
        parameters=parameters or [],
    )


def _make_health_result(
    *,
    tool_id: str = "get_users",
    healthy: bool = False,
    failure_class: FailureClass | None = None,
    status_code: int | None = None,
) -> HealthResult:
    return HealthResult(
        tool_id=tool_id,
        healthy=healthy,
        failure_class=failure_class,
        status_code=status_code,
    )


# ---------------------------------------------------------------------------
# Tests: should_check_drift
# ---------------------------------------------------------------------------


class TestShouldCheckDrift:
    """DriftDiffer.should_check_drift only returns True for SCHEMA_CHANGED."""

    def test_returns_true_for_schema_changed(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        result = _make_health_result(failure_class=FailureClass.SCHEMA_CHANGED)
        assert differ.should_check_drift(result) is True

    def test_returns_false_for_healthy(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        result = _make_health_result(healthy=True, failure_class=None)
        assert differ.should_check_drift(result) is False

    def test_returns_false_for_server_error(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        result = _make_health_result(failure_class=FailureClass.SERVER_ERROR)
        assert differ.should_check_drift(result) is False

    def test_returns_false_for_auth_expired(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        result = _make_health_result(failure_class=FailureClass.AUTH_EXPIRED)
        assert differ.should_check_drift(result) is False

    def test_returns_false_for_network_unreachable(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        result = _make_health_result(failure_class=FailureClass.NETWORK_UNREACHABLE)
        assert differ.should_check_drift(result) is False

    def test_returns_false_for_endpoint_gone(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        result = _make_health_result(failure_class=FailureClass.ENDPOINT_GONE)
        assert differ.should_check_drift(result) is False

    def test_returns_false_for_rate_limited(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        result = _make_health_result(failure_class=FailureClass.RATE_LIMITED)
        assert differ.should_check_drift(result) is False

    def test_returns_false_for_none_failure_class(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        result = _make_health_result(failure_class=None)
        assert differ.should_check_drift(result) is False


# ---------------------------------------------------------------------------
# Tests: check_drift
# ---------------------------------------------------------------------------


class TestCheckDrift:
    """DriftDiffer.check_drift delegates to DriftEngine.compare."""

    def test_no_drift_when_endpoints_identical(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        endpoints = [_make_endpoint()]
        report = differ.check_drift(endpoints, endpoints)

        assert isinstance(report, DriftReport)
        assert report.total_drifts == 0
        assert report.has_breaking_changes is False

    def test_detects_removed_endpoint(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        original = [_make_endpoint(method="GET", path="/users")]
        current: list[Endpoint] = []

        report = differ.check_drift(original, current)
        assert report.total_drifts > 0
        assert report.breaking_count > 0
        assert report.has_breaking_changes is True

    def test_detects_added_endpoint(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        original: list[Endpoint] = []
        current = [_make_endpoint(method="GET", path="/users")]

        report = differ.check_drift(original, current)
        assert report.total_drifts > 0
        # GET is read-only, so additive
        assert report.additive_count > 0

    def test_detects_auth_change(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        original = [_make_endpoint(auth_type=AuthType.BEARER)]
        current = [_make_endpoint(auth_type=AuthType.API_KEY)]

        report = differ.check_drift(original, current)
        assert report.total_drifts > 0
        assert report.auth_count > 0

    def test_detects_new_state_changing_endpoint(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        original: list[Endpoint] = []
        current = [_make_endpoint(method="POST", path="/users")]

        report = differ.check_drift(original, current)
        assert report.total_drifts > 0
        assert report.risk_count > 0

    def test_returns_drift_report_type(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        report = differ.check_drift([], [])
        assert isinstance(report, DriftReport)
        assert report.total_drifts == 0

    def test_multiple_changes_detected(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        original = [
            _make_endpoint(method="GET", path="/users"),
            _make_endpoint(method="GET", path="/items"),
        ]
        # Remove /users and add POST /orders
        current = [
            _make_endpoint(method="GET", path="/items"),
            _make_endpoint(method="POST", path="/orders"),
        ]

        report = differ.check_drift(original, current)
        assert report.total_drifts >= 2  # at least removal + addition

    def test_parameter_change_detected(self):
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        original = [_make_endpoint(parameters=[])]
        current = [
            _make_endpoint(
                parameters=[
                    Parameter(
                        name="page",
                        location=ParameterLocation.QUERY,
                        required=True,
                    )
                ]
            )
        ]

        report = differ.check_drift(original, current)
        assert report.total_drifts > 0
        assert report.parameter_count > 0

    def test_uses_deterministic_ids(self):
        """DriftDiffer should use deterministic mode for stable report IDs."""
        from toolwright.core.reconcile.differ import DriftDiffer

        differ = DriftDiffer()
        original = [_make_endpoint()]
        current: list[Endpoint] = []

        report1 = differ.check_drift(original, current)
        report2 = differ.check_drift(original, current)

        # Same inputs should produce same drift IDs
        assert report1.drifts[0].id == report2.drifts[0].id

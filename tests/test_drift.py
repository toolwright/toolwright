"""Tests for drift detection engine."""

import json

from toolwright.core.drift import DriftEngine
from toolwright.models.drift import DriftItem, DriftReport, DriftSeverity, DriftType
from toolwright.models.endpoint import AuthType, Endpoint, Parameter, ParameterLocation
from toolwright.utils.schema_version import DETERMINISTIC_TIMESTAMP


def make_endpoint(
    method: str = "GET",
    path: str = "/api/users/{id}",
    host: str = "api.example.com",
    is_first_party: bool = True,
    is_auth_related: bool = False,
    has_pii: bool = False,
    is_state_changing: bool = False,
    risk_tier: str = "low",
    auth_type: AuthType = AuthType.BEARER,
    parameters: list[Parameter] | None = None,
    response_status_codes: list[int] | None = None,
    request_body_schema: dict | None = None,
    response_body_schema: dict | None = None,
) -> Endpoint:
    """Create a test endpoint."""
    return Endpoint(
        method=method,
        path=path,
        host=host,
        is_first_party=is_first_party,
        is_auth_related=is_auth_related,
        has_pii=has_pii,
        is_state_changing=is_state_changing,
        risk_tier=risk_tier,
        auth_type=auth_type,
        parameters=parameters or [],
        response_status_codes=response_status_codes or [200],
        request_body_schema=request_body_schema,
        response_body_schema=response_body_schema,
    )


class TestDriftEngine:
    """Tests for DriftEngine."""

    def test_compare_identical_endpoints(self):
        """Test comparing identical endpoint sets produces no drift."""
        endpoints = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="POST", path="/api/users"),
        ]

        engine = DriftEngine()
        report = engine.compare(endpoints, endpoints)

        assert report.total_drifts == 0
        assert report.exit_code == 0
        assert not report.has_breaking_changes

    def test_detect_removed_endpoint(self):
        """Test detecting a removed endpoint."""
        old_endpoints = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="GET", path="/api/users/{id}"),
        ]
        new_endpoints = [
            make_endpoint(method="GET", path="/api/users"),
        ]

        engine = DriftEngine()
        report = engine.compare(old_endpoints, new_endpoints)

        assert report.total_drifts == 1
        assert report.breaking_count == 1
        assert report.has_breaking_changes
        assert report.exit_code == 2

        drift = report.drifts[0]
        assert drift.type == DriftType.BREAKING
        assert drift.severity == DriftSeverity.CRITICAL
        assert "removed" in drift.title.lower()

    def test_detect_added_readonly_endpoint(self):
        """Test detecting an added read-only endpoint (additive)."""
        old_endpoints = [
            make_endpoint(method="GET", path="/api/users"),
        ]
        new_endpoints = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="GET", path="/api/users/{id}"),
        ]

        engine = DriftEngine()
        report = engine.compare(old_endpoints, new_endpoints)

        assert report.total_drifts == 1
        assert report.additive_count == 1
        assert not report.has_breaking_changes
        assert report.exit_code == 0

        drift = report.drifts[0]
        assert drift.type == DriftType.ADDITIVE
        assert drift.severity == DriftSeverity.INFO

    def test_detect_added_state_changing_endpoint(self):
        """Test detecting an added state-changing endpoint (risk)."""
        old_endpoints = [
            make_endpoint(method="GET", path="/api/users"),
        ]
        new_endpoints = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="POST", path="/api/users", is_state_changing=True),
        ]

        engine = DriftEngine()
        report = engine.compare(old_endpoints, new_endpoints)

        assert report.total_drifts == 1
        assert report.risk_count == 1
        assert report.requires_review
        assert report.exit_code == 1

        drift = report.drifts[0]
        assert drift.type == DriftType.RISK
        assert drift.severity == DriftSeverity.WARNING

    def test_detect_auth_type_change(self):
        """Test detecting auth type change."""
        old_endpoints = [
            make_endpoint(auth_type=AuthType.BEARER),
        ]
        new_endpoints = [
            make_endpoint(auth_type=AuthType.API_KEY),
        ]

        engine = DriftEngine()
        report = engine.compare(old_endpoints, new_endpoints)

        assert report.total_drifts == 1
        assert report.auth_count == 1
        assert report.has_breaking_changes
        assert report.exit_code == 2

        drift = report.drifts[0]
        assert drift.type == DriftType.AUTH
        assert drift.severity == DriftSeverity.CRITICAL

    def test_detect_parameter_added(self):
        """Test detecting a new required parameter."""
        old_endpoints = [
            make_endpoint(parameters=[]),
        ]
        new_endpoints = [
            make_endpoint(
                parameters=[
                    Parameter(
                        name="page",
                        location=ParameterLocation.QUERY,
                        param_type="integer",
                        required=True,
                    )
                ]
            ),
        ]

        engine = DriftEngine()
        report = engine.compare(old_endpoints, new_endpoints)

        assert report.total_drifts == 1
        assert report.parameter_count == 1

        drift = report.drifts[0]
        assert drift.type == DriftType.PARAMETER

    def test_detect_parameter_removed(self):
        """Test detecting a removed parameter."""
        old_endpoints = [
            make_endpoint(
                parameters=[
                    Parameter(
                        name="page",
                        location=ParameterLocation.QUERY,
                        param_type="integer",
                        required=False,
                    )
                ]
            ),
        ]
        new_endpoints = [
            make_endpoint(parameters=[]),
        ]

        engine = DriftEngine()
        report = engine.compare(old_endpoints, new_endpoints)

        assert report.total_drifts == 1
        assert report.drifts[0].type == DriftType.PARAMETER

    def test_detect_response_schema_change(self):
        """Test detecting response schema change (breaking)."""
        old_endpoints = [
            make_endpoint(
                response_body_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "email": {"type": "string"},
                    },
                }
            ),
        ]
        new_endpoints = [
            make_endpoint(
                response_body_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        # email removed
                    },
                }
            ),
        ]

        engine = DriftEngine()
        report = engine.compare(old_endpoints, new_endpoints)

        # Removing a field from response is breaking
        assert report.total_drifts >= 1
        assert any(d.type in (DriftType.SCHEMA, DriftType.BREAKING) for d in report.drifts)

    def test_detect_request_schema_change(self):
        """Test detecting request schema change."""
        old_endpoints = [
            make_endpoint(
                method="POST",
                request_body_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                }
            ),
        ]
        new_endpoints = [
            make_endpoint(
                method="POST",
                request_body_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"},  # New field
                    },
                    "required": ["name", "email"],  # Now required
                }
            ),
        ]

        engine = DriftEngine()
        report = engine.compare(old_endpoints, new_endpoints)

        # Adding a required field is potentially breaking
        assert report.total_drifts >= 1

    def test_detect_risk_tier_change(self):
        """Test detecting risk tier escalation."""
        old_endpoints = [
            make_endpoint(risk_tier="low"),
        ]
        new_endpoints = [
            make_endpoint(risk_tier="high"),
        ]

        engine = DriftEngine()
        report = engine.compare(old_endpoints, new_endpoints)

        assert report.total_drifts == 1
        drift = report.drifts[0]
        assert drift.type == DriftType.RISK
        assert "risk" in drift.title.lower() or "tier" in drift.title.lower()

    def test_multiple_drifts(self):
        """Test detecting multiple drifts."""
        old_endpoints = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="GET", path="/api/users/{id}"),
        ]
        new_endpoints = [
            # users list endpoint removed
            make_endpoint(method="GET", path="/api/users/{id}", auth_type=AuthType.API_KEY),
            make_endpoint(method="DELETE", path="/api/users/{id}", is_state_changing=True),  # new
        ]

        engine = DriftEngine()
        report = engine.compare(old_endpoints, new_endpoints)

        # Should detect: removed endpoint, auth change, new state-changing
        assert report.total_drifts >= 3
        assert report.breaking_count >= 1
        assert report.has_breaking_changes

    def test_deterministic_report_ids_and_timestamps(self):
        """Deterministic mode should produce stable IDs and generated_at."""
        old_endpoints = [
            make_endpoint(method="GET", path="/api/users"),
        ]
        new_endpoints = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="POST", path="/api/users", is_state_changing=True),
        ]

        engine = DriftEngine()
        report_one = engine.compare(
            old_endpoints,
            new_endpoints,
            from_capture_id="cap_old",
            to_capture_id="cap_new",
            deterministic=True,
        )
        report_two = engine.compare(
            old_endpoints,
            new_endpoints,
            from_capture_id="cap_old",
            to_capture_id="cap_new",
            deterministic=True,
        )

        assert report_one.id == report_two.id
        assert [item.id for item in report_one.drifts] == [item.id for item in report_two.drifts]
        assert report_one.generated_at == DETERMINISTIC_TIMESTAMP
        assert report_two.generated_at == DETERMINISTIC_TIMESTAMP


class TestCompareToBaseline:
    """Tests for comparing endpoints to baseline."""

    def test_compare_to_baseline_no_drift(self):
        """Test comparing endpoints to baseline with no drift."""
        baseline = {
            "version": "1.0.0",
            "endpoints": [
                {
                    "stable_id": "abc123",
                    "method": "GET",
                    "path": "/api/users",
                    "host": "api.example.com",
                    "auth_type": "bearer",
                    "parameters": [],
                    "response_status_codes": [200],
                    "is_state_changing": False,
                    "risk_tier": "low",
                },
            ],
        }

        endpoints = [
            make_endpoint(method="GET", path="/api/users"),
        ]

        engine = DriftEngine()
        report = engine.compare_to_baseline(baseline, endpoints)

        assert report.total_drifts == 0
        assert report.exit_code == 0

    def test_compare_to_baseline_endpoint_removed(self):
        """Test detecting endpoint removed from baseline."""
        baseline = {
            "version": "1.0.0",
            "endpoints": [
                {
                    "stable_id": "abc123",
                    "method": "GET",
                    "path": "/api/users",
                    "host": "api.example.com",
                    "auth_type": "bearer",
                    "parameters": [],
                    "response_status_codes": [200],
                    "is_state_changing": False,
                    "risk_tier": "low",
                },
                {
                    "stable_id": "def456",
                    "method": "GET",
                    "path": "/api/users/{id}",
                    "host": "api.example.com",
                    "auth_type": "bearer",
                    "parameters": [],
                    "response_status_codes": [200],
                    "is_state_changing": False,
                    "risk_tier": "low",
                },
            ],
        }

        endpoints = [
            make_endpoint(method="GET", path="/api/users"),
            # /api/users/{id} missing
        ]

        engine = DriftEngine()
        report = engine.compare_to_baseline(baseline, endpoints)

        assert report.total_drifts >= 1
        assert report.breaking_count >= 1
        assert report.has_breaking_changes

    def test_compare_to_baseline_new_endpoint(self):
        """Test detecting new endpoint not in baseline."""
        baseline = {
            "version": "1.0.0",
            "endpoints": [
                {
                    "stable_id": "abc123",
                    "method": "GET",
                    "path": "/api/users",
                    "host": "api.example.com",
                    "auth_type": "bearer",
                    "parameters": [],
                    "response_status_codes": [200],
                    "is_state_changing": False,
                    "risk_tier": "low",
                },
            ],
        }

        endpoints = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="POST", path="/api/users", is_state_changing=True),
        ]

        engine = DriftEngine()
        report = engine.compare_to_baseline(baseline, endpoints)

        assert report.total_drifts >= 1
        assert report.risk_count >= 1  # New state-changing endpoint


class TestDriftClassification:
    """Tests for drift classification logic."""

    def test_classify_endpoint_removal_as_breaking(self):
        """Test that endpoint removal is classified as breaking."""
        engine = DriftEngine()
        drift = engine._create_removal_drift(
            make_endpoint(method="GET", path="/api/users")
        )
        assert drift.type == DriftType.BREAKING
        assert drift.severity == DriftSeverity.CRITICAL

    def test_classify_readonly_addition_as_additive(self):
        """Test that read-only endpoint addition is additive."""
        engine = DriftEngine()
        drift = engine._create_addition_drift(
            make_endpoint(method="GET", path="/api/users/{id}", is_state_changing=False)
        )
        assert drift.type == DriftType.ADDITIVE
        assert drift.severity == DriftSeverity.INFO

    def test_classify_state_changing_addition_as_risk(self):
        """Test that state-changing endpoint addition is risk."""
        engine = DriftEngine()
        drift = engine._create_addition_drift(
            make_endpoint(method="POST", path="/api/users", is_state_changing=True)
        )
        assert drift.type == DriftType.RISK
        assert drift.severity == DriftSeverity.WARNING

    def test_classify_delete_addition_as_risk(self):
        """Test that DELETE endpoint addition is risk even without flag."""
        engine = DriftEngine()
        drift = engine._create_addition_drift(
            make_endpoint(method="DELETE", path="/api/users/{id}")
        )
        assert drift.type == DriftType.RISK


class TestDriftReporter:
    """Tests for drift report generation."""

    def test_report_to_json(self):
        """Test JSON serialization of drift report."""
        engine = DriftEngine()
        report = DriftReport(
            id="drift_test",
            from_capture_id="cap_old",
            to_capture_id="cap_new",
            total_drifts=1,
            breaking_count=1,
            has_breaking_changes=True,
            exit_code=2,
            drifts=[
                DriftItem(
                    id="d1",
                    type=DriftType.BREAKING,
                    severity=DriftSeverity.CRITICAL,
                    path="/api/users/{id}",
                    method="GET",
                    title="Endpoint removed",
                    description="GET /api/users/{id} was removed",
                )
            ],
        )

        json_str = engine.to_json(report)
        parsed = json.loads(json_str)

        assert parsed["id"] == "drift_test"
        assert parsed["total_drifts"] == 1
        assert parsed["has_breaking_changes"] is True
        assert len(parsed["drifts"]) == 1
        assert parsed["drifts"][0]["type"] == "breaking"

    def test_report_to_markdown(self):
        """Test Markdown report generation."""
        engine = DriftEngine()
        report = DriftReport(
            id="drift_test",
            from_capture_id="cap_old",
            to_capture_id="cap_new",
            total_drifts=2,
            breaking_count=1,
            additive_count=1,
            has_breaking_changes=True,
            requires_review=True,
            exit_code=2,
            drifts=[
                DriftItem(
                    id="d1",
                    type=DriftType.BREAKING,
                    severity=DriftSeverity.CRITICAL,
                    path="/api/users/{id}",
                    method="GET",
                    title="Endpoint removed",
                    description="GET /api/users/{id} was removed",
                    recommendation="Restore endpoint or update consumers",
                ),
                DriftItem(
                    id="d2",
                    type=DriftType.ADDITIVE,
                    severity=DriftSeverity.INFO,
                    path="/api/orders",
                    method="GET",
                    title="New read-only endpoint",
                    description="GET /api/orders was added",
                ),
            ],
        )

        md = engine.to_markdown(report)

        assert "# Drift Report" in md
        assert "Breaking Changes" in md or "BREAKING" in md
        assert "/api/users/{id}" in md
        assert "Endpoint removed" in md


class TestExitCodes:
    """Tests for CI exit code calculation."""

    def test_exit_code_0_for_no_drift(self):
        """Test exit code 0 for no drift."""
        engine = DriftEngine()
        report = engine.compare([], [])
        assert report.exit_code == 0

    def test_exit_code_0_for_additive_only(self):
        """Test exit code 0 for additive-only drift."""
        old = []
        new = [make_endpoint(method="GET", path="/api/users")]

        engine = DriftEngine()
        report = engine.compare(old, new)

        assert report.additive_count >= 1
        assert report.exit_code == 0

    def test_exit_code_1_for_warnings(self):
        """Test exit code 1 for warning-level drift."""
        old = [make_endpoint(method="GET", path="/api/users")]
        new = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="POST", path="/api/users", is_state_changing=True),
        ]

        engine = DriftEngine()
        report = engine.compare(old, new)

        assert report.risk_count >= 1
        assert report.exit_code == 1

    def test_exit_code_2_for_breaking(self):
        """Test exit code 2 for breaking drift."""
        old = [
            make_endpoint(method="GET", path="/api/users"),
            make_endpoint(method="GET", path="/api/users/{id}"),
        ]
        new = [make_endpoint(method="GET", path="/api/users")]

        engine = DriftEngine()
        report = engine.compare(old, new)

        assert report.breaking_count >= 1
        assert report.exit_code == 2

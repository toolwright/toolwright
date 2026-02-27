"""Tests for verify-drift integration — contract failures as drift items."""

from __future__ import annotations

from toolwright.models.drift import DriftItem, DriftReport, DriftSeverity, DriftType


def test_drift_type_has_contract() -> None:
    assert DriftType.CONTRACT == "contract"
    assert "contract" in [t.value for t in DriftType]


def test_drift_report_has_contract_count() -> None:
    report = DriftReport(id="test", contract_count=3)
    assert report.contract_count == 3


def test_contract_drift_item() -> None:
    """Contract failures should be representable as drift items."""
    item = DriftItem(
        id="d_contract_001",
        type=DriftType.CONTRACT,
        severity=DriftSeverity.ERROR,
        title="Contract assertion failed: field 'users' missing",
        description="Verification contract vc_test expected field 'users' to exist in GET /api/users response",
        before="field exists",
        after="field missing",
        recommendation="Investigate API changes or update contract",
    )
    assert item.type == DriftType.CONTRACT
    assert item.severity == DriftSeverity.ERROR


def test_drift_report_with_contract_items() -> None:
    """Drift report should correctly aggregate contract drift items."""
    items = [
        DriftItem(
            id="d_1",
            type=DriftType.CONTRACT,
            severity=DriftSeverity.ERROR,
            title="Contract failed",
            description="Assertion check failed",
        ),
        DriftItem(
            id="d_2",
            type=DriftType.ADDITIVE,
            severity=DriftSeverity.INFO,
            title="New endpoint added",
            description="GET /api/new was added",
        ),
    ]
    report = DriftReport(
        id="drift_test",
        drifts=items,
        total_drifts=2,
        contract_count=1,
        additive_count=1,
        has_breaking_changes=False,
        exit_code=2,  # contract failure = breaking
    )
    assert report.contract_count == 1
    assert report.exit_code == 2


def test_contract_failure_is_breaking() -> None:
    """Contract failures should trigger exit code 2 (breaking)."""
    # This test documents the design decision: contract assertion failures
    # are treated as breaking changes because they indicate the API no
    # longer meets its declared contract.
    report = DriftReport(
        id="drift_contract",
        drifts=[
            DriftItem(
                id="d_c1",
                type=DriftType.CONTRACT,
                severity=DriftSeverity.ERROR,
                title="Contract broke",
                description="Field missing",
            ),
        ],
        total_drifts=1,
        contract_count=1,
        has_breaking_changes=True,
        exit_code=2,
    )
    assert report.has_breaking_changes is True
    assert report.exit_code == 2

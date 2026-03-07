"""Tests for drift_handler — severity→action mapping for shape drift.

Covers: SAFE auto-merge updates baseline, APPROVAL_REQUIRED logs event,
MANUAL logs event, no-changes is a no-op, error result is a no-op,
and auto-merge bumps sample_count.
"""
from __future__ import annotations

import json

from toolwright.core.drift.baselines import DriftResult
from toolwright.core.drift.shape_diff import DriftChange, DriftChangeType, DriftSeverity
from toolwright.models.baseline import BaselineIndex, ToolBaseline
from toolwright.models.probe_template import ProbeTemplate
from toolwright.models.shape import FieldShape, ShapeModel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_baseline_index(
    tool_name: str = "list_products",
    sample_count: int = 10,
) -> BaselineIndex:
    """Build a BaselineIndex with one tool baseline."""
    shape = ShapeModel(sample_count=sample_count, last_updated="2026-03-01T12:00:00Z")
    shape.fields[""] = FieldShape(
        types_seen={"object"},
        nullable=False,
        object_keys_seen={"products"},
        seen_count=sample_count,
        sample_count=sample_count,
    )
    shape.fields[".products"] = FieldShape(
        types_seen={"array"},
        nullable=False,
        array_item_types_seen={"object"},
        seen_count=sample_count,
        sample_count=sample_count,
    )
    shape.fields[".products[]"] = FieldShape(
        types_seen={"object"},
        nullable=False,
        object_keys_seen={"id", "title"},
        seen_count=sample_count,
        sample_count=sample_count,
    )
    shape.fields[".products[].id"] = FieldShape(
        types_seen={"integer"},
        nullable=False,
        seen_count=sample_count,
        sample_count=sample_count,
    )
    shape.fields[".products[].title"] = FieldShape(
        types_seen={"string"},
        nullable=False,
        seen_count=sample_count,
        sample_count=sample_count,
    )

    index = BaselineIndex()
    index.baselines[tool_name] = ToolBaseline(
        shape=shape,
        probe_template=ProbeTemplate(method="GET", path="/products"),
        content_hash=shape.content_hash(),
        source="har",
    )
    return index


def _safe_drift_result(tool_name: str = "list_products") -> DriftResult:
    """Drift result with a single SAFE change (field added)."""
    return DriftResult(
        tool_name=tool_name,
        changes=[
            DriftChange(
                change_type=DriftChangeType.FIELD_ADDED,
                severity=DriftSeverity.SAFE,
                path=".products[].price",
                description="New field: .products[].price (number)",
                baseline_value=None,
                observed_value="number",
            ),
        ],
        severity=DriftSeverity.SAFE,
    )


def _manual_drift_result(tool_name: str = "list_products") -> DriftResult:
    """Drift result with a MANUAL severity change."""
    return DriftResult(
        tool_name=tool_name,
        changes=[
            DriftChange(
                change_type=DriftChangeType.TYPE_CHANGED_BREAKING,
                severity=DriftSeverity.MANUAL,
                path=".products[].id",
                description="Type changed: integer -> string at .products[].id",
                baseline_value="integer",
                observed_value="string",
            ),
        ],
        severity=DriftSeverity.MANUAL,
    )


def _approval_drift_result(tool_name: str = "list_products") -> DriftResult:
    """Drift result with APPROVAL_REQUIRED severity."""
    return DriftResult(
        tool_name=tool_name,
        changes=[
            DriftChange(
                change_type=DriftChangeType.NULLABILITY_CHANGED,
                severity=DriftSeverity.APPROVAL_REQUIRED,
                path=".products[].title",
                description="Nullability changed at .products[].title",
                baseline_value="non-nullable",
                observed_value="nullable",
            ),
        ],
        severity=DriftSeverity.APPROVAL_REQUIRED,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDriftHandlerSafeAutoMerge:
    def test_safe_drift_merges_into_baseline(self, tmp_path):
        """SAFE drift -> merge_observation into baseline, save index."""
        from toolwright.core.drift.drift_handler import handle_drift

        index = _make_baseline_index()
        response_body = {"products": [{"id": 1, "title": "Widget", "price": 9.99}]}
        drift_result = _safe_drift_result()
        baselines_path = tmp_path / "shape_baselines.json"

        action = handle_drift(
            drift_result=drift_result,
            response_body=response_body,
            baseline_index=index,
            baselines_path=baselines_path,
        )

        assert action.action == "auto_merged"
        assert action.tool_name == "list_products"

        # Baseline should be updated: sample_count bumped
        bl = index.baselines["list_products"]
        assert bl.shape.sample_count == 11  # was 10, merged 1

        # New field should exist in shape
        assert ".products[].price" in bl.shape.fields

        # File should be written
        assert baselines_path.exists()

    def test_safe_drift_content_hash_updated(self, tmp_path):
        """After auto-merge, content_hash should be recalculated."""
        from toolwright.core.drift.drift_handler import handle_drift

        index = _make_baseline_index()
        old_hash = index.baselines["list_products"].content_hash
        response_body = {"products": [{"id": 1, "title": "Widget", "price": 9.99}]}
        drift_result = _safe_drift_result()
        baselines_path = tmp_path / "shape_baselines.json"

        handle_drift(
            drift_result=drift_result,
            response_body=response_body,
            baseline_index=index,
            baselines_path=baselines_path,
        )

        new_hash = index.baselines["list_products"].content_hash
        assert new_hash != old_hash


class TestDriftHandlerManualLog:
    def test_manual_drift_logged_not_merged(self, tmp_path):
        """MANUAL drift -> log event, do NOT merge into baseline."""
        from toolwright.core.drift.drift_handler import handle_drift

        index = _make_baseline_index()
        response_body = {"products": [{"id": "abc", "title": "Widget"}]}
        drift_result = _manual_drift_result()
        baselines_path = tmp_path / "shape_baselines.json"
        events_path = tmp_path / "drift_events.jsonl"

        action = handle_drift(
            drift_result=drift_result,
            response_body=response_body,
            baseline_index=index,
            baselines_path=baselines_path,
            events_path=events_path,
        )

        assert action.action == "logged"
        assert action.severity == DriftSeverity.MANUAL

        # Baseline should NOT be modified
        bl = index.baselines["list_products"]
        assert bl.shape.sample_count == 10  # unchanged

        # Event should be logged
        assert events_path.exists()
        events = [json.loads(line) for line in events_path.read_text().strip().split("\n")]
        assert len(events) == 1
        assert events[0]["tool_name"] == "list_products"
        assert events[0]["severity"] == "manual"


class TestDriftHandlerApprovalRequired:
    def test_approval_required_logged_not_merged(self, tmp_path):
        """APPROVAL_REQUIRED drift -> log event, do NOT merge."""
        from toolwright.core.drift.drift_handler import handle_drift

        index = _make_baseline_index()
        response_body = {"products": [{"id": 1, "title": None}]}
        drift_result = _approval_drift_result()
        baselines_path = tmp_path / "shape_baselines.json"
        events_path = tmp_path / "drift_events.jsonl"

        action = handle_drift(
            drift_result=drift_result,
            response_body=response_body,
            baseline_index=index,
            baselines_path=baselines_path,
            events_path=events_path,
        )

        assert action.action == "logged"
        assert action.severity == DriftSeverity.APPROVAL_REQUIRED

        # Baseline untouched
        assert index.baselines["list_products"].shape.sample_count == 10


class TestDriftHandlerNoChanges:
    def test_no_changes_is_noop(self, tmp_path):
        """DriftResult with empty changes -> no action."""
        from toolwright.core.drift.drift_handler import handle_drift

        index = _make_baseline_index()
        drift_result = DriftResult(
            tool_name="list_products",
            changes=[],
            severity=None,
        )
        baselines_path = tmp_path / "shape_baselines.json"

        action = handle_drift(
            drift_result=drift_result,
            response_body={"products": [{"id": 1, "title": "Widget"}]},
            baseline_index=index,
            baselines_path=baselines_path,
        )

        assert action.action == "no_drift"
        assert not baselines_path.exists()


class TestDriftHandlerErrorResult:
    def test_error_result_is_noop(self, tmp_path):
        """DriftResult with error -> no action."""
        from toolwright.core.drift.drift_handler import handle_drift

        index = _make_baseline_index()
        drift_result = DriftResult(
            tool_name="unknown_tool",
            error="Baseline for tool 'unknown_tool' not found in index",
        )
        baselines_path = tmp_path / "shape_baselines.json"

        action = handle_drift(
            drift_result=drift_result,
            response_body={},
            baseline_index=index,
            baselines_path=baselines_path,
        )

        assert action.action == "error"
        assert "not found" in (action.error or "").lower()

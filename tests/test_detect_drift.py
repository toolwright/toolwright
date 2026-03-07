"""Tests for detect_drift_for_tool() — per-tool shape drift detection.

Covers: no-drift baseline match, field additions (SAFE), type changes
(MANUAL), missing required paths, unknown tool handling, and empty baselines.
"""
from __future__ import annotations

from toolwright.core.drift.shape_diff import DriftChangeType, DriftSeverity
from toolwright.models.baseline import BaselineIndex, ToolBaseline
from toolwright.models.probe_template import ProbeTemplate
from toolwright.models.shape import FieldShape, ShapeModel


def _make_index_with_tool(
    tool_name: str = "get_products",
    fields: dict | None = None,
    sample_count: int = 10,
) -> BaselineIndex:
    """Build a BaselineIndex with a single tool baseline."""
    shape = ShapeModel(sample_count=sample_count, last_updated="2026-03-01T12:00:00Z")
    if fields is None:
        fields = {
            "": {
                "types_seen": {"object"},
                "nullable": False,
                "object_keys_seen": {"products"},
                "seen_count": sample_count,
                "sample_count": sample_count,
            },
            ".products": {
                "types_seen": {"array"},
                "nullable": False,
                "array_item_types_seen": {"object"},
                "seen_count": sample_count,
                "sample_count": sample_count,
            },
            ".products[]": {
                "types_seen": {"object"},
                "nullable": False,
                "object_keys_seen": {"id", "title"},
                "seen_count": sample_count,
                "sample_count": sample_count,
            },
            ".products[].id": {
                "types_seen": {"integer"},
                "nullable": False,
                "seen_count": sample_count,
                "sample_count": sample_count,
            },
            ".products[].title": {
                "types_seen": {"string"},
                "nullable": False,
                "seen_count": sample_count,
                "sample_count": sample_count,
            },
        }

    for path, spec in fields.items():
        shape.fields[path] = FieldShape(
            types_seen=spec["types_seen"],
            nullable=spec.get("nullable", False),
            object_keys_seen=spec.get("object_keys_seen"),
            array_item_types_seen=spec.get("array_item_types_seen"),
            seen_count=spec.get("seen_count", sample_count),
            sample_count=spec.get("sample_count", sample_count),
        )

    index = BaselineIndex()
    index.baselines[tool_name] = ToolBaseline(
        shape=shape,
        probe_template=ProbeTemplate(method="GET", path="/products"),
        content_hash=shape.content_hash(),
        source="har",
    )
    return index


class TestDetectDriftNoDrift:
    def test_identical_response_no_changes(self):
        """Response matching baseline -> no drift changes."""
        from toolwright.core.drift.baselines import detect_drift_for_tool

        index = _make_index_with_tool()
        body = {"products": [{"id": 1, "title": "Widget"}]}

        result = detect_drift_for_tool("get_products", body, index)
        assert result.changes == []
        assert result.severity is None


class TestDetectDriftFieldAdded:
    def test_new_field_is_safe(self):
        """Response with a new field -> SAFE drift."""
        from toolwright.core.drift.baselines import detect_drift_for_tool

        index = _make_index_with_tool()
        body = {"products": [{"id": 1, "title": "Widget", "price": 9.99}]}

        result = detect_drift_for_tool("get_products", body, index)
        safe_changes = [c for c in result.changes if c.severity == DriftSeverity.SAFE]
        assert len(safe_changes) > 0
        field_added = [c for c in safe_changes if c.change_type == DriftChangeType.FIELD_ADDED]
        assert len(field_added) > 0


class TestDetectDriftTypeChanged:
    def test_type_change_is_manual(self):
        """Field type changes from integer to string -> MANUAL."""
        from toolwright.core.drift.baselines import detect_drift_for_tool

        index = _make_index_with_tool()
        # id is now a string instead of integer
        body = {"products": [{"id": "abc", "title": "Widget"}]}

        result = detect_drift_for_tool("get_products", body, index)
        manual_changes = [c for c in result.changes if c.severity == DriftSeverity.MANUAL]
        assert len(manual_changes) > 0


class TestDetectDriftUnknownTool:
    def test_unknown_tool_returns_error(self):
        """Tool not in baseline -> error result."""
        from toolwright.core.drift.baselines import detect_drift_for_tool

        index = BaselineIndex()  # empty
        body = {"products": []}

        result = detect_drift_for_tool("nonexistent_tool", body, index)
        assert result.error is not None
        assert "not found" in result.error.lower()


class TestDetectDriftEmptyResponse:
    def test_empty_array_no_false_positives(self):
        """Empty array response should not trigger missing-path drift."""
        from toolwright.core.drift.baselines import detect_drift_for_tool

        index = _make_index_with_tool()
        body = {"products": []}  # Empty array — children unknown

        result = detect_drift_for_tool("get_products", body, index)
        # Should NOT report required_path_missing for .products[].id etc
        manual_missing = [
            c for c in result.changes
            if c.change_type == DriftChangeType.REQUIRED_PATH_MISSING
        ]
        assert len(manual_missing) == 0


class TestDetectDriftRootTypeChange:
    def test_root_type_change(self):
        """Response root type changes from object to array -> MANUAL."""
        from toolwright.core.drift.baselines import detect_drift_for_tool

        index = _make_index_with_tool()
        body = [{"id": 1}]  # Array instead of object

        result = detect_drift_for_tool("get_products", body, index)
        root_changes = [
            c for c in result.changes
            if c.change_type == DriftChangeType.ROOT_TYPE_CHANGED
        ]
        assert len(root_changes) == 1
        assert root_changes[0].severity == DriftSeverity.MANUAL

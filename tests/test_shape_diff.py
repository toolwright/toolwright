"""Tests for the shape diffing algorithm.

Covers: change classification, severity escalation, safe widenings,
empty/truncated array handling, presence thresholds, and immutability.
"""

from __future__ import annotations

import copy

from toolwright.core.drift.constants import MIN_SAMPLES_FOR_PRESENCE
from toolwright.core.drift.shape_diff import (
    DriftChangeType,
    DriftSeverity,
    _is_safe_widening,
    diff_shapes,
    overall_severity,
)
from toolwright.core.drift.shape_inference import InferenceMetadata
from toolwright.models.shape import FieldShape, ShapeModel


def _build_shape(fields_spec: dict, sample_count: int = 10) -> ShapeModel:
    """Build a ShapeModel from a compact spec dict.

    Each key is a path, each value is a dict with:
      types_seen, nullable (optional), seen_count (optional),
      object_keys_seen (optional), array_item_types_seen (optional)
    """
    model = ShapeModel(sample_count=sample_count)
    for path, spec in fields_spec.items():
        model.fields[path] = FieldShape(
            types_seen=set(spec["types_seen"]),
            nullable=spec.get("nullable", False),
            object_keys_seen=(
                set(spec["object_keys_seen"])
                if "object_keys_seen" in spec
                else None
            ),
            array_item_types_seen=(
                set(spec["array_item_types_seen"])
                if "array_item_types_seen" in spec
                else None
            ),
            seen_count=spec.get("seen_count", sample_count),
            sample_count=spec.get("sample_count", sample_count),
        )
    return model


# ---------------------------------------------------------------------------
# Basic diff cases
# ---------------------------------------------------------------------------


class TestNoChanges:
    def test_no_changes(self):
        spec = {
            "": {"types_seen": ["object"], "object_keys_seen": ["id"]},
            ".id": {"types_seen": ["integer"]},
        }
        baseline = _build_shape(spec)
        observed = _build_shape(spec)

        changes = diff_shapes(baseline, observed)
        assert changes == []


class TestNewFieldIsSafe:
    def test_new_field_is_safe(self):
        baseline = _build_shape(
            {"": {"types_seen": ["object"], "object_keys_seen": ["id"]}}
        )
        observed = _build_shape(
            {
                "": {"types_seen": ["object"], "object_keys_seen": ["id", "name"]},
                ".name": {"types_seen": ["string"]},
            }
        )

        changes = diff_shapes(baseline, observed)
        assert len(changes) == 1
        assert changes[0].change_type == DriftChangeType.FIELD_ADDED
        assert changes[0].severity == DriftSeverity.SAFE


# ---------------------------------------------------------------------------
# Type widening
# ---------------------------------------------------------------------------


class TestTypeWidenedIntToNumber:
    def test_type_widened_int_to_number(self):
        baseline = _build_shape(
            {".x": {"types_seen": ["integer"]}}
        )
        observed = _build_shape(
            {".x": {"types_seen": ["integer", "number"]}}
        )

        changes = diff_shapes(baseline, observed)
        assert len(changes) == 1
        assert changes[0].change_type == DriftChangeType.TYPE_WIDENED_SAFE
        assert changes[0].severity == DriftSeverity.SAFE


class TestTypeWidenedIntToStringIsManual:
    def test_type_widened_int_to_string_is_manual(self):
        baseline = _build_shape(
            {".x": {"types_seen": ["integer"]}}
        )
        observed = _build_shape(
            {".x": {"types_seen": ["integer", "string"]}}
        )

        changes = diff_shapes(baseline, observed)
        assert len(changes) == 1
        assert changes[0].change_type == DriftChangeType.TYPE_CHANGED_BREAKING
        assert changes[0].severity == DriftSeverity.MANUAL


class TestTypeWidenedMulti:
    def test_type_widened_multi(self):
        """{integer, string} -> {integer, string, number} is SAFE."""
        baseline = _build_shape(
            {".x": {"types_seen": ["integer", "string"]}}
        )
        observed = _build_shape(
            {".x": {"types_seen": ["integer", "string", "number"]}}
        )

        changes = diff_shapes(baseline, observed)
        assert len(changes) == 1
        assert changes[0].change_type == DriftChangeType.TYPE_WIDENED_SAFE
        assert changes[0].severity == DriftSeverity.SAFE


class TestTypeNarrowedIsManual:
    def test_type_narrowed_is_manual(self):
        baseline = _build_shape(
            {".x": {"types_seen": ["integer", "string"]}}
        )
        observed = _build_shape(
            {".x": {"types_seen": ["integer"]}}
        )

        changes = diff_shapes(baseline, observed)
        assert len(changes) == 1
        assert changes[0].change_type == DriftChangeType.TYPE_NARROWED
        assert changes[0].severity == DriftSeverity.MANUAL


class TestTypeChangedBreaking:
    def test_type_changed_breaking(self):
        baseline = _build_shape(
            {".x": {"types_seen": ["string"]}}
        )
        observed = _build_shape(
            {".x": {"types_seen": ["integer"]}}
        )

        changes = diff_shapes(baseline, observed)
        assert len(changes) == 1
        assert changes[0].change_type == DriftChangeType.TYPE_CHANGED_BREAKING
        assert changes[0].severity == DriftSeverity.MANUAL


class TestRootTypeChanged:
    def test_root_type_changed(self):
        baseline = _build_shape(
            {"": {"types_seen": ["object"], "object_keys_seen": ["id"]}}
        )
        observed = _build_shape(
            {"": {"types_seen": ["array"], "array_item_types_seen": ["object"]}}
        )

        changes = diff_shapes(baseline, observed)
        assert len(changes) == 1
        assert changes[0].change_type == DriftChangeType.ROOT_TYPE_CHANGED
        assert changes[0].severity == DriftSeverity.MANUAL


# ---------------------------------------------------------------------------
# Nullability
# ---------------------------------------------------------------------------


class TestNullabilityChanged:
    def test_nullable_changed(self):
        baseline = _build_shape(
            {".x": {"types_seen": ["string"], "nullable": False}}
        )
        observed = _build_shape(
            {".x": {"types_seen": ["string", "null"], "nullable": True}}
        )

        changes = diff_shapes(baseline, observed)
        # Should have both: nullability change (always reported)
        nullability_changes = [
            c for c in changes if c.change_type == DriftChangeType.NULLABILITY_CHANGED
        ]
        assert len(nullability_changes) == 1
        assert nullability_changes[0].severity == DriftSeverity.APPROVAL_REQUIRED


# ---------------------------------------------------------------------------
# Array item type changes
# ---------------------------------------------------------------------------


class TestArrayItemTypeChanged:
    def test_array_item_type_changed(self):
        baseline = _build_shape(
            {".items": {"types_seen": ["array"], "array_item_types_seen": ["string"]}}
        )
        observed = _build_shape(
            {
                ".items": {
                    "types_seen": ["array"],
                    "array_item_types_seen": ["string", "integer"],
                }
            }
        )

        changes = diff_shapes(baseline, observed)
        item_type_changes = [
            c for c in changes if c.change_type == DriftChangeType.ARRAY_ITEM_TYPE_CHANGED
        ]
        assert len(item_type_changes) == 1
        assert item_type_changes[0].severity == DriftSeverity.APPROVAL_REQUIRED


# ---------------------------------------------------------------------------
# Missing paths (presence-based)
# ---------------------------------------------------------------------------


class TestRequiredPathMissing:
    def test_required_path_missing(self):
        baseline = _build_shape(
            {".x": {"types_seen": ["string"], "seen_count": 20, "sample_count": 20}},
            sample_count=20,
        )
        observed = _build_shape({}, sample_count=1)

        changes = diff_shapes(baseline, observed)
        assert len(changes) == 1
        assert changes[0].change_type == DriftChangeType.REQUIRED_PATH_MISSING
        assert changes[0].severity == DriftSeverity.MANUAL


class TestOptionalPathMissing:
    def test_optional_path_missing(self):
        baseline = _build_shape(
            {".x": {"types_seen": ["string"], "seen_count": 5, "sample_count": 10}},
            sample_count=10,
        )
        observed = _build_shape({}, sample_count=1)

        changes = diff_shapes(baseline, observed)
        assert len(changes) == 1
        assert changes[0].change_type == DriftChangeType.OPTIONAL_KEY_REMOVED
        assert changes[0].severity == DriftSeverity.APPROVAL_REQUIRED


class TestEffectivelyRequiredThreshold:
    def test_effectively_required_threshold(self):
        # 94% -> optional
        baseline_94 = _build_shape(
            {".x": {"types_seen": ["string"], "seen_count": 94, "sample_count": 100}},
            sample_count=100,
        )
        changes_94 = diff_shapes(baseline_94, _build_shape({}))
        assert changes_94[0].change_type == DriftChangeType.OPTIONAL_KEY_REMOVED

        # 96% -> required
        baseline_96 = _build_shape(
            {".x": {"types_seen": ["string"], "seen_count": 96, "sample_count": 100}},
            sample_count=100,
        )
        changes_96 = diff_shapes(baseline_96, _build_shape({}))
        assert changes_96[0].change_type == DriftChangeType.REQUIRED_PATH_MISSING


class TestLowSampleCountNeverRequired:
    def test_low_sample_count_never_required(self):
        """1/1 samples (100%) but below MIN_SAMPLES -> APPROVAL_REQUIRED, not MANUAL."""
        baseline = _build_shape(
            {".x": {"types_seen": ["string"], "seen_count": 1, "sample_count": 1}},
            sample_count=1,
        )
        observed = _build_shape({}, sample_count=1)

        changes = diff_shapes(baseline, observed)
        assert len(changes) == 1
        # Not enough samples to claim "required"
        assert changes[0].change_type == DriftChangeType.OPTIONAL_KEY_REMOVED
        assert changes[0].severity == DriftSeverity.APPROVAL_REQUIRED


class TestMinSamplesThreshold:
    def test_min_samples_threshold(self):
        """At exactly MIN_SAMPLES with 100% presence -> MANUAL."""
        n = MIN_SAMPLES_FOR_PRESENCE
        baseline = _build_shape(
            {".x": {"types_seen": ["string"], "seen_count": n, "sample_count": n}},
            sample_count=n,
        )
        observed = _build_shape({}, sample_count=1)

        changes = diff_shapes(baseline, observed)
        assert changes[0].change_type == DriftChangeType.REQUIRED_PATH_MISSING
        assert changes[0].severity == DriftSeverity.MANUAL


# ---------------------------------------------------------------------------
# Overall severity
# ---------------------------------------------------------------------------


class TestOverallSeveritySafe:
    def test_overall_severity_safe(self):
        from toolwright.core.drift.shape_diff import DriftChange

        changes = [
            DriftChange(
                path=".x",
                change_type=DriftChangeType.FIELD_ADDED,
                severity=DriftSeverity.SAFE,
                description="test",
                baseline_value=None,
                observed_value=None,
            )
        ]
        assert overall_severity(changes) == DriftSeverity.SAFE


class TestOverallSeverityEscalates:
    def test_overall_severity_escalates(self):
        from toolwright.core.drift.shape_diff import DriftChange

        changes = [
            DriftChange(
                path=".x",
                change_type=DriftChangeType.FIELD_ADDED,
                severity=DriftSeverity.SAFE,
                description="safe",
                baseline_value=None,
                observed_value=None,
            ),
            DriftChange(
                path=".y",
                change_type=DriftChangeType.REQUIRED_PATH_MISSING,
                severity=DriftSeverity.MANUAL,
                description="manual",
                baseline_value=None,
                observed_value=None,
            ),
        ]
        assert overall_severity(changes) == DriftSeverity.MANUAL

    def test_overall_severity_empty(self):
        assert overall_severity([]) is None


class TestMultipleChanges:
    def test_multiple_changes(self):
        baseline = _build_shape(
            {
                "": {"types_seen": ["object"], "object_keys_seen": ["a", "b"]},
                ".a": {"types_seen": ["string"]},
                ".b": {"types_seen": ["integer"], "seen_count": 10, "sample_count": 10},
            }
        )
        observed = _build_shape(
            {
                "": {"types_seen": ["object"], "object_keys_seen": ["a", "c"]},
                ".a": {"types_seen": ["string", "null"], "nullable": True},
                ".c": {"types_seen": ["boolean"]},
            }
        )

        changes = diff_shapes(baseline, observed)
        types = {c.change_type for c in changes}

        assert DriftChangeType.FIELD_ADDED in types  # .c
        assert DriftChangeType.NULLABILITY_CHANGED in types  # .a became nullable
        assert DriftChangeType.REQUIRED_PATH_MISSING in types  # .b disappeared


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestDoesNotMutateBaseline:
    def test_does_not_mutate_baseline(self):
        baseline = _build_shape(
            {".x": {"types_seen": ["string"], "seen_count": 10, "sample_count": 10}}
        )
        baseline_copy = copy.deepcopy(baseline)

        observed = _build_shape(
            {".x": {"types_seen": ["integer"]}, ".y": {"types_seen": ["boolean"]}}
        )

        diff_shapes(baseline, observed)

        # Baseline should be unchanged
        assert baseline.fields.keys() == baseline_copy.fields.keys()
        for path in baseline.fields:
            assert baseline.fields[path].types_seen == baseline_copy.fields[path].types_seen


class TestDoesNotMutateObserved:
    def test_does_not_mutate_observed(self):
        baseline = _build_shape(
            {".x": {"types_seen": ["string"]}}
        )
        observed = _build_shape(
            {".x": {"types_seen": ["integer"]}, ".y": {"types_seen": ["boolean"]}}
        )
        observed_copy = copy.deepcopy(observed)

        diff_shapes(baseline, observed)

        assert observed.fields.keys() == observed_copy.fields.keys()


# ---------------------------------------------------------------------------
# Empty array handling
# ---------------------------------------------------------------------------


class TestEmptyArraySkipsRequiredPathMissing:
    def test_empty_array_skips_required_path_missing(self):
        baseline = _build_shape(
            {
                ".items": {
                    "types_seen": ["array"],
                    "array_item_types_seen": ["object"],
                    "seen_count": 10,
                    "sample_count": 10,
                },
                ".items[]": {
                    "types_seen": ["object"],
                    "object_keys_seen": ["id"],
                    "seen_count": 10,
                    "sample_count": 10,
                },
                ".items[].id": {
                    "types_seen": ["integer"],
                    "seen_count": 10,
                    "sample_count": 10,
                },
            }
        )
        observed = _build_shape(
            {
                ".items": {
                    "types_seen": ["array"],
                    "array_item_types_seen": [],
                },
            }
        )
        meta = InferenceMetadata(empty_array_paths={".items"})

        changes = diff_shapes(baseline, observed, inference_metadata=meta)

        # .items[] and .items[].id should NOT be reported as REQUIRED_PATH_MISSING
        missing_changes = [
            c for c in changes if c.change_type == DriftChangeType.REQUIRED_PATH_MISSING
        ]
        assert len(missing_changes) == 0


class TestEmptyArraySkipsItemNode:
    def test_empty_array_skips_item_node(self):
        baseline = _build_shape(
            {
                ".items[]": {
                    "types_seen": ["object"],
                    "object_keys_seen": ["id"],
                    "seen_count": 10,
                    "sample_count": 10,
                },
            }
        )
        observed = _build_shape({})
        meta = InferenceMetadata(empty_array_paths={".items"})

        changes = diff_shapes(baseline, observed, inference_metadata=meta)
        assert len(changes) == 0


class TestEmptyArraySkipsItemTypeChanged:
    def test_empty_array_skips_item_type_changed(self):
        baseline = _build_shape(
            {
                ".items": {
                    "types_seen": ["array"],
                    "array_item_types_seen": ["object"],
                },
            }
        )
        observed = _build_shape(
            {
                ".items": {
                    "types_seen": ["array"],
                    "array_item_types_seen": [],
                },
            }
        )
        meta = InferenceMetadata(empty_array_paths={".items"})

        changes = diff_shapes(baseline, observed, inference_metadata=meta)

        item_type_changes = [
            c for c in changes if c.change_type == DriftChangeType.ARRAY_ITEM_TYPE_CHANGED
        ]
        assert len(item_type_changes) == 0


# ---------------------------------------------------------------------------
# Truncated array handling
# ---------------------------------------------------------------------------


class TestTruncatedArraySkipsMissingChildren:
    def test_truncated_array_skips_missing_children(self):
        baseline = _build_shape(
            {
                ".items[].rare": {
                    "types_seen": ["string"],
                    "seen_count": 10,
                    "sample_count": 10,
                },
            }
        )
        observed = _build_shape({})
        meta = InferenceMetadata(truncated_array_paths={".items"})

        changes = diff_shapes(baseline, observed, inference_metadata=meta)
        assert len(changes) == 0


class TestTruncatedArraySkipsItemTypeChanged:
    def test_truncated_array_skips_item_type_changed(self):
        baseline = _build_shape(
            {
                ".items": {
                    "types_seen": ["array"],
                    "array_item_types_seen": ["object", "string"],
                },
            }
        )
        observed = _build_shape(
            {
                ".items": {
                    "types_seen": ["array"],
                    "array_item_types_seen": ["object"],
                },
            }
        )
        meta = InferenceMetadata(truncated_array_paths={".items"})

        changes = diff_shapes(baseline, observed, inference_metadata=meta)
        item_type_changes = [
            c for c in changes if c.change_type == DriftChangeType.ARRAY_ITEM_TYPE_CHANGED
        ]
        assert len(item_type_changes) == 0


class TestTruncatedArraySkipsTypeNarrowing:
    def test_truncated_array_skips_type_narrowing(self):
        baseline = _build_shape(
            {
                ".items[].value": {
                    "types_seen": ["string", "integer"],
                    "seen_count": 10,
                    "sample_count": 10,
                },
            }
        )
        observed = _build_shape(
            {
                ".items[].value": {
                    "types_seen": ["string"],
                },
            }
        )
        meta = InferenceMetadata(truncated_array_paths={".items"})

        changes = diff_shapes(baseline, observed, inference_metadata=meta)
        narrowing = [c for c in changes if c.change_type == DriftChangeType.TYPE_NARROWED]
        assert len(narrowing) == 0


class TestTruncatedArraySkipsNullabilityChange:
    def test_truncated_array_skips_nullability_change(self):
        baseline = _build_shape(
            {
                ".items[].x": {
                    "types_seen": ["string"],
                    "nullable": False,
                },
            }
        )
        observed = _build_shape(
            {
                ".items[].x": {
                    "types_seen": ["string", "null"],
                    "nullable": True,
                },
            }
        )
        meta = InferenceMetadata(truncated_array_paths={".items"})

        changes = diff_shapes(baseline, observed, inference_metadata=meta)
        nullability_changes = [
            c for c in changes if c.change_type == DriftChangeType.NULLABILITY_CHANGED
        ]
        assert len(nullability_changes) == 0


class TestTruncatedArrayAllowsFieldAdded:
    def test_truncated_array_allows_field_added(self):
        baseline = _build_shape({})
        observed = _build_shape(
            {".items[].new_field": {"types_seen": ["string"]}}
        )
        meta = InferenceMetadata(truncated_array_paths={".items"})

        changes = diff_shapes(baseline, observed, inference_metadata=meta)
        assert len(changes) == 1
        assert changes[0].change_type == DriftChangeType.FIELD_ADDED
        assert changes[0].severity == DriftSeverity.SAFE


class TestNonEmptyNonTruncatedStillDetects:
    def test_non_empty_non_truncated_still_detects(self):
        baseline = _build_shape(
            {
                ".items[].id": {
                    "types_seen": ["integer"],
                    "seen_count": 10,
                    "sample_count": 10,
                },
            }
        )
        observed = _build_shape({})
        meta = InferenceMetadata()  # no empty/truncated arrays

        changes = diff_shapes(baseline, observed, inference_metadata=meta)
        assert len(changes) == 1
        assert changes[0].change_type == DriftChangeType.REQUIRED_PATH_MISSING


class TestEmptyArrayParentNotSkipped:
    def test_empty_array_parent_not_skipped(self):
        """.items itself (the array node) is NOT skipped, only its descendants."""
        baseline = _build_shape(
            {
                ".items": {
                    "types_seen": ["array"],
                    "array_item_types_seen": ["object"],
                    "seen_count": 10,
                    "sample_count": 10,
                },
                ".items[]": {
                    "types_seen": ["object"],
                    "seen_count": 10,
                    "sample_count": 10,
                },
            }
        )
        observed = _build_shape(
            {
                ".items": {
                    "types_seen": ["array"],
                    "array_item_types_seen": [],
                },
            }
        )
        meta = InferenceMetadata(empty_array_paths={".items"})

        changes = diff_shapes(baseline, observed, inference_metadata=meta)

        # .items itself should still be present and compared
        # .items[] should be skipped (child of empty array)
        [c for c in changes if c.path == ".items"]
        items_bracket_changes = [c for c in changes if c.path == ".items[]"]
        assert len(items_bracket_changes) == 0  # skipped


# ---------------------------------------------------------------------------
# _is_safe_widening
# ---------------------------------------------------------------------------


class TestIsSafeWidening:
    def test_int_to_number_is_safe(self):
        assert _is_safe_widening({"integer"}, {"integer", "number"}) is True

    def test_int_to_string_is_not_safe(self):
        assert _is_safe_widening({"integer"}, {"integer", "string"}) is False

    def test_string_to_number_is_not_safe(self):
        assert _is_safe_widening({"string"}, {"string", "number"}) is False

    def test_not_strict_superset(self):
        assert _is_safe_widening({"integer"}, {"integer"}) is False

    def test_multi_type_widening(self):
        assert (
            _is_safe_widening(
                {"integer", "string"}, {"integer", "string", "number"}
            )
            is True
        )

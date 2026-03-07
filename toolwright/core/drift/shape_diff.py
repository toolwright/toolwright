"""Shape diffing algorithm for traffic-captured tool drift detection.

Compares a baseline ShapeModel against a newly observed ShapeModel
and produces a list of classified changes with severity levels.

Critical rule: decide first, then merge.
The baseline is NOT mutated. The caller decides whether to merge
based on the classification results.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from toolwright.core.drift.constants import (
    EFFECTIVELY_REQUIRED_THRESHOLD,
    MIN_SAMPLES_FOR_PRESENCE,
)
from toolwright.core.drift.shape_inference import InferenceMetadata
from toolwright.models.shape import ShapeModel


class DriftSeverity(Enum):
    """Severity of a drift change."""

    SAFE = "safe"  # auto-merge OK
    APPROVAL_REQUIRED = "approval_required"  # present diff, wait for approval
    MANUAL = "manual"  # flag for human review


class DriftChangeType(Enum):
    """Type of structural change detected."""

    # SAFE
    FIELD_ADDED = "field_added"
    OPTIONAL_PATH_ADDED = "optional_path_added"
    TYPE_WIDENED_SAFE = "type_widened_safe"

    # APPROVAL_REQUIRED
    NULLABILITY_CHANGED = "nullability_changed"
    ARRAY_ITEM_TYPE_CHANGED = "array_item_type_changed"
    OPTIONAL_KEY_REMOVED = "optional_key_removed"

    # MANUAL
    REQUIRED_PATH_MISSING = "required_path_missing"
    TYPE_NARROWED = "type_narrowed"
    TYPE_CHANGED_BREAKING = "type_changed_breaking"
    ROOT_TYPE_CHANGED = "root_type_changed"


@dataclass
class DriftChange:
    """A single classified change between baseline and observed shapes."""

    path: str
    change_type: DriftChangeType
    severity: DriftSeverity
    description: str
    baseline_value: str | None
    observed_value: str | None


# Safe type widenings: the ONLY type changes classified as SAFE.
SAFE_WIDENINGS: set[tuple[str, str]] = {
    ("integer", "number"),  # int -> float is safe
}


def _is_safe_widening(old_types: set[str], new_types: set[str]) -> bool:
    """Check if the type change from old_types to new_types is a safe widening.

    Safe widening means:
    - new_types is a strict superset of old_types
    - every type in (new_types - old_types) is reachable via SAFE_WIDENINGS
      from some type in old_types
    """
    if not (old_types < new_types):  # must be strict subset
        return False

    added_types = new_types - old_types
    for added in added_types:
        if not any(
            (existing, added) in SAFE_WIDENINGS for existing in old_types
        ):
            return False
    return True


def diff_shapes(
    baseline: ShapeModel,
    observed: ShapeModel,
    effectively_required_threshold: float = EFFECTIVELY_REQUIRED_THRESHOLD,
    inference_metadata: InferenceMetadata | None = None,
) -> list[DriftChange]:
    """Diff a baseline ShapeModel against a newly observed ShapeModel.

    Returns a list of DriftChange items, classified by severity.

    CRITICAL: This function does NOT mutate either model.
    The caller decides whether to merge based on the results.

    If inference_metadata is provided, paths that are descendants of
    empty or truncated arrays in the observed sample are treated as
    "unknown" rather than "missing."
    """
    changes: list[DriftChange] = []
    meta = inference_metadata or InferenceMetadata()

    def _is_under_empty_array(path: str) -> bool:
        """Path is a descendant of an empty array (children unknown)."""
        return any(
            path.startswith(arr + "[]") for arr in meta.empty_array_paths
        )

    def _is_under_truncated_array(path: str) -> bool:
        """Path is a descendant of a truncated array (shape may be partial)."""
        return any(
            path.startswith(arr + "[]") for arr in meta.truncated_array_paths
        )

    all_paths = set(baseline.fields.keys()) | set(observed.fields.keys())

    for path in sorted(all_paths):
        b_field = baseline.fields.get(path)
        o_field = observed.fields.get(path)

        # --- Path present in observed but not in baseline ---
        # Always report FIELD_ADDED (even under truncated arrays —
        # new fields are real discoveries, not sampling artifacts)
        if b_field is None and o_field is not None:
            changes.append(
                DriftChange(
                    path=path,
                    change_type=DriftChangeType.FIELD_ADDED,
                    severity=DriftSeverity.SAFE,
                    description=f"New path appeared: {path} (type: {o_field.types_seen})",
                    baseline_value=None,
                    observed_value=str(o_field.types_seen),
                )
            )
            continue

        # --- Path present in baseline but not in observed ---
        if b_field is not None and o_field is None:
            # If this path is under an empty or truncated array,
            # its absence is expected — skip classification entirely
            if _is_under_empty_array(path) or _is_under_truncated_array(path):
                continue

            has_enough_samples = (
                b_field.sample_count >= MIN_SAMPLES_FOR_PRESENCE
            )
            is_required = has_enough_samples and b_field.is_effectively_required(
                effectively_required_threshold
            )

            if is_required:
                changes.append(
                    DriftChange(
                        path=path,
                        change_type=DriftChangeType.REQUIRED_PATH_MISSING,
                        severity=DriftSeverity.MANUAL,
                        description=(
                            f"Effectively-required path missing: {path} "
                            f"(was present in {b_field.seen_count}/{b_field.sample_count} samples)"
                        ),
                        baseline_value=str(b_field.types_seen),
                        observed_value=None,
                    )
                )
            else:
                changes.append(
                    DriftChange(
                        path=path,
                        change_type=DriftChangeType.OPTIONAL_KEY_REMOVED,
                        severity=DriftSeverity.APPROVAL_REQUIRED,
                        description=(
                            f"Optional path absent: {path} "
                            f"(was present in {b_field.seen_count}/{b_field.sample_count} samples)"
                        ),
                        baseline_value=str(b_field.types_seen),
                        observed_value=None,
                    )
                )
            continue

        # --- Both present: compare field shapes ---
        assert b_field is not None and o_field is not None

        # Under truncated arrays, the observed shape may be a subset.
        # Only FIELD_ADDED (handled above) is reliable under truncation.
        if _is_under_truncated_array(path):
            continue

        # Check root type change
        if path == "" and b_field.types_seen != o_field.types_seen:
            b_types = b_field.types_seen - {"null"}
            o_types = o_field.types_seen - {"null"}
            if b_types != o_types:
                changes.append(
                    DriftChange(
                        path=path,
                        change_type=DriftChangeType.ROOT_TYPE_CHANGED,
                        severity=DriftSeverity.MANUAL,
                        description=(
                            f"Root type changed from {b_field.types_seen} "
                            f"to {o_field.types_seen}"
                        ),
                        baseline_value=str(b_field.types_seen),
                        observed_value=str(o_field.types_seen),
                    )
                )
                continue

        # Type changes (non-root)
        if b_field.types_seen != o_field.types_seen:
            b_non_null = b_field.types_seen - {"null"}
            o_non_null = o_field.types_seen - {"null"}

            if b_non_null == o_non_null:
                # Only nullability changed — handled below
                pass
            elif _is_safe_widening(b_non_null, o_non_null):
                changes.append(
                    DriftChange(
                        path=path,
                        change_type=DriftChangeType.TYPE_WIDENED_SAFE,
                        severity=DriftSeverity.SAFE,
                        description=(
                            f"Type safely widened at {path}: "
                            f"{b_field.types_seen} -> {o_field.types_seen}"
                        ),
                        baseline_value=str(b_field.types_seen),
                        observed_value=str(o_field.types_seen),
                    )
                )
            elif b_non_null > o_non_null:
                # Types narrowed (strict superset -> subset)
                changes.append(
                    DriftChange(
                        path=path,
                        change_type=DriftChangeType.TYPE_NARROWED,
                        severity=DriftSeverity.MANUAL,
                        description=(
                            f"Type narrowed at {path}: "
                            f"{b_field.types_seen} -> {o_field.types_seen}"
                        ),
                        baseline_value=str(b_field.types_seen),
                        observed_value=str(o_field.types_seen),
                    )
                )
            else:
                # Any other type change — incompatible
                changes.append(
                    DriftChange(
                        path=path,
                        change_type=DriftChangeType.TYPE_CHANGED_BREAKING,
                        severity=DriftSeverity.MANUAL,
                        description=(
                            f"Type changed at {path}: "
                            f"{b_field.types_seen} -> {o_field.types_seen}"
                        ),
                        baseline_value=str(b_field.types_seen),
                        observed_value=str(o_field.types_seen),
                    )
                )

        # Nullability change (non-null -> nullable)
        if not b_field.nullable and o_field.nullable:
            changes.append(
                DriftChange(
                    path=path,
                    change_type=DriftChangeType.NULLABILITY_CHANGED,
                    severity=DriftSeverity.APPROVAL_REQUIRED,
                    description=f"Field became nullable at {path}",
                    baseline_value="non-null",
                    observed_value="nullable",
                )
            )

        # Array item type changes
        # Skip for empty arrays and truncated arrays
        if (
            b_field.array_item_types_seen is not None
            and o_field.array_item_types_seen is not None
        ):
            if (
                path not in meta.empty_array_paths
                and path not in meta.truncated_array_paths
            ):
                if (
                    b_field.array_item_types_seen
                    != o_field.array_item_types_seen
                ):
                    changes.append(
                        DriftChange(
                            path=path,
                            change_type=DriftChangeType.ARRAY_ITEM_TYPE_CHANGED,
                            severity=DriftSeverity.APPROVAL_REQUIRED,
                            description=(
                                f"Array item types changed at {path}: "
                                f"{b_field.array_item_types_seen} -> "
                                f"{o_field.array_item_types_seen}"
                            ),
                            baseline_value=str(b_field.array_item_types_seen),
                            observed_value=str(o_field.array_item_types_seen),
                        )
                    )

    return changes


def overall_severity(changes: list[DriftChange]) -> DriftSeverity | None:
    """Return the highest severity from a list of changes, or None if empty."""
    if not changes:
        return None
    if any(c.severity == DriftSeverity.MANUAL for c in changes):
        return DriftSeverity.MANUAL
    if any(c.severity == DriftSeverity.APPROVAL_REQUIRED for c in changes):
        return DriftSeverity.APPROVAL_REQUIRED
    return DriftSeverity.SAFE

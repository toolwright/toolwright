"""Shape inference engine for traffic-captured tool drift detection.

Converts JSON response bodies into ShapeModel instances and merges
new observations into existing models. This is the foundation for
detecting structural drift in API responses.

Key invariants:
- _walk() only populates structural info (types, keys, nullability).
  It NEVER touches seen_count or sample_count.
- Presence counting is per-sample and happens only in merge_observation().
- Array elements do not inflate presence — an array with 100 items
  counts as "path was present in 1 sample."
- All merges (compile-time, SAFE drift, approved drift) go through
  merge_observation(). There is no separate merge implementation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from toolwright.models.shape import FieldShape, ShapeModel

logger = logging.getLogger("toolwright.drift")

MAX_WALK_DEPTH = 32
MAX_ARRAY_ITEMS_PER_SAMPLE = 50


@dataclass
class InferenceMetadata:
    """Per-observation metadata that affects how diffs should be interpreted.

    These are properties of a single observation, NOT accumulated into
    the baseline. They tell diff_shapes which paths are "unknown"
    (rather than "missing") in this particular sample.
    """

    empty_array_paths: set[str] = field(default_factory=set)
    """Array paths where len(node) == 0. Children are unknown, not missing."""

    truncated_array_paths: set[str] = field(default_factory=set)
    """Array paths where len(node) > MAX_ARRAY_ITEMS_PER_SAMPLE.
    Child paths may be incomplete — fields that only appear in later
    items won't be observed."""


def infer_shape(body: Any) -> tuple[ShapeModel, InferenceMetadata]:
    """Infer a ShapeModel from a single JSON response body.

    Returns:
        (ShapeModel, InferenceMetadata) — the shape model contains
        structural info only (types_seen, nullable, object_keys_seen,
        array_item_types_seen). Presence stats (seen_count, sample_count)
        are all zero — they are populated by merge_observation().

        The InferenceMetadata tracks empty and truncated arrays so that
        diff_shapes can distinguish "children are unknown" from
        "children are missing."

    For the first sample, use merge_observation() on an empty ShapeModel.
    """
    model = ShapeModel(
        sample_count=0,  # NOT 1 — presence stats set by merge_observation
        last_updated=datetime.now(UTC).isoformat(),
    )
    metadata = InferenceMetadata()
    _walk(body, "", model, metadata, depth=0)
    return model, metadata


def _walk(
    node: Any,
    path: str,
    model: ShapeModel,
    metadata: InferenceMetadata,
    depth: int,
) -> None:
    """Recursively walk a JSON value and populate structural shape info.

    DOES NOT touch seen_count or sample_count. Those are per-sample
    counters managed by merge_observation().

    For arrays: always recurses each item at path[], which naturally
    creates item-level FieldShape nodes. Nested arrays compose:
    path[] -> path[][] -> path[][][] with no special cases.
    """
    if depth > MAX_WALK_DEPTH:
        return

    json_type = _json_type(node)

    if path not in model.fields:
        model.fields[path] = FieldShape(
            types_seen=set(),
            nullable=False,
            seen_count=0,  # set by merge_observation
            sample_count=0,  # set by merge_observation
        )

    fs = model.fields[path]
    fs.types_seen.add(json_type)
    fs.nullable = fs.nullable or (json_type == "null")

    if json_type == "object" and isinstance(node, dict):
        if fs.object_keys_seen is None:
            fs.object_keys_seen = set()
        fs.object_keys_seen.update(node.keys())

        for key, value in node.items():
            child_path = f"{path}.{key}"
            _walk(value, child_path, model, metadata, depth + 1)

    elif json_type == "array" and isinstance(node, list):
        if fs.array_item_types_seen is None:
            fs.array_item_types_seen = set()

        if len(node) == 0:
            # Empty array: children are unknown, not missing
            metadata.empty_array_paths.add(path)
            return

        items_to_inspect = node[:MAX_ARRAY_ITEMS_PER_SAMPLE]
        if len(node) > MAX_ARRAY_ITEMS_PER_SAMPLE:
            metadata.truncated_array_paths.add(path)
            logger.debug(
                "Array at %s has %d items, inspecting first %d for shape inference",
                path,
                len(node),
                MAX_ARRAY_ITEMS_PER_SAMPLE,
            )

        for item in items_to_inspect:
            item_type = _json_type(item)
            fs.array_item_types_seen.add(item_type)
            # Always recurse at path[] — creates a FieldShape for array
            # items and lets their children recurse naturally.
            _walk(item, f"{path}[]", model, metadata, depth + 1)


def _json_type(value: Any) -> str:
    """Map a Python value to its JSON type string."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "unknown"


def merge_observation(existing: ShapeModel, body: Any) -> ShapeModel:
    """Merge a new observation into an existing ShapeModel.

    This is the single merge function. All merges go through here:
    - Compile time: multiple HAR entries for the same endpoint
    - Runtime: SAFE drift auto-merge
    - Runtime: approved drift merge
    - Phase 2: passive learning from live traffic

    Presence counting is per-sample and conditional on observability:
    - Each path gets seen_count += 1 if it appeared in this sample
    - Paths NOT observed get sample_count bumped (marking them as "absent")
    - EXCEPT paths under empty/truncated arrays, which are "unknown" —
      neither seen_count nor sample_count changes for them

    Returns the mutated existing model (also mutates in place).
    """
    existing.sample_count += 1
    existing.last_updated = datetime.now(UTC).isoformat()

    observed, meta = infer_shape(body)

    # The set of paths that appeared in this sample
    observed_paths = set(observed.fields.keys())

    # Merge structural info and increment presence for observed paths
    for path, o_field in observed.fields.items():
        if path in existing.fields:
            efs = existing.fields[path]
            # Merge structural info
            efs.types_seen |= o_field.types_seen
            efs.nullable = efs.nullable or o_field.nullable

            if o_field.object_keys_seen is not None:
                if efs.object_keys_seen is None:
                    efs.object_keys_seen = set()
                efs.object_keys_seen |= o_field.object_keys_seen

            if o_field.array_item_types_seen is not None:
                if efs.array_item_types_seen is None:
                    efs.array_item_types_seen = set()
                efs.array_item_types_seen |= o_field.array_item_types_seen

            # Presence: this path appeared in this sample
            efs.seen_count += 1
            efs.sample_count = existing.sample_count
        else:
            # New path appeared — add it with seen_count=1
            existing.fields[path] = FieldShape(
                types_seen=set(o_field.types_seen),
                nullable=o_field.nullable,
                object_keys_seen=(
                    set(o_field.object_keys_seen)
                    if o_field.object_keys_seen
                    else None
                ),
                array_item_types_seen=(
                    set(o_field.array_item_types_seen)
                    if o_field.array_item_types_seen
                    else None
                ),
                seen_count=1,
                sample_count=existing.sample_count,
            )

    # Bump sample_count for paths NOT observed in this sample.
    # Skip paths under empty/truncated arrays (unknown, not absent).
    unknowable_paths = meta.empty_array_paths | meta.truncated_array_paths

    for path, efs in existing.fields.items():
        if path not in observed_paths:
            # Check if this path is a descendant of an empty/truncated array
            if any(path.startswith(arr + "[]") for arr in unknowable_paths):
                continue  # Unknown, not absent — don't touch stats
            efs.sample_count = existing.sample_count
            # seen_count stays the same — it wasn't seen in this sample

    return existing

"""Confidence-aware schema inference for the heal system.

Aggregates typed_shape observations across stored ResponseSamples
into an InferredSchema with confidence-based optionality thresholds.

Confidence tiers (from spec Section 3):
  N < 20:   optional only if presence_rate == 0, confidence "low"
  20 <= N < 50: optional if presence_rate < 0.90, confidence "medium"
  N >= 50:  optional if presence_rate < 0.95, confidence "high"
"""

from __future__ import annotations

import hashlib
import json
import logging

from toolwright.models.heal import (
    FieldSchema,
    InferredSchema,
    PresenceConfidence,
    ResponseSample,
)

logger = logging.getLogger("toolwright.heal.schema_inference")


def infer_schema(
    tool_id: str,
    variant: str,
    samples: list[ResponseSample],
) -> InferredSchema:
    """Aggregate samples into a confidence-aware InferredSchema.

    Raises ValueError if samples is empty.
    """
    if not samples:
        raise ValueError("infer_schema requires at least one sample")

    n = len(samples)
    confidence = _confidence_tier(n)

    # Aggregate per-path: types seen, nullable, presence count
    path_data: dict[str, _PathAgg] = {}

    for sample in samples:
        observed_paths = set(sample.typed_shape.keys())
        for path, info in sample.typed_shape.items():
            if path not in path_data:
                path_data[path] = _PathAgg()
            agg = path_data[path]
            agg.types.update(info.types)
            if info.nullable:
                agg.nullable = True
            agg.seen_count += 1

        # Mark paths NOT in this sample as absent
        for path in path_data:
            if path not in observed_paths:
                pass  # seen_count not incremented — tracked by total n

    # Build FieldSchema list
    fields: dict[str, FieldSchema] = {}
    for path, agg in path_data.items():
        presence_rate = agg.seen_count / n
        optional = _is_optional(presence_rate, confidence)
        name = path.rsplit(".", 1)[-1] if "." in path else path
        observed_types = sorted(agg.types)

        # Determine field_type (primary type)
        field_type = observed_types[0] if observed_types else "unknown"

        # Collect examples from first sample that has this path
        example_values: list[str] = []
        for s in samples:
            if path in s.examples:
                example_values.append(s.examples[path])
                break

        fields[path] = FieldSchema(
            name=name,
            path=path,
            field_type=field_type,
            nullable=agg.nullable,
            optional=optional,
            presence_rate=round(presence_rate, 4),
            presence_confidence=confidence.value,
            observed_types=observed_types,
            example_values=example_values,
        )

    schema_hash = compute_schema_hash(fields)

    # Determine response type from (root)
    response_type = "unknown"
    if "(root)" in fields:
        root_types = fields["(root)"].observed_types
        if root_types:
            response_type = root_types[0]

    return InferredSchema(
        tool_id=tool_id,
        variant=variant,
        schema_hash=schema_hash,
        sample_count=n,
        first_seen=samples[0].timestamp,
        last_seen=samples[-1].timestamp,
        response_type=response_type,
        fields=fields,
    )


def compute_schema_hash(fields: dict[str, FieldSchema]) -> str:
    """SHA256 of canonicalized fields (sorted paths, sorted type lists)."""
    canonical = {}
    for path in sorted(fields.keys()):
        f = fields[path]
        canonical[path] = {
            "types": sorted(f.observed_types),
            "nullable": f.nullable,
        }
    raw = json.dumps(canonical, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _confidence_tier(n: int) -> PresenceConfidence:
    if n >= 50:
        return PresenceConfidence.HIGH
    if n >= 20:
        return PresenceConfidence.MEDIUM
    return PresenceConfidence.LOW


def _is_optional(
    presence_rate: float, confidence: PresenceConfidence,
) -> bool:
    """Determine optionality based on confidence tier."""
    if confidence == PresenceConfidence.LOW:
        return presence_rate == 0.0
    if confidence == PresenceConfidence.MEDIUM:
        return presence_rate < 0.90
    # HIGH
    return presence_rate < 0.95


class _PathAgg:
    """Accumulator for per-path aggregation."""

    __slots__ = ("types", "nullable", "seen_count")

    def __init__(self) -> None:
        self.types: set[str] = set()
        self.nullable: bool = False
        self.seen_count: int = 0

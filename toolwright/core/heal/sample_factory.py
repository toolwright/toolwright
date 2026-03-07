"""Factory for creating ResponseSample from raw probe results."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from toolwright.core.heal.typed_shape import build_typed_shape
from toolwright.models.heal import FieldTypeInfo, ResponseSample


def create_response_sample(
    *,
    tool_id: str,
    variant: str,
    status_code: int,
    latency_ms: int,
    body: Any,
) -> ResponseSample:
    """Create a ResponseSample from a raw response body."""
    typed_shape, presence_paths, examples = build_typed_shape(body)
    schema_hash = _compute_typed_shape_hash(typed_shape)

    return ResponseSample(
        tool_id=tool_id,
        variant=variant,
        timestamp=time.time(),
        status_code=status_code,
        latency_ms=latency_ms,
        schema_hash=schema_hash,
        typed_shape=typed_shape,
        presence_paths=presence_paths,
        examples=examples,
    )


def _compute_typed_shape_hash(typed_shape: dict[str, FieldTypeInfo]) -> str:
    """SHA256 of canonicalized typed_shape (sorted paths, sorted types)."""
    canonical = {
        path: {"types": sorted(info.types), "nullable": info.nullable}
        for path, info in sorted(typed_shape.items())
    }
    raw = json.dumps(canonical, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

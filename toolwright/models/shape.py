"""Response shape models for traffic-captured tool drift detection.

The shape model is our canonical format for describing the structure
of JSON API responses. It tracks types, nullability, object keys,
array item types, and per-field presence statistics.

Fields use flat JSON pointer paths with array notation:
  ""           — root object
  ".products"  — direct child
  ".products[]" — array items
  ".products[].id" — field in array item objects
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


@dataclass
class FieldShape:
    """Shape of a single field at a JSON pointer path."""

    # Structural
    types_seen: set[str] = field(default_factory=set)
    nullable: bool = False

    # For type == "object"
    object_keys_seen: set[str] | None = None

    # For type == "array"
    array_item_types_seen: set[str] | None = None

    # Presence stats
    seen_count: int = 0
    sample_count: int = 0

    @property
    def presence_ratio(self) -> float:
        if self.sample_count == 0:
            return 0.0
        return self.seen_count / self.sample_count

    def is_effectively_required(self, threshold: float = 0.95) -> bool:
        """Field is 'effectively required' if present in >= threshold of samples."""
        return self.presence_ratio >= threshold


@dataclass
class ShapeModel:
    """Canonical shape model for an API response.

    Keys are JSON pointer paths: "", ".products", ".products[]",
    ".products[].id", ".products[].variants[]", etc.

    The root path is always "".
    """

    fields: dict[str, FieldShape] = field(default_factory=dict)
    sample_count: int = 0
    last_updated: str = ""

    def content_hash(self) -> str:
        """Deterministic hash of shape content for change detection."""
        canonical = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict for storage."""
        result: dict = {
            "sample_count": self.sample_count,
            "last_updated": self.last_updated,
            "fields": {},
        }
        for path, fs in sorted(self.fields.items()):
            entry: dict = {
                "types_seen": sorted(fs.types_seen),
                "nullable": fs.nullable,
                "seen_count": fs.seen_count,
                "sample_count": fs.sample_count,
            }
            if fs.object_keys_seen is not None:
                entry["object_keys_seen"] = sorted(fs.object_keys_seen)
            if fs.array_item_types_seen is not None:
                entry["array_item_types_seen"] = sorted(fs.array_item_types_seen)
            result["fields"][path] = entry
        return result

    @classmethod
    def from_dict(cls, data: dict) -> ShapeModel:
        """Deserialize from stored dict."""
        model = cls(
            sample_count=data.get("sample_count", 0),
            last_updated=data.get("last_updated", ""),
        )
        for path, entry in data.get("fields", {}).items():
            model.fields[path] = FieldShape(
                types_seen=set(entry["types_seen"]),
                nullable=entry["nullable"],
                object_keys_seen=(
                    set(entry["object_keys_seen"])
                    if "object_keys_seen" in entry
                    else None
                ),
                array_item_types_seen=(
                    set(entry["array_item_types_seen"])
                    if "array_item_types_seen" in entry
                    else None
                ),
                seen_count=entry.get("seen_count", 0),
                sample_count=entry.get("sample_count", 0),
            )
        return model

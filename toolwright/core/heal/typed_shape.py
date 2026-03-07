"""Typed shape builder — converts JSON bodies to heal-format typed shapes.

Produces (typed_shape, presence_paths, examples) from a raw JSON body.

Path conventions (from spec):
  (root)       — always present, type matches root value
  key          — object child (no leading dot)
  key.sub      — nested object child
  items[]      — array items
  items[].id   — field in array item objects
  []           — root-level array items
  matrix[][]   — nested array items
"""

from __future__ import annotations

from typing import Any

from toolwright.core.heal.redaction import redact_examples
from toolwright.models.heal import FieldTypeInfo

MAX_DEPTH = 32


def build_typed_shape(
    body: Any,
) -> tuple[dict[str, FieldTypeInfo], list[str], dict[str, str]]:
    """Convert a JSON body to heal-format typed shape.

    Returns:
        typed_shape: {dotted_path: FieldTypeInfo}
        presence_paths: list of all paths present
        examples: {path: first_scalar_as_string} (redacted)
    """
    typed_shape: dict[str, FieldTypeInfo] = {}
    examples_raw: dict[str, str] = {}

    _walk(body, "(root)", typed_shape, examples_raw, depth=0)

    presence_paths = list(typed_shape.keys())
    examples = redact_examples(examples_raw)

    return typed_shape, presence_paths, examples


def _walk(
    node: Any,
    path: str,
    typed_shape: dict[str, FieldTypeInfo],
    examples: dict[str, str],
    depth: int,
) -> None:
    """Recursively walk a JSON value and build typed shape entries."""
    if depth > MAX_DEPTH:
        return

    jtype = _json_type(node)

    if path not in typed_shape:
        typed_shape[path] = FieldTypeInfo(
            types=[jtype], nullable=(jtype == "null")
        )
    else:
        entry = typed_shape[path]
        if jtype not in entry.types:
            entry.types.append(jtype)
        if jtype == "null":
            entry.nullable = True

    if jtype == "object" and isinstance(node, dict):
        for key, value in node.items():
            child_path = key if path == "(root)" else f"{path}.{key}"
            _walk(value, child_path, typed_shape, examples, depth + 1)

    elif jtype == "array" and isinstance(node, list):
        if len(node) == 0:
            return
        item_path = "[]" if path == "(root)" else f"{path}[]"
        for item in node[:50]:
            _walk(item, item_path, typed_shape, examples, depth + 1)

    else:
        # Scalar — record example
        if path != "(root)" and path not in examples:
            examples[path] = _to_example_str(node)


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


def _to_example_str(value: Any) -> str:
    """Convert a scalar value to its string representation for examples."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)

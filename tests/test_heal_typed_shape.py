"""Tests for typed shape builder (JSON body → heal format)."""

from __future__ import annotations


class TestBuildTypedShape:
    def test_flat_object(self):
        from toolwright.core.heal.typed_shape import build_typed_shape

        ts, paths, examples = build_typed_shape({"id": 1, "name": "Alice"})
        assert ts["(root)"].types == ["object"]
        assert ts["id"].types == ["integer"]
        assert ts["name"].types == ["string"]
        assert "(root)" in paths
        assert "id" in paths
        assert "name" in paths

    def test_nested_object(self):
        from toolwright.core.heal.typed_shape import build_typed_shape

        ts, paths, _ = build_typed_shape({"data": {"count": 5}})
        assert ts["(root)"].types == ["object"]
        assert ts["data"].types == ["object"]
        assert ts["data.count"].types == ["integer"]

    def test_array_of_objects(self):
        from toolwright.core.heal.typed_shape import build_typed_shape

        ts, paths, _ = build_typed_shape({"items": [{"id": 1}]})
        assert ts["items"].types == ["array"]
        assert ts["items[]"].types == ["object"]
        assert ts["items[].id"].types == ["integer"]

    def test_root_array(self):
        from toolwright.core.heal.typed_shape import build_typed_shape

        ts, paths, _ = build_typed_shape([{"id": 1}])
        assert ts["(root)"].types == ["array"]
        assert ts["[]"].types == ["object"]
        assert ts["[].id"].types == ["integer"]

    def test_null_value(self):
        from toolwright.core.heal.typed_shape import build_typed_shape

        ts, _, _ = build_typed_shape({"x": None})
        assert ts["x"].types == ["null"]
        assert ts["x"].nullable is True

    def test_nested_array(self):
        from toolwright.core.heal.typed_shape import build_typed_shape

        ts, _, _ = build_typed_shape({"matrix": [[1, 2]]})
        assert ts["matrix"].types == ["array"]
        assert ts["matrix[]"].types == ["array"]
        assert ts["matrix[][]"].types == ["integer"]

    def test_root_always_present(self):
        from toolwright.core.heal.typed_shape import build_typed_shape

        for body in [{"a": 1}, [1, 2], "hello", 42, None, True]:
            ts, paths, _ = build_typed_shape(body)
            assert "(root)" in ts, f"(root) missing for body type {type(body)}"
            assert "(root)" in paths

    def test_presence_paths_complete(self):
        from toolwright.core.heal.typed_shape import build_typed_shape

        ts, paths, _ = build_typed_shape({"a": {"b": 1}, "c": [2]})
        expected = {"(root)", "a", "a.b", "c", "c[]"}
        assert set(paths) == expected

    def test_examples_extraction(self):
        from toolwright.core.heal.typed_shape import build_typed_shape

        _, _, examples = build_typed_shape({"id": "cus_123", "count": 42})
        assert examples["id"] == "cus_123"
        assert examples["count"] == "42"

    def test_examples_redacted(self):
        from toolwright.core.heal.typed_shape import build_typed_shape

        _, _, examples = build_typed_shape({"api_key": "secret123", "name": "Alice"})
        assert examples["api_key"] == "[REDACTED]"
        assert examples["name"] == "Alice"

    def test_examples_only_scalars(self):
        """Objects and arrays should not appear in examples."""
        from toolwright.core.heal.typed_shape import build_typed_shape

        _, _, examples = build_typed_shape({"data": {"nested": "val"}, "items": [1]})
        assert "data" not in examples
        assert "items" not in examples
        assert "data.nested" in examples

    def test_boolean_value(self):
        from toolwright.core.heal.typed_shape import build_typed_shape

        ts, _, examples = build_typed_shape({"active": True})
        assert ts["active"].types == ["boolean"]
        assert examples["active"] == "true"

    def test_float_value(self):
        from toolwright.core.heal.typed_shape import build_typed_shape

        ts, _, _ = build_typed_shape({"price": 9.99})
        assert ts["price"].types == ["number"]

    def test_empty_object(self):
        from toolwright.core.heal.typed_shape import build_typed_shape

        ts, paths, _ = build_typed_shape({})
        assert ts["(root)"].types == ["object"]
        assert paths == ["(root)"]

    def test_empty_array(self):
        from toolwright.core.heal.typed_shape import build_typed_shape

        ts, paths, _ = build_typed_shape([])
        assert ts["(root)"].types == ["array"]
        assert paths == ["(root)"]

    def test_no_leading_dot_on_paths(self):
        """Heal format uses 'key' not '.key' for object children."""
        from toolwright.core.heal.typed_shape import build_typed_shape

        ts, paths, _ = build_typed_shape({"name": "x"})
        assert "name" in ts
        assert ".name" not in ts
        for p in paths:
            assert not p.startswith("."), f"Path {p!r} starts with dot"

    def test_depth_limit(self):
        """Deeply nested structures stop at MAX_DEPTH."""
        from toolwright.core.heal.typed_shape import build_typed_shape

        body: dict = {"a": None}
        current = body
        for _ in range(40):
            inner: dict = {"a": None}
            current["a"] = inner
            current = inner
        ts, _, _ = build_typed_shape(body)
        # Should not crash; paths are bounded
        assert "(root)" in ts

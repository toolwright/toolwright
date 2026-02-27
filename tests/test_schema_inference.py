"""Tests for schema inference quality in EndpointAggregator."""

from toolwright.core.normalize.aggregator import EndpointAggregator


class TestInferSchema:
    """Tests for _infer_schema multi-sample merge."""

    def setup_method(self):
        self.agg = EndpointAggregator()

    def test_single_sample(self):
        """Single sample should produce correct schema."""
        samples = [{"name": "Alice", "age": 30}]
        schema = self.agg._infer_schema(samples)

        assert schema["type"] == "object"
        assert schema["properties"]["name"] == {"type": "string"}
        assert schema["properties"]["age"] == {"type": "integer"}

    def test_required_computed_from_field_presence(self):
        """Fields present in all samples should be required."""
        samples = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
            {"name": "Charlie"},  # age missing
        ]
        schema = self.agg._infer_schema(samples)

        assert "required" in schema
        assert "name" in schema["required"]
        assert "age" not in schema["required"]

    def test_all_fields_present_are_required(self):
        """When all samples have the same fields, all are required."""
        samples = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
        schema = self.agg._infer_schema(samples)

        assert set(schema["required"]) == {"id", "name"}

    def test_mixed_types_produce_oneof(self):
        """Fields with mixed types across samples should emit oneOf."""
        samples = [
            {"value": 42},
            {"value": "hello"},
        ]
        schema = self.agg._infer_schema(samples)

        prop = schema["properties"]["value"]
        assert "oneOf" in prop
        types = {item["type"] for item in prop["oneOf"]}
        assert types == {"integer", "string"}

    def test_consistent_types_no_oneof(self):
        """Fields with consistent types should not emit oneOf."""
        samples = [
            {"value": 1},
            {"value": 2},
            {"value": 3},
        ]
        schema = self.agg._infer_schema(samples)

        assert schema["properties"]["value"] == {"type": "integer"}

    def test_nullable_field_produces_oneof_with_null(self):
        """Field that is sometimes null should emit oneOf with null."""
        samples = [
            {"value": "hello"},
            {"value": None},
        ]
        schema = self.agg._infer_schema(samples)

        prop = schema["properties"]["value"]
        assert "oneOf" in prop
        types = {item["type"] for item in prop["oneOf"]}
        assert types == {"string", "null"}

    def test_array_items_from_all_elements(self):
        """Array items schema should be inferred from all elements."""
        samples = [
            {"tags": ["a", "b"]},
            {"tags": ["c", "d", "e"]},
        ]
        schema = self.agg._infer_schema(samples)

        arr = schema["properties"]["tags"]
        assert arr["type"] == "array"
        assert arr["items"] == {"type": "string"}

    def test_array_mixed_element_types(self):
        """Array with mixed element types should emit oneOf in items."""
        samples = [
            {"data": [1, "two", 3]},
        ]
        schema = self.agg._infer_schema(samples)

        arr = schema["properties"]["data"]
        assert arr["type"] == "array"
        assert "oneOf" in arr["items"]
        types = {item["type"] for item in arr["items"]["oneOf"]}
        assert types == {"integer", "string"}

    def test_empty_array(self):
        """Empty arrays should produce array type without items."""
        samples = [{"data": []}]
        schema = self.agg._infer_schema(samples)

        assert schema["properties"]["data"] == {"type": "array"}

    def test_nested_object(self):
        """Nested objects should be recursively inferred."""
        samples = [
            {"user": {"name": "Alice", "age": 30}},
            {"user": {"name": "Bob"}},
        ]
        schema = self.agg._infer_schema(samples)

        user = schema["properties"]["user"]
        assert user["type"] == "object"
        assert "name" in user["properties"]
        assert "age" in user["properties"]
        assert "required" in user
        assert "name" in user["required"]
        assert "age" not in user["required"]

    def test_recursion_depth_limit(self):
        """Deep nesting should be capped and not recurse infinitely."""
        # Build deeply nested object
        obj = {"leaf": "value"}
        for _ in range(25):
            obj = {"nested": obj}

        samples = [obj]
        # Should not raise RecursionError
        schema = self.agg._infer_schema(samples)
        assert schema["type"] == "object"

    def test_empty_samples_returns_object(self):
        """Empty samples list should return bare object schema."""
        schema = self.agg._infer_schema([])
        assert schema == {"type": "object"}

    def test_bool_not_conflated_with_int(self):
        """Boolean values should be 'boolean', not 'integer'."""
        samples = [{"active": True}, {"active": False}]
        schema = self.agg._infer_schema(samples)

        assert schema["properties"]["active"] == {"type": "boolean"}

    def test_float_type(self):
        """Float values should produce 'number' type."""
        samples = [{"price": 9.99}, {"price": 19.99}]
        schema = self.agg._infer_schema(samples)

        assert schema["properties"]["price"] == {"type": "number"}

    def test_int_and_float_mixed(self):
        """Mixed int and float should emit oneOf."""
        samples = [
            {"value": 42},
            {"value": 3.14},
        ]
        schema = self.agg._infer_schema(samples)

        prop = schema["properties"]["value"]
        assert "oneOf" in prop
        types = {item["type"] for item in prop["oneOf"]}
        assert types == {"integer", "number"}


class TestInferType:
    """Tests for _infer_type individual values."""

    def setup_method(self):
        self.agg = EndpointAggregator()

    def test_none(self):
        assert self.agg._infer_type(None) == {"type": "null"}

    def test_bool(self):
        assert self.agg._infer_type(True) == {"type": "boolean"}

    def test_int(self):
        assert self.agg._infer_type(42) == {"type": "integer"}

    def test_float(self):
        assert self.agg._infer_type(3.14) == {"type": "number"}

    def test_string(self):
        assert self.agg._infer_type("hello") == {"type": "string"}

    def test_list_with_elements(self):
        result = self.agg._infer_type(["a", "b"])
        assert result["type"] == "array"
        assert result["items"] == {"type": "string"}

    def test_empty_list(self):
        assert self.agg._infer_type([]) == {"type": "array"}

    def test_dict(self):
        result = self.agg._infer_type({"key": "val"})
        assert result["type"] == "object"
        assert "properties" in result

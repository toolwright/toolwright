"""Tests for ResponseSample creation from raw probe results."""

from __future__ import annotations


class TestCreateResponseSample:
    def test_basic_creation(self):
        from toolwright.core.heal.sample_factory import create_response_sample

        sample = create_response_sample(
            tool_id="list_customers",
            variant="list_customers:default",
            status_code=200,
            latency_ms=142,
            body={"data": [{"id": "cus_1"}]},
        )
        assert sample.tool_id == "list_customers"
        assert sample.variant == "list_customers:default"
        assert sample.status_code == 200
        assert sample.latency_ms == 142
        assert "(root)" in sample.typed_shape
        assert sample.schema_hash  # non-empty

    def test_schema_hash_deterministic(self):
        from toolwright.core.heal.sample_factory import create_response_sample

        body = {"users": [{"id": 1, "name": "Alice"}]}
        s1 = create_response_sample(
            tool_id="t", variant="v", status_code=200, latency_ms=10, body=body,
        )
        s2 = create_response_sample(
            tool_id="t", variant="v", status_code=200, latency_ms=20, body=body,
        )
        assert s1.schema_hash == s2.schema_hash

    def test_schema_hash_changes_with_structure(self):
        from toolwright.core.heal.sample_factory import create_response_sample

        s1 = create_response_sample(
            tool_id="t", variant="v", status_code=200, latency_ms=10,
            body={"id": 1},
        )
        s2 = create_response_sample(
            tool_id="t", variant="v", status_code=200, latency_ms=10,
            body={"id": "string_now"},
        )
        assert s1.schema_hash != s2.schema_hash

    def test_root_always_in_typed_shape(self):
        from toolwright.core.heal.sample_factory import create_response_sample

        for body in [{"a": 1}, [1, 2], "hello", 42]:
            sample = create_response_sample(
                tool_id="t", variant="v", status_code=200, latency_ms=10, body=body,
            )
            assert "(root)" in sample.typed_shape

    def test_examples_are_redacted(self):
        from toolwright.core.heal.sample_factory import create_response_sample

        sample = create_response_sample(
            tool_id="t", variant="v", status_code=200, latency_ms=10,
            body={"api_key": "secret", "name": "Alice"},
        )
        assert sample.examples["api_key"] == "[REDACTED]"
        assert sample.examples["name"] == "Alice"

    def test_timestamp_set(self):
        import time

        from toolwright.core.heal.sample_factory import create_response_sample

        before = time.time()
        sample = create_response_sample(
            tool_id="t", variant="v", status_code=200, latency_ms=10, body={},
        )
        after = time.time()
        assert before <= sample.timestamp <= after

    def test_presence_paths(self):
        from toolwright.core.heal.sample_factory import create_response_sample

        sample = create_response_sample(
            tool_id="t", variant="v", status_code=200, latency_ms=10,
            body={"a": 1, "b": {"c": 2}},
        )
        assert "(root)" in sample.presence_paths
        assert "a" in sample.presence_paths
        assert "b" in sample.presence_paths
        assert "b.c" in sample.presence_paths

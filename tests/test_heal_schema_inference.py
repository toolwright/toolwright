"""Tests for confidence-aware schema inference."""

from __future__ import annotations

from toolwright.core.heal.sample_factory import create_response_sample
from toolwright.models.heal import ResponseSample


def _make_samples(bodies: list[dict], tool_id: str = "t", variant: str = "t:default") -> list[ResponseSample]:
    return [
        create_response_sample(
            tool_id=tool_id, variant=variant,
            status_code=200, latency_ms=10, body=b,
        )
        for b in bodies
    ]


class TestInferSchema:
    def test_single_sample(self):
        from toolwright.core.heal.schema_inference import infer_schema

        samples = _make_samples([{"id": 1, "name": "Alice"}])
        schema = infer_schema("t", "t:default", samples)

        assert schema.tool_id == "t"
        assert schema.sample_count == 1
        assert "(root)" in schema.fields
        assert schema.fields["id"].observed_types == ["integer"]
        assert schema.fields["name"].observed_types == ["string"]

    def test_all_low_confidence_under_20(self):
        from toolwright.core.heal.schema_inference import infer_schema

        bodies = [{"id": i, "name": "x"} for i in range(15)]
        samples = _make_samples(bodies)
        schema = infer_schema("t", "t:default", samples)

        for field in schema.fields.values():
            assert field.presence_confidence == "low"

    def test_merges_types(self):
        from toolwright.core.heal.schema_inference import infer_schema

        samples = _make_samples([{"val": 1}, {"val": "hello"}])
        schema = infer_schema("t", "t:default", samples)

        assert set(schema.fields["val"].observed_types) == {"integer", "string"}

    def test_nullable_detection(self):
        from toolwright.core.heal.schema_inference import infer_schema

        samples = _make_samples([{"x": 1}, {"x": None}])
        schema = infer_schema("t", "t:default", samples)

        assert schema.fields["x"].nullable is True

    def test_optionality_low_confidence(self):
        """N < 20: optional only if presence_rate == 0."""
        from toolwright.core.heal.schema_inference import infer_schema

        # 10 samples, 'extra' present in 5
        bodies: list[dict] = []
        for i in range(10):
            b: dict = {"id": i}
            if i < 5:
                b["extra"] = "val"
            bodies.append(b)

        samples = _make_samples(bodies)
        schema = infer_schema("t", "t:default", samples)

        # At low confidence (N<20), only optional if presence_rate == 0
        assert schema.fields["extra"].optional is False
        assert schema.fields["extra"].presence_confidence == "low"

    def test_optionality_medium_confidence(self):
        """N 20-50: optional if presence_rate < 0.90."""
        from toolwright.core.heal.schema_inference import infer_schema

        # 30 samples, 'extra' present in 20 (presence_rate = 0.667)
        bodies: list[dict] = []
        for i in range(30):
            b: dict = {"id": i}
            if i < 20:
                b["extra"] = "val"
            bodies.append(b)

        samples = _make_samples(bodies)
        schema = infer_schema("t", "t:default", samples)

        assert schema.fields["extra"].optional is True
        assert schema.fields["extra"].presence_confidence == "medium"

    def test_optionality_high_confidence(self):
        """N >= 50: optional if presence_rate < 0.95."""
        from toolwright.core.heal.schema_inference import infer_schema

        # 60 samples, 'extra' present in 55 (presence_rate ~0.917, < 0.95)
        bodies: list[dict] = []
        for i in range(60):
            b: dict = {"id": i}
            if i < 55:
                b["extra"] = "val"
            bodies.append(b)

        samples = _make_samples(bodies)
        schema = infer_schema("t", "t:default", samples)

        assert schema.fields["extra"].optional is True
        assert schema.fields["extra"].presence_confidence == "high"

    def test_presence_rate_calculation(self):
        """15 of 25 samples have field -> rate 0.60."""
        from toolwright.core.heal.schema_inference import infer_schema

        bodies: list[dict] = []
        for i in range(25):
            b: dict = {"id": i}
            if i < 15:
                b["extra"] = "val"
            bodies.append(b)

        samples = _make_samples(bodies)
        schema = infer_schema("t", "t:default", samples)

        assert abs(schema.fields["extra"].presence_rate - 0.60) < 0.01

    def test_schema_hash_deterministic(self):
        from toolwright.core.heal.schema_inference import infer_schema

        bodies = [{"id": 1, "name": "x"}]
        s1 = infer_schema("t", "t:default", _make_samples(bodies))
        s2 = infer_schema("t", "t:default", _make_samples(bodies))
        assert s1.schema_hash == s2.schema_hash

    def test_schema_hash_changes_with_fields(self):
        from toolwright.core.heal.schema_inference import infer_schema

        s1 = infer_schema("t", "t:default", _make_samples([{"id": 1}]))
        s2 = infer_schema("t", "t:default", _make_samples([{"id": 1, "extra": 2}]))
        assert s1.schema_hash != s2.schema_hash

    def test_response_type_object(self):
        from toolwright.core.heal.schema_inference import infer_schema

        schema = infer_schema("t", "t:default", _make_samples([{"id": 1}]))
        assert schema.response_type == "object"

    def test_response_type_array(self):
        from toolwright.core.heal.schema_inference import infer_schema

        samples = [
            create_response_sample(
                tool_id="t", variant="t:default",
                status_code=200, latency_ms=10, body=[1, 2, 3],
            )
        ]
        schema = infer_schema("t", "t:default", samples)
        assert schema.response_type == "array"

    def test_first_seen_last_seen(self):
        from toolwright.core.heal.schema_inference import infer_schema

        samples = _make_samples([{"id": 1}, {"id": 2}, {"id": 3}])
        schema = infer_schema("t", "t:default", samples)
        assert schema.first_seen == samples[0].timestamp
        assert schema.last_seen == samples[-1].timestamp

    def test_empty_samples_raises(self):
        from toolwright.core.heal.schema_inference import infer_schema

        with pytest.raises(ValueError, match="at least one sample"):
            infer_schema("t", "t:default", [])


import pytest

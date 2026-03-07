"""Tests for variant-aware baseline store."""

from __future__ import annotations

import json
import os
import re
import time

import pytest

from toolwright.core.heal.sample_factory import create_response_sample
from toolwright.models.heal import FieldSchema, FieldTypeInfo, InferredSchema, ResponseSample


def _make_sample(
    tool_id: str = "list_customers",
    variant: str = "list_customers:default",
    body: dict | None = None,
) -> ResponseSample:
    return create_response_sample(
        tool_id=tool_id,
        variant=variant,
        status_code=200,
        latency_ms=100,
        body=body or {"id": "cus_1", "name": "Alice"},
    )


def _make_schema(tool_id: str = "list_customers", variant: str = "list_customers:default") -> InferredSchema:
    return InferredSchema(
        tool_id=tool_id,
        variant=variant,
        schema_hash="abc123",
        sample_count=5,
        first_seen=1000.0,
        last_seen=2000.0,
        response_type="object",
        fields={
            "(root)": FieldSchema(
                name="(root)", path="(root)", field_type="object",
                nullable=False, optional=False, presence_rate=1.0,
                presence_confidence="low", observed_types=["object"],
            ),
        },
    )


class TestVariantKey:
    def test_default_variant_for_no_args(self):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore.__new__(BaselineStore)
        assert store.variant_key("tool", None) == "tool:default"
        assert store.variant_key("tool", {}) == "tool:default"

    def test_sorted_keys(self):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore.__new__(BaselineStore)
        k1 = store.variant_key("t", {"limit": "10", "offset": "0"})
        k2 = store.variant_key("t", {"offset": "0", "limit": "10"})
        assert k1 == k2

    def test_variant_slug_is_hex(self):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore.__new__(BaselineStore)
        slug = store.variant_slug("some:key")
        assert len(slug) == 12
        assert re.match(r"^[0-9a-f]{12}$", slug)

    def test_variant_slug_deterministic(self):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore.__new__(BaselineStore)
        assert store.variant_slug("a:b") == store.variant_slug("a:b")


class TestSampleStorage:
    def test_store_creates_file(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path)
        sample = _make_sample()
        path = store.record_sample(sample)
        assert path.exists()
        assert path.suffix == ".json"

    def test_collision_proof_filename(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path)
        sample = _make_sample()
        path = store.record_sample(sample)
        name = path.stem  # e.g. "1709571234567_abcdef01"
        parts = name.split("_")
        assert len(parts) == 2
        assert parts[0].isdigit()
        assert len(parts[1]) == 8
        assert re.match(r"^[0-9a-f]{8}$", parts[1])

    def test_atomic_write_no_tmp_leftover(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path)
        store.record_sample(_make_sample())
        # No .tmp files should remain
        for root, _dirs, files in os.walk(tmp_path):
            for f in files:
                assert not f.endswith(".tmp"), f"Leftover tmp file: {f}"

    def test_load_samples_round_trip(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path)
        sample = _make_sample()
        store.record_sample(sample)

        loaded = store.load_baseline_samples("list_customers", "list_customers:default")
        assert len(loaded) == 1
        assert loaded[0].tool_id == sample.tool_id
        assert loaded[0].schema_hash == sample.schema_hash

    def test_ring_buffer_eviction(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path, max_samples=5)
        for i in range(7):
            store.record_sample(_make_sample(body={"i": i}))

        loaded = store.load_baseline_samples("list_customers", "list_customers:default")
        assert len(loaded) == 5  # 2 evicted

    def test_directory_structure(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path)
        store.record_sample(_make_sample())

        slug = store.variant_slug("list_customers:default")
        variant_dir = tmp_path / "list_customers" / "variants" / slug
        assert variant_dir.exists()
        assert (variant_dir / "samples").is_dir()


class TestFreezeUnfreeze:
    def test_freeze_persists(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path)
        store.record_sample(_make_sample())
        store.freeze("list_customers:default")

        # Re-create store from same path
        store2 = BaselineStore(tmp_path)
        assert store2.is_frozen("list_customers:default")

    def test_frozen_samples_go_to_current(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path)
        store.record_sample(_make_sample())  # goes to samples/
        store.freeze("list_customers:default")
        store.record_sample(_make_sample(body={"new": True}))  # goes to current/

        baseline = store.load_baseline_samples("list_customers", "list_customers:default")
        current = store.load_current_samples("list_customers", "list_customers:default")
        assert len(baseline) == 1
        assert len(current) == 1

    def test_unfreeze_clears_flag(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path)
        store.record_sample(_make_sample())
        store.freeze("list_customers:default")
        assert store.is_frozen("list_customers:default")
        store.unfreeze("list_customers:default")
        assert not store.is_frozen("list_customers:default")

    def test_freeze_state_file(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path)
        store.record_sample(_make_sample())
        store.freeze("list_customers:default")

        frozen_path = tmp_path / "list_customers" / "frozen_variants.json"
        assert frozen_path.exists()
        data = json.loads(frozen_path.read_text())
        assert "list_customers:default" in data["frozen"]

    def test_not_frozen_by_default(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path)
        assert not store.is_frozen("list_customers:default")


class TestSchemaStorage:
    def test_save_load_round_trip(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path)
        store.record_sample(_make_sample())  # ensure variant dir exists
        schema = _make_schema()
        store.save_schema("list_customers", "list_customers:default", schema)

        loaded = store.load_schema("list_customers", "list_customers:default")
        assert loaded is not None
        assert loaded.tool_id == schema.tool_id
        assert loaded.schema_hash == schema.schema_hash
        assert "(root)" in loaded.fields

    def test_load_nonexistent_returns_none(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path)
        assert store.load_schema("missing_tool", "missing:default") is None

    def test_schema_atomic_write(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path)
        store.record_sample(_make_sample())
        store.save_schema("list_customers", "list_customers:default", _make_schema())

        for root, _dirs, files in os.walk(tmp_path):
            for f in files:
                assert not f.endswith(".tmp"), f"Leftover tmp: {f}"


class TestVariantEviction:
    def test_max_variants_evicts_lru(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path, max_variants=3)

        # Create 4 variants — oldest should be evicted
        for i in range(4):
            variant = f"tool:v{i}"
            sample = _make_sample(variant=variant)
            store.record_sample(sample)
            time.sleep(0.01)  # ensure distinct timestamps

        # Check variant meta
        meta_path = tmp_path / "list_customers" / "variant_meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert len(meta["variants"]) == 3
        # v0 should be evicted (oldest)
        variant_keys = [v["key"] for v in meta["variants"]]
        assert "tool:v0" not in variant_keys

    def test_variant_meta_persists(self, tmp_path):
        from toolwright.core.heal.baseline_store import BaselineStore

        store = BaselineStore(tmp_path)
        store.record_sample(_make_sample())

        meta_path = tmp_path / "list_customers" / "variant_meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert len(meta["variants"]) == 1
        assert meta["variants"][0]["key"] == "list_customers:default"

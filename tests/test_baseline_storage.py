"""Tests for baseline storage (serialization/deserialization round-trips).

Covers: BaselineIndex and ToolBaseline save/load, atomic writes,
concurrent access safety, and backward compatibility.
"""

from __future__ import annotations

import json
import threading

from toolwright.models.baseline import BaselineIndex, ToolBaseline
from toolwright.models.probe_template import ProbeTemplate
from toolwright.models.shape import FieldShape, ShapeModel


def _make_baseline(
    tool_id: str = "get_products",
    source: str = "har",
) -> tuple[str, ToolBaseline]:
    """Create a sample ToolBaseline for testing."""
    shape = ShapeModel(sample_count=3, last_updated="2026-03-01T12:00:00Z")
    shape.fields[""] = FieldShape(
        types_seen={"object"},
        nullable=False,
        object_keys_seen={"products"},
        seen_count=3,
        sample_count=3,
    )
    shape.fields[".products"] = FieldShape(
        types_seen={"array"},
        nullable=False,
        array_item_types_seen={"object"},
        seen_count=3,
        sample_count=3,
    )
    shape.fields[".products[]"] = FieldShape(
        types_seen={"object"},
        nullable=False,
        object_keys_seen={"id", "title"},
        seen_count=3,
        sample_count=3,
    )
    shape.fields[".products[].id"] = FieldShape(
        types_seen={"integer"},
        nullable=False,
        seen_count=3,
        sample_count=3,
    )
    shape.fields[".products[].title"] = FieldShape(
        types_seen={"string"},
        nullable=False,
        seen_count=3,
        sample_count=3,
    )

    template = ProbeTemplate(
        method="GET",
        path="/admin/api/2024-01/products.json",
        query_params={"fields": "id,title", "limit": "50"},
        headers={"Accept": "application/json"},
    )

    baseline = ToolBaseline(
        shape=shape,
        probe_template=template,
        content_hash=shape.content_hash(),
        source=source,
    )
    return tool_id, baseline


class TestRoundTripSerialization:
    def test_round_trip_serialization(self, tmp_path):
        index = BaselineIndex()
        tool_id, baseline = _make_baseline()
        index.baselines[tool_id] = baseline

        path = tmp_path / "baselines.json"
        index.save(path)

        loaded = BaselineIndex.load(path)

        assert tool_id in loaded.baselines
        lb = loaded.baselines[tool_id]

        # Shape round-trip
        assert lb.shape.sample_count == baseline.shape.sample_count
        assert set(lb.shape.fields.keys()) == set(baseline.shape.fields.keys())
        for p in baseline.shape.fields:
            assert lb.shape.fields[p].types_seen == baseline.shape.fields[p].types_seen
            assert lb.shape.fields[p].nullable == baseline.shape.fields[p].nullable
            assert lb.shape.fields[p].seen_count == baseline.shape.fields[p].seen_count
            assert lb.shape.fields[p].sample_count == baseline.shape.fields[p].sample_count
            assert lb.shape.fields[p].object_keys_seen == baseline.shape.fields[p].object_keys_seen
            assert lb.shape.fields[p].array_item_types_seen == baseline.shape.fields[p].array_item_types_seen


class TestEmptyIndex:
    def test_empty_index(self, tmp_path):
        path = tmp_path / "baselines.json"
        index = BaselineIndex()
        index.save(path)

        loaded = BaselineIndex.load(path)
        assert loaded.baselines == {}
        assert loaded.version == 1


class TestContentHashPersists:
    def test_content_hash_persists(self, tmp_path):
        index = BaselineIndex()
        tool_id, baseline = _make_baseline()
        original_hash = baseline.content_hash
        index.baselines[tool_id] = baseline

        path = tmp_path / "baselines.json"
        index.save(path)

        loaded = BaselineIndex.load(path)
        assert loaded.baselines[tool_id].content_hash == original_hash


class TestProbeTemplateRoundTrip:
    def test_probe_template_round_trip(self, tmp_path):
        index = BaselineIndex()
        tool_id, baseline = _make_baseline()
        index.baselines[tool_id] = baseline

        path = tmp_path / "baselines.json"
        index.save(path)

        loaded = BaselineIndex.load(path)
        lt = loaded.baselines[tool_id].probe_template

        assert lt.method == "GET"
        assert lt.path == "/admin/api/2024-01/products.json"
        assert lt.query_params == {"fields": "id,title", "limit": "50"}
        assert lt.headers == {"Accept": "application/json"}


class TestBackwardCompatibleLoad:
    def test_backward_compatible_load(self, tmp_path):
        """Missing optional fields should use defaults."""
        data = {
            "version": 1,
            "baselines": {
                "get_items": {
                    "shape": {
                        "fields": {
                            "": {
                                "types_seen": ["object"],
                                "nullable": False,
                            }
                        },
                    },
                    "probe_template": {
                        "method": "GET",
                        "path": "/items",
                    },
                    # No content_hash, no source
                }
            },
        }
        path = tmp_path / "baselines.json"
        path.write_text(json.dumps(data))

        loaded = BaselineIndex.load(path)
        b = loaded.baselines["get_items"]

        assert b.source == "unknown"
        assert b.content_hash is not None  # computed from shape
        assert b.shape.sample_count == 0
        assert b.shape.fields[""].seen_count == 0


class TestAtomicWrite:
    def test_atomic_write(self, tmp_path):
        """Save writes to .tmp then renames."""
        index = BaselineIndex()
        tool_id, baseline = _make_baseline()
        index.baselines[tool_id] = baseline

        path = tmp_path / "baselines.json"
        index.save(path)

        # File should exist and be valid JSON
        assert path.exists()
        data = json.loads(path.read_text())
        assert "baselines" in data

        # Temp file should NOT remain
        tmp_file = path.with_suffix(".json.tmp")
        assert not tmp_file.exists()


class TestConcurrentSaves:
    def test_concurrent_saves(self, tmp_path):
        """Two threads calling save() -> no corruption, both complete."""
        index = BaselineIndex()

        path = tmp_path / "baselines.json"
        errors: list[Exception] = []

        def save_many(prefix: str):
            try:
                for i in range(20):
                    tool_id = f"{prefix}_tool_{i}"
                    shape = ShapeModel(sample_count=1)
                    shape.fields[""] = FieldShape(
                        types_seen={"object"},
                        nullable=False,
                        seen_count=1,
                        sample_count=1,
                    )
                    index.baselines[tool_id] = ToolBaseline(
                        shape=shape,
                        probe_template=ProbeTemplate(
                            method="GET", path=f"/{tool_id}"
                        ),
                        content_hash=shape.content_hash(),
                        source="test",
                    )
                    index.save(path)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=save_many, args=("a",))
        t2 = threading.Thread(target=save_many, args=("b",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(errors) == 0, f"Errors during concurrent saves: {errors}"

        # File should be valid JSON
        data = json.loads(path.read_text())
        assert "baselines" in data


class TestSaveLock:
    def test_save_lock(self, tmp_path):
        """Concurrent saves are serialized (no interleaving)."""
        index = BaselineIndex()
        tool_id, baseline = _make_baseline()
        index.baselines[tool_id] = baseline

        path = tmp_path / "baselines.json"
        call_order: list[str] = []
        lock = threading.Lock()

        original_save = BaselineIndex.save

        def tracked_save(self_inner, p):
            with lock:
                call_order.append("start")
            original_save(self_inner, p)
            with lock:
                call_order.append("end")

        BaselineIndex.save = tracked_save  # type: ignore[method-assign]
        try:
            t1 = threading.Thread(target=lambda: index.save(path))
            t2 = threading.Thread(target=lambda: index.save(path))
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        finally:
            BaselineIndex.save = original_save  # type: ignore[method-assign]

        # Both saves completed
        assert call_order.count("start") == 2
        assert call_order.count("end") == 2


class TestLoadNonexistentFile:
    def test_load_nonexistent_file(self, tmp_path):
        path = tmp_path / "does_not_exist.json"
        index = BaselineIndex.load(path)
        assert index.baselines == {}
        assert index.version == 1

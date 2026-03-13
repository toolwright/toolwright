"""Tests for shape inference engine.

Covers: infer_shape, merge_observation, InferenceMetadata,
presence counting, array handling, depth limits, and type merging.
"""

from __future__ import annotations

import logging

from toolwright.core.drift.shape_inference import (
    MAX_ARRAY_ITEMS_PER_SAMPLE,
    MAX_WALK_DEPTH,
    infer_shape,
    merge_observation,
)
from toolwright.models.shape import ShapeModel

# ---------------------------------------------------------------------------
# infer_shape — structural inference
# ---------------------------------------------------------------------------


class TestInferFlatObject:
    def test_infer_flat_object(self):
        body = {"id": 1, "name": "x"}
        model, meta = infer_shape(body)

        assert "" in model.fields
        assert model.fields[""].types_seen == {"object"}
        assert model.fields[""].object_keys_seen == {"id", "name"}

        assert ".id" in model.fields
        assert model.fields[".id"].types_seen == {"integer"}

        assert ".name" in model.fields
        assert model.fields[".name"].types_seen == {"string"}


class TestInferNestedObject:
    def test_infer_nested_object(self):
        body = {"a": {"b": {"c": 1}}}
        model, _ = infer_shape(body)

        assert ".a" in model.fields
        assert model.fields[".a"].types_seen == {"object"}
        assert ".a.b" in model.fields
        assert model.fields[".a.b"].types_seen == {"object"}
        assert ".a.b.c" in model.fields
        assert model.fields[".a.b.c"].types_seen == {"integer"}


class TestInferArrayOfObjects:
    def test_infer_array_of_objects(self):
        body = {"items": [{"id": 1}]}
        model, _ = infer_shape(body)

        assert ".items" in model.fields
        assert model.fields[".items"].types_seen == {"array"}
        assert model.fields[".items"].array_item_types_seen == {"object"}

        # Intermediate array item node
        assert ".items[]" in model.fields
        assert model.fields[".items[]"].types_seen == {"object"}
        assert model.fields[".items[]"].object_keys_seen == {"id"}

        assert ".items[].id" in model.fields
        assert model.fields[".items[].id"].types_seen == {"integer"}


class TestInferArrayOfScalars:
    def test_infer_array_of_scalars(self):
        body = {"tags": ["a", "b"]}
        model, _ = infer_shape(body)

        assert ".tags" in model.fields
        assert model.fields[".tags"].types_seen == {"array"}
        assert model.fields[".tags"].array_item_types_seen == {"string"}

        assert ".tags[]" in model.fields
        assert model.fields[".tags[]"].types_seen == {"string"}


class TestInferNullValue:
    def test_infer_null_value(self):
        body = {"x": None}
        model, _ = infer_shape(body)

        assert ".x" in model.fields
        assert model.fields[".x"].nullable is True
        assert model.fields[".x"].types_seen == {"null"}


class TestInferMixedTypes:
    def test_infer_mixed_types(self):
        """After merging two samples with different types for the same field."""
        shape = ShapeModel()
        merge_observation(shape, {"x": 1})
        merge_observation(shape, {"x": "hi"})

        assert ".x" in shape.fields
        assert shape.fields[".x"].types_seen == {"integer", "string"}


class TestInferEmptyArray:
    def test_infer_empty_array(self):
        body = {"items": []}
        model, meta = infer_shape(body)

        assert ".items" in model.fields
        assert model.fields[".items"].types_seen == {"array"}
        # No array item types observed
        assert model.fields[".items"].array_item_types_seen == set()
        # No .items[] node created for empty array
        assert ".items[]" not in model.fields

    def test_infer_empty_array_metadata(self):
        body = {"items": []}
        _, meta = infer_shape(body)
        assert ".items" in meta.empty_array_paths

    def test_infer_non_empty_array_not_in_metadata(self):
        body = {"items": [{"id": 1}]}
        _, meta = infer_shape(body)
        assert ".items" not in meta.empty_array_paths


class TestInferEmptyObject:
    def test_infer_empty_object(self):
        body = {}
        model, _ = infer_shape(body)

        assert "" in model.fields
        assert model.fields[""].types_seen == {"object"}
        assert model.fields[""].object_keys_seen == set()


class TestInferDeeplyNested:
    def test_infer_deeply_nested(self):
        body: dict = {"a": {"b": {"c": {"d": {"e": 42}}}}}
        model, _ = infer_shape(body)

        assert ".a.b.c.d.e" in model.fields
        assert model.fields[".a.b.c.d.e"].types_seen == {"integer"}


class TestInferDoesNotSetPresence:
    def test_infer_does_not_set_presence(self):
        body = {"id": 1, "items": [{"name": "x"}]}
        model, _ = infer_shape(body)

        for path, fs in model.fields.items():
            assert fs.seen_count == 0, f"{path} should have seen_count=0"
            assert fs.sample_count == 0, f"{path} should have sample_count=0"
        assert model.sample_count == 0


class TestInferNestedArrayPaths:
    def test_infer_nested_array_paths(self):
        body = {"m": [[1, 2], [3, 4]]}
        model, _ = infer_shape(body)

        assert ".m" in model.fields
        assert model.fields[".m"].types_seen == {"array"}

        # .m[] represents items of the outer array (which are arrays)
        assert ".m[]" in model.fields
        assert model.fields[".m[]"].types_seen == {"array"}

        # .m[][] represents items of the inner arrays (which are integers)
        assert ".m[][]" in model.fields
        assert model.fields[".m[][]"].types_seen == {"integer"}


class TestInferTripleNestedArray:
    def test_infer_triple_nested_array(self):
        body = [[[1]]]
        model, _ = infer_shape(body)

        assert "" in model.fields
        assert model.fields[""].types_seen == {"array"}

        assert "[]" in model.fields
        assert model.fields["[]"].types_seen == {"array"}

        assert "[][]" in model.fields
        assert model.fields["[][]"].types_seen == {"array"}

        assert "[][][]" in model.fields
        assert model.fields["[][][]"].types_seen == {"integer"}


class TestInferMaxDepthGuard:
    def test_infer_max_depth_guard(self):
        # Build a 40-level deep nested object
        body: dict = {"value": 1}
        for _ in range(39):
            body = {"nested": body}

        model, _ = infer_shape(body)
        # Should not crash — just stops at MAX_WALK_DEPTH
        assert len(model.fields) <= MAX_WALK_DEPTH + 2  # root + up to depth limit


class TestInferArrayItemKeysTracked:
    def test_infer_array_item_keys_tracked(self):
        body = {"items": [{"id": 1, "name": "x"}]}
        model, _ = infer_shape(body)

        assert ".items[]" in model.fields
        assert model.fields[".items[]"].object_keys_seen == {"id", "name"}


class TestInferArrayItemsMergeKeys:
    def test_infer_array_items_merge_keys(self):
        body = {"items": [{"id": 1}, {"id": 2, "extra": True}]}
        model, _ = infer_shape(body)

        assert model.fields[".items[]"].object_keys_seen == {"id", "extra"}


class TestInferMaxArrayItems:
    def test_infer_max_array_items(self):
        items = [{"id": i} for i in range(100)]
        body = {"items": items}
        model, meta = infer_shape(body)

        # Shape is still inferred correctly from first N items
        assert ".items[].id" in model.fields
        assert model.fields[".items[].id"].types_seen == {"integer"}

    def test_infer_max_array_items_logs(self, caplog):
        items = [{"id": i} for i in range(MAX_ARRAY_ITEMS_PER_SAMPLE + 10)]
        body = {"items": items}

        with caplog.at_level(logging.DEBUG, logger="toolwright.drift"):
            infer_shape(body)

        assert any(
            "inspecting first" in record.message for record in caplog.records
        )


class TestInferTruncatedArrayMetadata:
    def test_infer_truncated_array_metadata(self):
        items = [{"id": i} for i in range(MAX_ARRAY_ITEMS_PER_SAMPLE + 1)]
        body = {"items": items}
        _, meta = infer_shape(body)

        assert ".items" in meta.truncated_array_paths

    def test_infer_small_array_not_truncated(self):
        body = {"items": [{"id": 1}, {"id": 2}, {"id": 3}]}
        _, meta = infer_shape(body)
        assert ".items" not in meta.truncated_array_paths


# ---------------------------------------------------------------------------
# merge_observation — presence counting and structural merge
# ---------------------------------------------------------------------------


class TestMergeFirstSample:
    def test_merge_first_sample(self):
        shape = ShapeModel()
        merge_observation(shape, {"id": 1, "name": "x"})

        assert shape.sample_count == 1
        assert shape.fields[".id"].seen_count == 1
        assert shape.fields[".id"].sample_count == 1
        assert shape.fields[".name"].seen_count == 1
        assert shape.fields[""].seen_count == 1


class TestMergeAddsNewPaths:
    def test_merge_adds_new_paths(self):
        shape = ShapeModel()
        merge_observation(shape, {"id": 1})
        merge_observation(shape, {"id": 2, "extra": "new"})

        assert ".extra" in shape.fields
        assert shape.fields[".extra"].seen_count == 1
        assert shape.fields[".extra"].sample_count == 2


class TestMergeUpdatesPresence:
    def test_merge_updates_presence(self):
        shape = ShapeModel()
        merge_observation(shape, {"id": 1, "optional": "yes"})
        merge_observation(shape, {"id": 2})

        assert shape.fields[".optional"].seen_count == 1
        assert shape.fields[".optional"].sample_count == 2
        assert shape.fields[".optional"].presence_ratio == 0.5


class TestMergeWidensTypes:
    def test_merge_widens_types(self):
        shape = ShapeModel()
        merge_observation(shape, {"x": 1})
        merge_observation(shape, {"x": "hello"})

        assert shape.fields[".x"].types_seen == {"integer", "string"}


class TestMergeTracksNullability:
    def test_merge_tracks_nullability(self):
        shape = ShapeModel()
        merge_observation(shape, {"x": 1})
        assert shape.fields[".x"].nullable is False

        merge_observation(shape, {"x": None})
        assert shape.fields[".x"].nullable is True


class TestMergeArrayPresenceIsPerSample:
    def test_merge_array_presence_is_per_sample(self):
        """Array with 2 items: seen_count for .items[].id should be 1, not 2."""
        shape = ShapeModel()
        merge_observation(shape, {"items": [{"id": 1}, {"id": 2}]})

        assert shape.fields[".items[].id"].seen_count == 1
        assert shape.fields[".items[].id"].sample_count == 1


class TestMergeArray100Items:
    def test_merge_array_100_items(self):
        items = [{"id": i} for i in range(100)]
        shape = ShapeModel()
        merge_observation(shape, {"items": items})

        assert shape.fields[".items[].id"].seen_count == 1
        assert shape.fields[".items[].id"].sample_count == 1


class TestMergeEmptyArrayDoesNotDilutePresence:
    def test_merge_empty_array_does_not_dilute_presence(self):
        shape = ShapeModel()
        # 5 samples with items
        for i in range(5):
            merge_observation(shape, {"items": [{"id": i}]})

        assert shape.fields[".items[].id"].seen_count == 5
        assert shape.fields[".items[].id"].sample_count == 5

        # Now merge empty array — should NOT dilute presence
        merge_observation(shape, {"items": []})

        assert shape.fields[".items[].id"].seen_count == 5
        # sample_count should NOT have been bumped for array descendants
        assert shape.fields[".items[].id"].sample_count == 5


class TestMergeTruncatedArrayDoesNotDilutePresence:
    def test_merge_truncated_array_does_not_dilute_presence(self):
        shape = ShapeModel()
        # 5 samples with items
        for i in range(5):
            merge_observation(shape, {"items": [{"id": i, "deep": True}]})

        assert shape.fields[".items[].deep"].seen_count == 5
        assert shape.fields[".items[].deep"].sample_count == 5

        # Merge a truncated array — should NOT dilute deep field's presence
        big_items = [{"id": i} for i in range(MAX_ARRAY_ITEMS_PER_SAMPLE + 10)]
        # Note: "deep" only appears in items beyond the sample limit
        # This should not affect the presence ratio
        merge_observation(shape, {"items": big_items})

        # .items[].id should be bumped (it was observed in the truncated sample)
        assert shape.fields[".items[].id"].seen_count == 6

        # .items[].deep should NOT have its sample_count bumped
        # because it's under a truncated array
        assert shape.fields[".items[].deep"].sample_count == 5


class TestMergeNonArrayPathStillBumped:
    def test_merge_non_array_path_still_bumped(self):
        shape = ShapeModel()
        merge_observation(shape, {"items": [{"id": 1}], "top": "yes"})
        merge_observation(shape, {"items": []})

        # top_level_field was missing in second sample → sample_count bumped
        assert shape.fields[".top"].seen_count == 1
        assert shape.fields[".top"].sample_count == 2


class TestPresenceRatio:
    def test_presence_ratio(self):
        shape = ShapeModel()
        # Present in 3 of 4 samples
        for _ in range(3):
            merge_observation(shape, {"x": 1})
        merge_observation(shape, {"y": 2})

        assert shape.fields[".x"].presence_ratio == 3 / 4
        assert not shape.fields[".x"].is_effectively_required()


class TestPresenceRatioNeverExceedsOne:
    def test_presence_ratio_never_exceeds_one(self):
        shape = ShapeModel()
        # Array with many items
        merge_observation(shape, {"items": [{"id": i} for i in range(50)]})

        for path, fs in shape.fields.items():
            assert (
                fs.presence_ratio <= 1.0
            ), f"{path} presence_ratio={fs.presence_ratio}"


class TestEffectivelyRequired:
    def test_effectively_required(self):
        shape = ShapeModel()
        # Present in 19 of 20 samples
        for _ in range(19):
            merge_observation(shape, {"x": 1})
        merge_observation(shape, {"y": 2})

        assert shape.fields[".x"].presence_ratio == 19 / 20
        assert shape.fields[".x"].is_effectively_required()  # >= 0.95


class TestContentHash:
    def test_content_hash_stable(self):
        shape = ShapeModel()
        merge_observation(shape, {"id": 1, "name": "x"})

        h1 = shape.content_hash()
        h2 = shape.content_hash()
        assert h1 == h2

    def test_content_hash_changes(self):
        shape1 = ShapeModel()
        merge_observation(shape1, {"id": 1})

        shape2 = ShapeModel()
        merge_observation(shape2, {"id": 1, "extra": "x"})

        assert shape1.content_hash() != shape2.content_hash()

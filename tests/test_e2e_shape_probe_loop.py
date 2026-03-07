"""E2E tests for the complete shape probe loop.

Exercises the full cycle: probe → detect → handle for both
SAFE (auto-merge) and breaking (log) drift scenarios. Uses real
BaselineIndex serialization, real shape inference, and real drift
detection — only the HTTP layer is mocked.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from toolwright.core.drift.probe_executor import ProbeResult
from toolwright.core.drift.shape_inference import merge_observation
from toolwright.core.drift.shape_probe_loop import ShapeProbeLoop
from toolwright.models.baseline import BaselineIndex, ToolBaseline
from toolwright.models.probe_template import ProbeTemplate
from toolwright.models.shape import ShapeModel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_baseline_index(bodies: dict[str, list[dict]]) -> BaselineIndex:
    """Build a real BaselineIndex from sample response bodies per tool.

    Each tool gets a shape built from the supplied bodies and a default
    GET probe template.
    """
    index = BaselineIndex()
    for tool_name, response_bodies in bodies.items():
        shape = ShapeModel()
        for body in response_bodies:
            merge_observation(shape, body)
        index.baselines[tool_name] = ToolBaseline(
            shape=shape,
            probe_template=ProbeTemplate(
                method="GET",
                path=f"/api/{tool_name}",
            ),
            content_hash=shape.content_hash(),
            source="har",
        )
    return index


def _mock_client_returning(response_map: dict[str, dict]) -> AsyncMock:
    """Create a mock httpx.AsyncClient that returns different JSON bodies per URL path.

    response_map keys are URL path suffixes (e.g., "/api/list_products").
    """
    async def fake_request(_method: str, url: str, **_kwargs) -> httpx.Response:
        for path_suffix, body in response_map.items():
            if path_suffix in url:
                return httpx.Response(
                    status_code=200,
                    headers={"content-type": "application/json", "content-length": "1000"},
                    json=body,
                )
        return httpx.Response(
            status_code=404,
            headers={"content-type": "text/plain"},
            text="Not found",
        )

    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock(side_effect=fake_request)
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestE2EFullLoopSafeDrift:
    """Full loop: new optional field → SAFE → auto-merge → baseline updated on disk."""

    @pytest.mark.asyncio
    async def test_safe_drift_auto_merges_and_persists(self, tmp_path: Path):
        # --- Arrange: create a baseline from a response missing a field ---
        original_body = {"id": 1, "name": "Widget", "price": 9.99}
        index = _build_baseline_index({"list_products": [original_body]})

        baselines_path = tmp_path / "baselines.json"
        events_path = tmp_path / "drift_events.jsonl"
        index.save(baselines_path)

        original_sample_count = index.baselines["list_products"].shape.sample_count
        original_hash = index.baselines["list_products"].content_hash

        # The probe returns a response with a NEW optional field "sku"
        drifted_body = {"id": 2, "name": "Gadget", "price": 19.99, "sku": "GDG-001"}
        client = _mock_client_returning({"/api/list_products": drifted_body})

        loop = ShapeProbeLoop(
            baseline_index=index,
            baselines_path=baselines_path,
            events_path=events_path,
            host="api.example.com",
            client=client,
            probe_interval=0,  # always due
        )

        # --- Act ---
        results = await loop.probe_cycle()

        # --- Assert: auto-merged ---
        assert "list_products" in results
        action = results["list_products"]
        assert hasattr(action, "action")  # DriftAction, not ProbeResult
        assert action.action == "auto_merged"

        # Baseline updated: sample_count bumped
        updated_baseline = index.baselines["list_products"]
        assert updated_baseline.shape.sample_count == original_sample_count + 1

        # Content hash changed
        assert updated_baseline.content_hash != original_hash

        # New field ".sku" exists in the shape
        assert ".sku" in updated_baseline.shape.fields

        # Baselines persisted to disk
        reloaded = BaselineIndex.load(baselines_path)
        assert ".sku" in reloaded.baselines["list_products"].shape.fields
        assert reloaded.baselines["list_products"].shape.sample_count == original_sample_count + 1

        # No events logged (SAFE drift doesn't log)
        assert not events_path.exists()


class TestE2EFullLoopBreakingDrift:
    """Full loop: type change → MANUAL → logged to events file → baseline NOT changed."""

    @pytest.mark.asyncio
    async def test_breaking_drift_logs_and_does_not_merge(self, tmp_path: Path):
        # --- Arrange: baseline has integer "id" ---
        original_body = {"id": 1, "name": "Widget"}
        index = _build_baseline_index({"get_product": [original_body]})

        baselines_path = tmp_path / "baselines.json"
        events_path = tmp_path / "drift_events.jsonl"
        index.save(baselines_path)

        original_hash = index.baselines["get_product"].content_hash
        original_sample_count = index.baselines["get_product"].shape.sample_count

        # The probe returns "id" as a STRING — type_changed_breaking
        drifted_body = {"id": "abc-123", "name": "Widget"}
        client = _mock_client_returning({"/api/get_product": drifted_body})

        loop = ShapeProbeLoop(
            baseline_index=index,
            baselines_path=baselines_path,
            events_path=events_path,
            host="api.example.com",
            client=client,
            probe_interval=0,
        )

        # --- Act ---
        results = await loop.probe_cycle()

        # --- Assert: logged, NOT merged ---
        action = results["get_product"]
        assert action.action == "logged"
        assert action.severity is not None

        # Baseline NOT updated
        assert index.baselines["get_product"].content_hash == original_hash
        assert index.baselines["get_product"].shape.sample_count == original_sample_count

        # Events file written
        assert events_path.exists()
        events = [json.loads(line) for line in events_path.read_text().strip().split("\n")]
        assert len(events) == 1
        assert events[0]["tool_name"] == "get_product"
        assert events[0]["severity"] in ("manual", "approval_required")
        assert len(events[0]["changes"]) >= 1


class TestE2EFullLoopNoDrift:
    """Full loop: identical response → no drift → no-op."""

    @pytest.mark.asyncio
    async def test_identical_response_produces_no_drift(self, tmp_path: Path):
        # --- Arrange: baseline and probe return the same body ---
        body = {"id": 1, "status": "active", "count": 42}
        index = _build_baseline_index({"check_status": [body]})

        baselines_path = tmp_path / "baselines.json"
        events_path = tmp_path / "drift_events.jsonl"
        index.save(baselines_path)

        original_hash = index.baselines["check_status"].content_hash

        client = _mock_client_returning({"/api/check_status": body})

        loop = ShapeProbeLoop(
            baseline_index=index,
            baselines_path=baselines_path,
            events_path=events_path,
            host="api.example.com",
            client=client,
            probe_interval=0,
        )

        # --- Act ---
        results = await loop.probe_cycle()

        # --- Assert: no_drift ---
        action = results["check_status"]
        assert action.action == "no_drift"

        # Hash unchanged
        assert index.baselines["check_status"].content_hash == original_hash

        # No events logged
        assert not events_path.exists()


class TestE2EFullLoopProbeFailure:
    """Full loop: HTTP error → ProbeResult (not DriftAction), baseline untouched."""

    @pytest.mark.asyncio
    async def test_probe_failure_returns_error_and_leaves_baseline(self, tmp_path: Path):
        # --- Arrange ---
        body = {"id": 1}
        index = _build_baseline_index({"failing_tool": [body]})

        baselines_path = tmp_path / "baselines.json"
        events_path = tmp_path / "drift_events.jsonl"
        index.save(baselines_path)

        original_hash = index.baselines["failing_tool"].content_hash

        # Mock client returns 500
        async def fail_request(_method: str, _url: str, **_kwargs) -> httpx.Response:
            return httpx.Response(
                status_code=500,
                headers={"content-type": "text/plain"},
                text="Internal Server Error",
            )

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=fail_request)

        loop = ShapeProbeLoop(
            baseline_index=index,
            baselines_path=baselines_path,
            events_path=events_path,
            host="api.example.com",
            client=client,
            probe_interval=0,
        )

        # --- Act ---
        results = await loop.probe_cycle()

        # --- Assert: ProbeResult with error ---
        result = results["failing_tool"]
        assert isinstance(result, ProbeResult)
        assert not result.ok
        assert "500" in (result.error or "")

        # Baseline untouched
        assert index.baselines["failing_tool"].content_hash == original_hash
        assert not events_path.exists()


class TestE2EMultipleToolsMixed:
    """Full loop with multiple tools: one SAFE, one breaking, one no-drift."""

    @pytest.mark.asyncio
    async def test_mixed_results_across_tools(self, tmp_path: Path):
        # --- Arrange ---
        index = _build_baseline_index({
            "tool_safe": [{"id": 1, "name": "A"}],
            "tool_breaking": [{"id": 1, "name": "B"}],
            "tool_stable": [{"id": 1, "name": "C"}],
        })

        baselines_path = tmp_path / "baselines.json"
        events_path = tmp_path / "drift_events.jsonl"
        index.save(baselines_path)

        # tool_safe: new field → auto-merge
        # tool_breaking: type change on id → log
        # tool_stable: identical → no-op
        client = _mock_client_returning({
            "/api/tool_safe": {"id": 2, "name": "A2", "new_field": True},
            "/api/tool_breaking": {"id": "string-id", "name": "B"},
            "/api/tool_stable": {"id": 3, "name": "C"},
        })

        loop = ShapeProbeLoop(
            baseline_index=index,
            baselines_path=baselines_path,
            events_path=events_path,
            host="api.example.com",
            client=client,
            probe_interval=0,
        )

        # --- Act ---
        results = await loop.probe_cycle()

        # --- Assert: all three tools probed ---
        assert len(results) == 3

        # tool_safe → auto_merged
        assert results["tool_safe"].action == "auto_merged"
        assert ".new_field" in index.baselines["tool_safe"].shape.fields

        # tool_breaking → logged
        assert results["tool_breaking"].action == "logged"

        # tool_stable → no_drift
        assert results["tool_stable"].action == "no_drift"

        # Events file has exactly 1 event (from tool_breaking)
        assert events_path.exists()
        events = [json.loads(line) for line in events_path.read_text().strip().split("\n")]
        assert len(events) == 1
        assert events[0]["tool_name"] == "tool_breaking"

        # Reloaded baselines reflect the SAFE merge
        reloaded = BaselineIndex.load(baselines_path)
        assert ".new_field" in reloaded.baselines["tool_safe"].shape.fields

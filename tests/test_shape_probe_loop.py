"""Tests for ShapeProbeLoop — shape-based drift detection in the reconciliation loop.

Covers: probing due tools, skipping unhealthy tools, auto-merging SAFE drift,
logging non-SAFE drift, respecting probe intervals, and concurrent probe limiting.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from toolwright.models.baseline import BaselineIndex, ToolBaseline
from toolwright.models.probe_template import ProbeTemplate
from toolwright.models.shape import FieldShape, ShapeModel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_baseline_index(
    tools: dict[str, dict] | None = None,
) -> BaselineIndex:
    """Build a BaselineIndex with one or more tool baselines."""
    if tools is None:
        tools = {"list_products": {"path": "/products"}}

    index = BaselineIndex()
    for name, spec in tools.items():
        shape = ShapeModel(sample_count=10, last_updated="2026-03-01T12:00:00Z")
        shape.fields[""] = FieldShape(
            types_seen={"object"},
            nullable=False,
            object_keys_seen={"data"},
            seen_count=10,
            sample_count=10,
        )
        shape.fields[".data"] = FieldShape(
            types_seen={"array"},
            nullable=False,
            array_item_types_seen={"object"},
            seen_count=10,
            sample_count=10,
        )
        index.baselines[name] = ToolBaseline(
            shape=shape,
            probe_template=ProbeTemplate(
                method="GET",
                path=spec.get("path", "/"),
            ),
            content_hash=shape.content_hash(),
            source="har",
        )
    return index


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestShapeProbeLoopBasic:
    @pytest.mark.asyncio
    async def test_probes_all_tools_on_first_run(self, tmp_path):
        """First run: all tools should be probed."""
        from toolwright.core.drift.shape_probe_loop import ShapeProbeLoop

        index = _make_baseline_index({
            "tool_a": {"path": "/a"},
            "tool_b": {"path": "/b"},
        })
        baselines_path = tmp_path / "shape_baselines.json"
        index.save(baselines_path)

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            content=json.dumps({"data": []}).encode(),
            request=httpx.Request("GET", "https://example.com"),
        ))

        loop = ShapeProbeLoop(
            baseline_index=index,
            baselines_path=baselines_path,
            events_path=tmp_path / "drift_events.jsonl",
            host="api.example.com",
            client=mock_client,
        )

        probed = await loop.probe_cycle()

        # Both tools should have been probed
        assert len(probed) == 2
        assert "tool_a" in probed
        assert "tool_b" in probed


class TestShapeProbeLoopInterval:
    @pytest.mark.asyncio
    async def test_respects_interval_on_second_run(self, tmp_path):
        """Second run within interval: tools should NOT be re-probed."""
        from toolwright.core.drift.shape_probe_loop import ShapeProbeLoop

        index = _make_baseline_index()
        baselines_path = tmp_path / "shape_baselines.json"
        index.save(baselines_path)

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            content=json.dumps({"data": []}).encode(),
            request=httpx.Request("GET", "https://example.com"),
        ))

        loop = ShapeProbeLoop(
            baseline_index=index,
            baselines_path=baselines_path,
            events_path=tmp_path / "drift_events.jsonl",
            host="api.example.com",
            client=mock_client,
            probe_interval=300,  # 5 minutes
        )

        # First cycle probes all
        probed1 = await loop.probe_cycle()
        assert len(probed1) == 1

        # Second cycle: within interval, should skip
        probed2 = await loop.probe_cycle()
        assert len(probed2) == 0


class TestShapeProbeLoopSafeAutoMerge:
    @pytest.mark.asyncio
    async def test_safe_drift_auto_merged(self, tmp_path):
        """SAFE drift from probe -> auto-merge into baseline."""
        from toolwright.core.drift.shape_probe_loop import ShapeProbeLoop

        index = _make_baseline_index()
        baselines_path = tmp_path / "shape_baselines.json"
        index.save(baselines_path)

        # Response with a new field -> SAFE drift
        response_body = {"data": [{"id": 1, "new_field": "value"}]}
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            content=json.dumps(response_body).encode(),
            request=httpx.Request("GET", "https://example.com"),
        ))

        loop = ShapeProbeLoop(
            baseline_index=index,
            baselines_path=baselines_path,
            events_path=tmp_path / "drift_events.jsonl",
            host="api.example.com",
            client=mock_client,
        )

        probed = await loop.probe_cycle()
        assert "list_products" in probed

        # Baseline should have been updated with new sample
        bl = index.baselines["list_products"]
        assert bl.shape.sample_count == 11  # was 10, merged 1


class TestShapeProbeLoopSkipUnhealthy:
    @pytest.mark.asyncio
    async def test_unhealthy_tools_skipped(self, tmp_path):
        """Tools where the probe fails should not trigger drift detection."""
        from toolwright.core.drift.shape_probe_loop import ShapeProbeLoop

        index = _make_baseline_index()
        baselines_path = tmp_path / "shape_baselines.json"
        index.save(baselines_path)

        # Probe returns 500
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=httpx.Response(
            status_code=500,
            headers={"content-type": "text/html"},
            content=b"Internal Server Error",
            request=httpx.Request("GET", "https://example.com"),
        ))

        loop = ShapeProbeLoop(
            baseline_index=index,
            baselines_path=baselines_path,
            events_path=tmp_path / "drift_events.jsonl",
            host="api.example.com",
            client=mock_client,
        )

        probed = await loop.probe_cycle()

        # Tool was probed but baseline should NOT be modified
        assert "list_products" in probed
        assert index.baselines["list_products"].shape.sample_count == 10  # unchanged


class TestShapeProbeLoopConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_probes_limited(self, tmp_path):
        """Probes should respect max_concurrent limit."""
        from toolwright.core.drift.shape_probe_loop import ShapeProbeLoop

        tools = {f"tool_{i}": {"path": f"/t{i}"} for i in range(10)}
        index = _make_baseline_index(tools)
        baselines_path = tmp_path / "shape_baselines.json"
        index.save(baselines_path)

        concurrent_count = 0
        max_concurrent = 0

        async def mock_request(*_args, **_kwargs):
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.01)
            concurrent_count -= 1
            return httpx.Response(
                status_code=200,
                headers={"content-type": "application/json"},
                content=json.dumps({"data": []}).encode(),
                request=httpx.Request("GET", "https://example.com"),
            )

        mock_client = AsyncMock()
        mock_client.request = mock_request

        loop = ShapeProbeLoop(
            baseline_index=index,
            baselines_path=baselines_path,
            events_path=tmp_path / "drift_events.jsonl",
            host="api.example.com",
            client=mock_client,
            max_concurrent_probes=3,
        )

        probed = await loop.probe_cycle()

        assert len(probed) == 10
        assert max_concurrent <= 3

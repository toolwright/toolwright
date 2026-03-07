"""Shape probe loop — second-tier probing for shape-based drift detection.

Iterates through tools in a BaselineIndex, fires GET probes using
probe templates, detects drift, and routes results to the drift handler.
Designed to run alongside the health probe loop in serve --watch mode.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import httpx

from toolwright.core.drift.baselines import detect_drift_for_tool
from toolwright.core.drift.drift_handler import DriftAction, handle_drift
from toolwright.core.drift.probe_executor import ProbeResult, execute_probe
from toolwright.models.baseline import BaselineIndex

logger = logging.getLogger("toolwright.drift.shape_probe_loop")

DEFAULT_PROBE_INTERVAL: int = 300  # 5 minutes
DEFAULT_MAX_CONCURRENT: int = 3


class ShapeProbeLoop:
    """Schedule-aware shape probe loop.

    On each cycle, iterates tools in the BaselineIndex, probes those
    that are due, runs drift detection, and routes results to the handler.
    """

    def __init__(
        self,
        *,
        baseline_index: BaselineIndex,
        baselines_path: Path,
        events_path: Path,
        host: str,
        client: httpx.AsyncClient | None = None,
        auth_header: str | None = None,
        extra_headers: dict[str, str] | None = None,
        base_url: str | None = None,
        probe_interval: int = DEFAULT_PROBE_INTERVAL,
        max_concurrent_probes: int = DEFAULT_MAX_CONCURRENT,
    ) -> None:
        self._index = baseline_index
        self._baselines_path = baselines_path
        self._events_path = events_path
        self._host = host
        self._client = client
        self._auth_header = auth_header
        self._extra_headers = extra_headers
        self._base_url = base_url
        self._probe_interval = probe_interval
        self._max_concurrent = max_concurrent_probes

        # Track last probe time per tool
        self._last_probe_at: dict[str, float] = {}

    def _is_due(self, tool_name: str) -> bool:
        """Check if a tool is due for probing."""
        last = self._last_probe_at.get(tool_name)
        if last is None:
            return True
        return (time.monotonic() - last) >= self._probe_interval

    async def probe_cycle(self) -> dict[str, DriftAction | ProbeResult]:
        """Run one probe cycle across all due tools.

        Returns:
            Dict mapping tool_name -> action taken (DriftAction or ProbeResult).
        """
        due_tools = [
            name for name in self._index.baselines
            if self._is_due(name)
        ]

        if not due_tools:
            return {}

        semaphore = asyncio.Semaphore(self._max_concurrent)
        results: dict[str, DriftAction | ProbeResult] = {}

        async def probe_one(tool_name: str) -> None:
            async with semaphore:
                result = await self._probe_and_handle(tool_name)
                results[tool_name] = result

        await asyncio.gather(*[probe_one(name) for name in due_tools])
        return results

    async def _probe_and_handle(
        self, tool_name: str
    ) -> DriftAction | ProbeResult:
        """Probe a single tool and handle the result."""
        baseline = self._index.baselines.get(tool_name)
        if baseline is None:
            return ProbeResult(ok=False, error=f"No baseline for {tool_name}")

        # Mark as probed regardless of outcome
        self._last_probe_at[tool_name] = time.monotonic()

        # Execute probe
        probe_result = await execute_probe(
            template=baseline.probe_template,
            host=self._host,
            client=self._client,
            auth_header=self._auth_header,
            extra_headers=self._extra_headers,
            base_url=self._base_url,
        )

        # If probe failed, return the probe result (no drift detection)
        if not probe_result.ok:
            logger.debug(
                "Probe failed for %s: %s", tool_name, probe_result.error
            )
            return probe_result

        # Run drift detection
        drift_result = detect_drift_for_tool(
            tool_name, probe_result.body, self._index
        )

        # Handle drift
        action = handle_drift(
            drift_result=drift_result,
            response_body=probe_result.body,
            baseline_index=self._index,
            baselines_path=self._baselines_path,
            events_path=self._events_path,
        )

        return action

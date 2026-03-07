"""Shape baseline compilation and per-tool drift detection.

compile_shape_baselines(): matches captured HTTP exchanges to compiled
tool actions, infers response shapes, produces a BaselineIndex.

detect_drift_for_tool(): compares a new response body against a stored
baseline shape and returns classified drift changes.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlparse

from toolwright.core.drift.shape_diff import (
    DriftChange,
    DriftSeverity,
    diff_shapes,
    overall_severity,
)
from toolwright.core.drift.shape_inference import infer_shape, merge_observation
from toolwright.models.baseline import BaselineIndex, ToolBaseline
from toolwright.models.capture import CaptureSession
from toolwright.models.probe_template import ProbeTemplate
from toolwright.models.shape import ShapeModel

logger = logging.getLogger("toolwright.drift.baselines")

# Headers to strip from probe templates (case-insensitive).
_REDACTED_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "x-csrf-token",
    "x-xsrf-token",
}


def compile_shape_baselines(
    session: CaptureSession,
    manifest: dict[str, Any],
) -> BaselineIndex:
    """Compile shape baselines from captured response bodies.

    Matches exchanges to tool actions by (method, host, path),
    infers response shapes from JSON bodies, and returns a
    BaselineIndex ready to save.

    Args:
        session: Capture session with exchanges.
        manifest: Compiled tools manifest (the dict from tools.json).

    Returns:
        BaselineIndex with per-tool shape baselines.
    """
    # Build action lookup: (METHOD, host, path) -> action_name
    action_lookup: dict[tuple[str, str, str], str] = {}
    for action in manifest.get("actions", []):
        method = str(action.get("method", "GET")).upper()
        host = str(action.get("host", "")).lower()
        path = str(action.get("path", ""))
        name = str(action.get("name", ""))
        if name:
            action_lookup[(method, host, path)] = name

    # Group exchange response bodies by tool name.
    # Also keep the first matching exchange per tool for probe template.
    tool_responses: dict[str, list[Any]] = defaultdict(list)
    tool_first_exchange: dict[str, Any] = {}

    for exchange in session.exchanges:
        if not exchange.response_body_json:
            continue

        method = exchange.method.value.upper()
        host = exchange.host.lower()
        path = exchange.path

        key = (method, host, path)
        action_name = action_lookup.get(key)
        if action_name:
            tool_responses[action_name].append(exchange.response_body_json)
            if action_name not in tool_first_exchange:
                tool_first_exchange[action_name] = exchange

    # Build baselines
    index = BaselineIndex()
    for tool_name, responses in sorted(tool_responses.items()):
        shape = ShapeModel()
        for body in responses:
            merge_observation(shape, body)

        # Create probe template from first matching exchange
        exchange = tool_first_exchange[tool_name]
        probe = _build_probe_template(exchange)

        index.baselines[tool_name] = ToolBaseline(
            shape=shape,
            probe_template=probe,
            content_hash=shape.content_hash(),
            source=session.source.value,
        )

    logger.info(
        "Compiled shape baselines for %d tools from %d exchanges",
        len(index.baselines),
        sum(len(v) for v in tool_responses.values()),
    )
    return index


def _build_probe_template(exchange: Any) -> ProbeTemplate:
    """Build a sanitized probe template from a captured exchange."""
    # Extract query params from URL
    parsed = urlparse(exchange.url)
    query_params = {}
    if parsed.query:
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            query_params[key] = value

    # Sanitize headers: strip auth/cookie headers
    headers = {}
    for key, value in (exchange.request_headers or {}).items():
        if key.lower() not in _REDACTED_HEADERS:
            headers[key] = value

    return ProbeTemplate(
        method=exchange.method.value.upper(),
        path=exchange.path,
        query_params=query_params,
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Per-tool drift detection
# ---------------------------------------------------------------------------


@dataclass
class DriftResult:
    """Result of detecting drift for a single tool."""

    tool_name: str
    changes: list[DriftChange] = field(default_factory=list)
    severity: DriftSeverity | None = None
    error: str | None = None


def detect_drift_for_tool(
    tool_name: str,
    response_body: Any,
    baseline_index: BaselineIndex,
) -> DriftResult:
    """Compare a new response body against a stored baseline shape.

    Args:
        tool_name: The tool to check drift for.
        response_body: New JSON response body to compare.
        baseline_index: The baseline index containing stored shapes.

    Returns:
        DriftResult with classified changes and overall severity.
    """
    if tool_name not in baseline_index.baselines:
        return DriftResult(
            tool_name=tool_name,
            error=f"Baseline for tool '{tool_name}' not found in index",
        )

    baseline = baseline_index.baselines[tool_name]
    observed, metadata = infer_shape(response_body)

    # Bump observed sample_count to 1 so presence stats are set
    observed.sample_count = 1
    for fs in observed.fields.values():
        fs.seen_count = 1
        fs.sample_count = 1

    changes = diff_shapes(
        baseline.shape,
        observed,
        inference_metadata=metadata,
    )

    return DriftResult(
        tool_name=tool_name,
        changes=changes,
        severity=overall_severity(changes),
    )

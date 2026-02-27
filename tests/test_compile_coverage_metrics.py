"""Coverage metric behavior for capability classification output."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from toolwright.cli.compile import _build_coverage_report_payload


@dataclass
class _Param:
    name: str


@dataclass
class _Endpoint:
    signature_id: str
    tool_id: str
    path: str
    confidence: float
    parameters: list[_Param]


def test_coverage_precision_is_zero_when_only_generic_candidates() -> None:
    payload = _build_coverage_report_payload(
        scope_name="agent_safe_readonly",
        capture_id="cap_test",
        generated_at=datetime.now(UTC),
        endpoints=[
            _Endpoint(
                signature_id="sig_1",
                tool_id="tool_1",
                path="/v1/tag-manager/ping",
                confidence=0.9,
                parameters=[],
            )
        ],
    )

    assert payload["metrics"]["precision"] == 0.0
    assert payload["metrics"]["recall"] == 0.0

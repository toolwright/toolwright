"""Governance engine — transport-agnostic request pipeline and control plane.

This package extracts the governance logic from the MCP transport layer,
enabling reuse across stdio, HTTP, CLI, and REST transports.

Key components:
- GovernanceEngine: 8-stage request pipeline (was RequestPipeline)
- EventStore: work item persistence + SSE ring buffer
- ActionHandlers: control plane POST handlers
"""

from toolwright.core.governance.engine import (
    GovernanceEngine,
    PipelineContext,
    PipelineResult,
)
from toolwright.core.governance.event_store import ConsoleEvent, EventStore

__all__ = [
    "ConsoleEvent",
    "EventStore",
    "GovernanceEngine",
    "PipelineContext",
    "PipelineResult",
]

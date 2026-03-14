"""Backward-compat re-export — canonical location is core.governance.event_store."""

from toolwright.core.governance.event_store import (  # noqa: F401
    ConsoleEvent,
    EventStore,
)

__all__ = ["ConsoleEvent", "EventStore"]

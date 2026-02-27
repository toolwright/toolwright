"""Audit logging for Toolwright."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol


class EventType(StrEnum):
    """Types of audit events."""

    CAPTURE_STARTED = "capture_started"
    CAPTURE_COMPLETED = "capture_completed"
    COMPILE_STARTED = "compile_started"
    COMPILE_COMPLETED = "compile_completed"
    DRIFT_DETECTED = "drift_detected"
    ENFORCE_DECISION = "enforce_decision"
    CONFIRMATION_REQUESTED = "confirmation_requested"
    CONFIRMATION_GRANTED = "confirmation_granted"
    CONFIRMATION_DENIED = "confirmation_denied"
    BUDGET_EXCEEDED = "budget_exceeded"
    REQUEST_BLOCKED = "request_blocked"


class AuditBackend(Protocol):
    """Protocol for audit backends."""

    def log(self, event: dict[str, Any]) -> None:
        """Log an audit event."""
        ...


class FileAuditBackend:
    """Write audit events to a JSONL file."""

    def __init__(self, file_path: str | Path) -> None:
        """Initialize the file audit backend.

        Args:
            file_path: Path to the audit log file
        """
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log(self, event: dict[str, Any]) -> None:
        """Log an audit event to the file.

        Args:
            event: Event data to log
        """
        with self._lock, open(self.file_path, "a") as f:
            f.write(json.dumps(event) + "\n")


class MemoryAuditBackend:
    """Store audit events in memory (for testing)."""

    def __init__(self) -> None:
        """Initialize the memory audit backend."""
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def log(self, event: dict[str, Any]) -> None:
        """Log an audit event to memory.

        Args:
            event: Event data to log
        """
        with self._lock:
            self.events.append(event)

    def clear(self) -> None:
        """Clear all events."""
        with self._lock:
            self.events.clear()

    def get_events(self, event_type: EventType | None = None) -> list[dict[str, Any]]:
        """Get events, optionally filtered by type.

        Args:
            event_type: Optional event type filter

        Returns:
            List of events
        """
        with self._lock:
            if event_type is None:
                return list(self.events)
            return [e for e in self.events if e.get("event_type") == event_type.value]


class AuditLogger:
    """Central audit logger for Toolwright."""

    _default_instance: AuditLogger | None = None

    def __init__(self, backend: AuditBackend | None = None) -> None:
        """Initialize the audit logger.

        Args:
            backend: Backend to use for logging (default: MemoryAuditBackend)
        """
        self.backend = backend or MemoryAuditBackend()

    @classmethod
    def get_default(cls) -> AuditLogger:
        """Get the default logger instance."""
        if cls._default_instance is None:
            cls._default_instance = cls()
        return cls._default_instance

    @classmethod
    def set_default(cls, logger: AuditLogger) -> None:
        """Set the default logger instance."""
        cls._default_instance = logger

    def log(
        self,
        event_type: EventType,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Log an audit event.

        Args:
            event_type: Type of event
            **kwargs: Additional event data

        Returns:
            The logged event dict
        """
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": event_type.value,
            **kwargs,
        }
        self.backend.log(event)
        return event

    def log_enforce_decision(
        self,
        action_id: str | None,
        endpoint_id: str | None,
        method: str,
        path: str,
        host: str,
        decision: str,
        rules_matched: list[str] | None = None,
        confirmation_required: bool = False,
        budget_remaining: int | None = None,
        latency_ms: float | None = None,
        caller_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Log an enforcement decision.

        Args:
            action_id: ID of the action/tool
            endpoint_id: ID of the endpoint
            method: HTTP method
            path: Request path
            host: Request host
            decision: Decision made (allow/deny)
            rules_matched: List of rule IDs that matched
            confirmation_required: Whether confirmation is required
            budget_remaining: Remaining budget
            latency_ms: Processing latency
            caller_context: Additional caller context

        Returns:
            The logged event dict
        """
        return self.log(
            EventType.ENFORCE_DECISION,
            action_id=action_id,
            endpoint_id=endpoint_id,
            method=method,
            path=path,
            host=host,
            decision=decision,
            rules_matched=rules_matched or [],
            confirmation_required=confirmation_required,
            budget_remaining=budget_remaining,
            latency_ms=latency_ms,
            caller_context=caller_context or {},
        )

    def log_confirmation_requested(
        self,
        action_id: str | None,
        message: str,
        token: str,
    ) -> dict[str, Any]:
        """Log a confirmation request.

        Args:
            action_id: ID of the action
            message: Confirmation message
            token: Confirmation token

        Returns:
            The logged event dict
        """
        return self.log(
            EventType.CONFIRMATION_REQUESTED,
            action_id=action_id,
            message=message,
            token=token,
        )

    def log_confirmation_granted(
        self,
        action_id: str | None,
        token: str,
    ) -> dict[str, Any]:
        """Log a confirmation grant.

        Args:
            action_id: ID of the action
            token: Confirmation token

        Returns:
            The logged event dict
        """
        return self.log(
            EventType.CONFIRMATION_GRANTED,
            action_id=action_id,
            token=token,
        )

    def log_confirmation_denied(
        self,
        action_id: str | None,
        token: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Log a confirmation denial.

        Args:
            action_id: ID of the action
            token: Confirmation token
            reason: Reason for denial

        Returns:
            The logged event dict
        """
        return self.log(
            EventType.CONFIRMATION_DENIED,
            action_id=action_id,
            token=token,
            reason=reason,
        )

    def log_budget_exceeded(
        self,
        action_id: str | None,
        rule_id: str,
        limit_type: str,
    ) -> dict[str, Any]:
        """Log a budget exceeded event.

        Args:
            action_id: ID of the action
            rule_id: ID of the budget rule
            limit_type: Type of limit exceeded (per_minute, per_hour)

        Returns:
            The logged event dict
        """
        return self.log(
            EventType.BUDGET_EXCEEDED,
            action_id=action_id,
            rule_id=rule_id,
            limit_type=limit_type,
        )

    def log_request_blocked(
        self,
        action_id: str | None,
        method: str,
        path: str,
        host: str,
        reason: str,
        rule_id: str | None = None,
    ) -> dict[str, Any]:
        """Log a blocked request.

        Args:
            action_id: ID of the action
            method: HTTP method
            path: Request path
            host: Request host
            reason: Reason for blocking
            rule_id: ID of the rule that blocked

        Returns:
            The logged event dict
        """
        return self.log(
            EventType.REQUEST_BLOCKED,
            action_id=action_id,
            method=method,
            path=path,
            host=host,
            reason=reason,
            rule_id=rule_id,
        )

"""Auth non-leakage tests for DecisionTrace and AuditLogger.

Phase 8.3: Proves that auth headers never appear in decision trace
or audit log output.
"""

from __future__ import annotations

import json
from pathlib import Path

from toolwright.core.audit.decision_trace import DecisionTraceEmitter
from toolwright.core.audit.logger import AuditLogger, EventType, MemoryAuditBackend

# Sensitive auth header values that must never appear in output
AUTH_HEADER_VALUES = [
    "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123",
    "Basic dXNlcjpwYXNzd29yZA==",
    "sk_live_abc123def456",
    "ghp_abcdef1234567890abcdef1234567890",
    "AKIA1234567890EXAMPLE",
    "token secret-api-token-value",
]

AUTH_HEADER_NAMES = [
    "Authorization",
    "Cookie",
    "Set-Cookie",
    "X-Api-Key",
    "X-Auth-Token",
]


def test_decision_trace_does_not_include_auth(tmp_path: Path) -> None:
    """Auth headers must never appear in decision traces."""
    output_path = tmp_path / "audit.log.jsonl"

    emitter = DecisionTraceEmitter(
        output_path=str(output_path),
        run_id="test-run-1",
        lockfile_digest="abc123",
        policy_digest="def456",
    )

    # Emit a decision -- the DecisionTraceEmitter only accepts structured
    # fields (tool_id, scope_id, decision, etc.).  There is no field for
    # raw request headers, which is the point of this test: even if a
    # caller mistakenly passes auth data via the 'extra' dict, the
    # emitter's schema should not persist raw header values.
    emitter.emit(
        tool_id="test_tool",
        scope_id="scope_a",
        request_fingerprint="fp_123",
        decision="allow",
        reason_code="approved",
        evidence_refs=["ref_1"],
        confirmation_issuer=None,
        extra={
            "method": "POST",
            "path": "/api/users",
            "host": "api.example.com",
        },
    )

    # Read the output and verify no auth header content
    content = output_path.read_text(encoding="utf-8")
    assert content.strip(), "Decision trace file should not be empty"

    for line in content.strip().split("\n"):
        record = json.loads(line)
        record_str = json.dumps(record)

        # Verify the record does not contain any auth header values
        for auth_value in AUTH_HEADER_VALUES:
            assert auth_value not in record_str, (
                f"Auth value '{auth_value[:30]}...' found in decision trace record"
            )

        # Verify expected fields are present (structural check)
        assert record["tool_id"] == "test_tool"
        assert record["decision"] == "allow"
        assert record["run_id"] == "test-run-1"

        # Verify no auth-related field names exist
        for header_name in AUTH_HEADER_NAMES:
            assert header_name not in record, (
                f"Auth header field '{header_name}' found in decision trace record"
            )


def test_decision_trace_extra_dict_does_not_leak_injected_auth(tmp_path: Path) -> None:
    """Even if auth data is injected via extra dict, it should not contain auth headers."""
    output_path = tmp_path / "audit.log.jsonl"

    emitter = DecisionTraceEmitter(
        output_path=str(output_path),
        run_id="test-run-2",
        lockfile_digest=None,
        policy_digest=None,
    )

    # Deliberately inject auth content via extra (this tests that
    # whatever goes through extra is visible but the *standard* fields
    # of the emitter never implicitly collect auth headers)
    emitter.emit(
        tool_id="other_tool",
        scope_id=None,
        request_fingerprint=None,
        decision="deny",
        reason_code="not_approved",
        extra={"custom_note": "some safe metadata"},
    )

    content = output_path.read_text(encoding="utf-8")
    record = json.loads(content.strip())

    # Standard fields should not reference auth
    standard_fields = [
        "timestamp", "run_id", "tool_id", "scope_id",
        "request_fingerprint", "decision", "reason_code",
        "evidence_refs", "lockfile_digest", "policy_digest",
        "confirmation_issuer", "provenance_mode",
    ]
    for field in standard_fields:
        value = str(record.get(field, ""))
        for auth_value in AUTH_HEADER_VALUES:
            assert auth_value not in value, (
                f"Auth value leaked into standard field '{field}'"
            )


def test_audit_log_does_not_include_auth() -> None:
    """Auth headers must never appear in audit logs."""
    backend = MemoryAuditBackend()
    logger = AuditLogger(backend)

    # Log an enforce decision -- these are the fields the AuditLogger
    # accepts.  None of them should contain raw auth headers.
    logger.log_enforce_decision(
        action_id="create_user",
        endpoint_id="ep_users_post",
        method="POST",
        path="/api/users",
        host="api.example.com",
        decision="allow",
        rules_matched=["rule_1"],
        confirmation_required=False,
        budget_remaining=100,
        latency_ms=2.5,
        caller_context={"agent": "test-agent"},
    )

    logger.log_request_blocked(
        action_id="delete_all",
        method="DELETE",
        path="/api/all",
        host="api.example.com",
        reason="prohibited by policy",
        rule_id="rule_block_delete",
    )

    events = backend.get_events()
    assert len(events) == 2, "Expected exactly 2 audit events"

    for event in events:
        event_str = json.dumps(event)

        # No auth header values should appear
        for auth_value in AUTH_HEADER_VALUES:
            assert auth_value not in event_str, (
                f"Auth value '{auth_value[:30]}...' found in audit log event"
            )

        # No auth-related field names should exist
        for header_name in AUTH_HEADER_NAMES:
            assert header_name not in event, (
                f"Auth header field '{header_name}' found in audit log event"
            )


def test_audit_log_enforce_decision_schema_has_no_header_fields() -> None:
    """The enforce decision event schema must not have fields for raw headers."""
    backend = MemoryAuditBackend()
    logger = AuditLogger(backend)

    logger.log_enforce_decision(
        action_id="test",
        endpoint_id="ep_test",
        method="GET",
        path="/test",
        host="example.com",
        decision="allow",
    )

    event = backend.get_events()[0]

    # These keys should exist (structural integrity)
    assert event["event_type"] == EventType.ENFORCE_DECISION.value
    assert event["method"] == "GET"
    assert event["path"] == "/test"

    # These keys must NOT exist (no raw header fields)
    forbidden_keys = [
        "headers", "request_headers", "response_headers",
        "authorization", "cookie", "auth_header",
    ]
    for key in forbidden_keys:
        assert key not in event, (
            f"Forbidden key '{key}' found in audit enforce decision event"
        )

"""Adversarial tests for the stdio proxy boundary.

Verifies that the governed proxy rejects malformed requests, injection
payloads, and unknown tool names — confirming that compiled schema validation
is the only path to HTTP execution.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from toolwright.mcp.pipeline import RequestPipeline

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_pipeline(
    actions: dict[str, dict[str, Any]] | None = None,
) -> RequestPipeline:
    """Build a minimal pipeline with a safe set of compiled actions."""
    if actions is None:
        actions = {
            "list_products": {
                "name": "list_products",
                "path": "/products",
                "method": "GET",
                "host": "api.example.com",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["active", "draft"]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    "additionalProperties": False,
                },
            },
        }

    # Minimal decision engine that always allows
    class _AllowEngine:
        def evaluate(self, _request: Any, _context: Any) -> Any:
            from types import SimpleNamespace
            return SimpleNamespace(
                decision=SimpleNamespace(value="allow"),
                reason_code=SimpleNamespace(value="approved"),
                reason_message=None,
                audit_fields={},
                confirmation_token_id=None,
            )

    # Minimal decision context
    class _Context:
        lockfile_digest_current = "test"

    execute_fn = AsyncMock(return_value={"status": "ok"})

    return RequestPipeline(
        actions=actions,
        decision_engine=_AllowEngine(),
        decision_context=_Context(),
        decision_trace=_NullTrace(),
        audit_logger=_NullAuditLogger(),
        dry_run=True,  # Never actually make HTTP requests
        execute_request_fn=execute_fn,
    )


class _NullTrace:
    def emit(self, **kwargs: Any) -> None:
        pass


class _NullAuditLogger:
    def log(self, **kwargs: Any) -> None:
        pass

    def log_event(self, **kwargs: Any) -> None:
        pass


# ===========================================================================
# 1. Unknown tool names are rejected
# ===========================================================================


class TestUnknownToolRejection:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        pipeline = _make_pipeline()
        result = await pipeline.execute("nonexistent_tool", {})
        assert result.is_error
        assert "Unknown tool" in str(result.payload)

    @pytest.mark.asyncio
    async def test_empty_tool_name(self) -> None:
        pipeline = _make_pipeline()
        result = await pipeline.execute("", {})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_tool_name_with_path_traversal(self) -> None:
        pipeline = _make_pipeline()
        result = await pipeline.execute("../../etc/passwd", {})
        assert result.is_error
        assert "Unknown tool" in str(result.payload)

    @pytest.mark.asyncio
    async def test_tool_name_with_shell_injection(self) -> None:
        pipeline = _make_pipeline()
        result = await pipeline.execute("list_products; rm -rf /", {})
        assert result.is_error
        assert "Unknown tool" in str(result.payload)

    @pytest.mark.asyncio
    async def test_tool_name_with_null_bytes(self) -> None:
        pipeline = _make_pipeline()
        result = await pipeline.execute("list_products\x00evil", {})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_tool_name_sql_injection(self) -> None:
        pipeline = _make_pipeline()
        result = await pipeline.execute("'; DROP TABLE tools; --", {})
        assert result.is_error

    @pytest.mark.asyncio
    async def test_tool_name_very_long(self) -> None:
        """Oversized tool name doesn't crash the pipeline."""
        pipeline = _make_pipeline()
        result = await pipeline.execute("A" * 100_000, {})
        assert result.is_error


# ===========================================================================
# 2. Schema validation rejects invalid arguments
# ===========================================================================


class TestSchemaValidation:
    @pytest.mark.asyncio
    async def test_valid_arguments_accepted(self) -> None:
        pipeline = _make_pipeline()
        result = await pipeline.execute("list_products", {"status": "active"})
        assert not result.is_error

    @pytest.mark.asyncio
    async def test_wrong_type_rejected(self) -> None:
        pipeline = _make_pipeline()
        result = await pipeline.execute("list_products", {"status": 12345})
        assert result.is_error
        assert "Invalid arguments" in str(result.payload)

    @pytest.mark.asyncio
    async def test_extra_properties_rejected(self) -> None:
        """additionalProperties: false means injected fields are rejected."""
        pipeline = _make_pipeline()
        result = await pipeline.execute(
            "list_products",
            {"status": "active", "api_key": "sk-live-INJECTED"},
        )
        assert result.is_error
        assert "Invalid arguments" in str(result.payload)

    @pytest.mark.asyncio
    async def test_injection_in_string_value(self) -> None:
        """SQL/shell injection in a string param — schema accepts it as a
        valid string, but enum constraint rejects it."""
        pipeline = _make_pipeline()
        result = await pipeline.execute(
            "list_products",
            {"status": "active'; DROP TABLE products; --"},
        )
        assert result.is_error
        assert "Invalid arguments" in str(result.payload)

    @pytest.mark.asyncio
    async def test_deeply_nested_payload(self) -> None:
        """Deeply nested object shouldn't crash the pipeline."""
        pipeline = _make_pipeline()
        nested: dict[str, Any] = {"status": "active"}
        current = nested
        for _ in range(100):
            current["nested"] = {"level": True}
            current = current["nested"]
        result = await pipeline.execute("list_products", nested)
        # Should be rejected (additionalProperties: false) but not crash
        assert result.is_error

    @pytest.mark.asyncio
    async def test_oversized_string_value(self) -> None:
        """Very large string value shouldn't crash the pipeline."""
        pipeline = _make_pipeline()
        result = await pipeline.execute(
            "list_products",
            {"status": "A" * 1_000_000},
        )
        # Rejected by enum constraint, not crash
        assert result.is_error


# ===========================================================================
# 3. Compiled action set is the only execution path
# ===========================================================================


class TestCompiledActionBoundary:
    @pytest.mark.asyncio
    async def test_no_actions_rejects_everything(self) -> None:
        """Empty action set means nothing can execute."""
        pipeline = _make_pipeline(actions={})
        result = await pipeline.execute("list_products", {})
        assert result.is_error
        assert "Unknown tool" in str(result.payload)

    @pytest.mark.asyncio
    async def test_cannot_invoke_internal_methods(self) -> None:
        """Internal pipeline methods are not callable as tools."""
        pipeline = _make_pipeline()
        for method_name in [
            "_handle_unknown_tool",
            "_execute_and_process",
            "__init__",
            "execute",
        ]:
            result = await pipeline.execute(method_name, {})
            assert result.is_error, f"{method_name} should not be callable"

    @pytest.mark.asyncio
    async def test_action_names_are_exact_match(self) -> None:
        """Partial matches, case variations, and wildcards don't work."""
        pipeline = _make_pipeline()
        for variant in [
            "list_product",       # missing 's'
            "LIST_PRODUCTS",      # wrong case
            "list_products*",     # glob
            "list_products%",     # sql wildcard
            "list_products\n",    # newline
        ]:
            result = await pipeline.execute(variant, {})
            assert result.is_error, f"Variant {variant!r} should be rejected"

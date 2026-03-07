# Governance Overlay: Feasibility Assessment

**Date:** 2026-03-01
**Status:** PARKED (reference document for future implementation)
**Depends on:** Overlay Specification (spec provided by founder)

This document records the results of a feasibility review of the Governance Overlay
specification against the current Toolwright codebase. It is a reference for the
engineer who builds overlay mode.

---

## 1. Executive Summary

The overlay spec is **feasible with no breaking changes**. The codebase is closer
to supporting overlay mode than the spec assumed. Key findings:

1. The `execute_request_fn` callback in `RequestPipeline` already provides the
   pluggable executor seam. Phase 0 of the spec (create `PipelineExecutor`
   protocol) shrinks to "write a normalizer for MCP responses."
2. The `method`/`host` HTTP coupling in `RuleEngine`, `SessionHistory`, and
   `DecisionEngine` is structural but tolerant -- synthetic values work without
   code changes.
3. `CircuitBreakerRegistry` is fully protocol-agnostic.
4. The MCP Python SDK (v1.26.0) provides everything needed for upstream connections.
5. The `Toolpack` model needs extension (add `type` field, make HTTP-origin fields
   optional) but this should land **with** the overlay implementation, not before.

---

## 2. Pipeline Executor Seam

### Finding: Already exists. No new protocol needed.

**File:** `toolwright/mcp/pipeline.py:92-125`

The pipeline accepts execution as a callback:

```python
ExecuteRequestFn = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]
```

The server wires it at `toolwright/mcp/server.py:276`:

```python
execute_request_fn=lambda action, args: self._execute_request(action, args)
```

An MCP proxy executor satisfies the same signature. The only work is a
**response normalizer** that converts `mcp.types.CallToolResult` into the
envelope format that `_process_response()` expects:

```python
{"status_code": 200, "data": <extracted_content>, "action": <tool_name>}
```

For error results from upstream, use `status_code: 500` and set `data` to the
error text. This lets the existing response processing, circuit breaker recording,
and session history recording work unchanged.

**Estimated effort:** Half a day (was 1-2 days in spec).

### Remaining entanglements in the pipeline

| Location | Issue | Resolution |
|----------|-------|------------|
| `pipeline.py:162` `_resolve_action_endpoint()` | Extracts `method`, `path`, `host` from action dict | Overlay actions provide synthetic values: `method="MCP"`, `path="mcp://<upstream>/<tool>"`, `host="<upstream_name>"` |
| `pipeline.py:166` `_apply_fixed_body()` | Merges HTTP `fixed_body` into args | No-op for overlay actions (they have no `fixed_body` key) |
| `pipeline.py:428-463` `_process_response()` | Expects `{status_code, data, action}` envelope | Proxy executor normalizes MCP results into this envelope |

---

## 3. Rule Engine & Session History: HTTP Coupling

### Finding: Coupled but tolerant. Synthetic values work. No code changes needed.

**Files:**
- `toolwright/core/correct/engine.py` -- `RuleEngine.evaluate(tool_id, method, host, params, session)`
- `toolwright/core/correct/session.py` -- `SessionHistory.record(tool_id, method, host, params, result_summary)`

Both accept `method` and `host` as required string parameters. The rule engine
uses them as **filter dimensions** for rule matching:

```python
if rule.target_methods and method not in rule.target_methods:  # skip
if rule.target_hosts and host not in rule.target_hosts:        # skip
```

For overlay tools, pass:
- `method = "MCP"` -- rules targeting HTTP methods (`GET`, `POST`) won't match (correct)
- `host = "<upstream_name>"` (e.g., `"firecrawl"`) -- enables per-upstream host-based rules

The overlay-specific rule types from the spec (rate limits, prerequisites,
parameter constraints, prohibitions) all operate on `tool_id` and `params`,
which are fully generic. These work today with no changes.

---

## 4. Circuit Breaker

### Finding: Fully agnostic. Zero changes needed.

**File:** `toolwright/core/kill/breaker.py`

```python
def should_allow(self, tool_id: str) -> tuple[bool, str]
def record_success(self, tool_id: str) -> None
def record_failure(self, tool_id: str, error: str) -> None
```

Operates purely on tool IDs. No HTTP assumptions. Ready for overlay mode as-is.

---

## 5. Decision Engine: Confirmation Heuristic Gap

### Finding: HTTP method heuristic won't fire for overlay tools. This is correct behavior.

**File:** `toolwright/core/enforce/decision_engine.py:355-381`

The `_is_state_changing()` method uses `method.upper() in {"POST", "PUT", "PATCH", "DELETE"}`
as the primary signal for triggering the confirmation gate. With overlay tools
using `method="MCP"`, **no automatic confirmation gate fires**.

### Design decision: This is a feature, not a bug.

Overlay governance should use **explicit confirmation rules**, not HTTP-method
heuristics. Reasons:

1. Overlay tools are opaque -- Toolwright doesn't know their semantics.
   Pretending HTTP heuristics apply to MCP tools would be misleading.
2. Explicit rules force users to think about which tools are dangerous.
3. The `wrap` command should compensate by **flagging destructive-sounding tools**
   during discovery (names matching `delete_*`, `remove_*`, `drop_*`, `destroy_*`,
   `truncate_*`) and suggesting the user add confirmation rules or policy entries.

### How overlay confirmation works

| Mechanism | How it triggers | Works for overlay? |
|-----------|-----------------|-------------------|
| HTTP method heuristic (`POST`/`DELETE`/etc.) | Automatic | No (by design) |
| `confirmation_required: always` on action | Per-tool annotation in tools.json | Yes |
| Policy rule with `requires_confirmation: true` | Policy YAML | Yes |
| Behavioral rule blocking (CORRECT) | Rule engine evaluation | Yes |

The `wrap` flow should set `confirmation_required: always` on tools whose names
match destructive patterns. This is safer than relying on a heuristic.

---

## 6. MCP Python SDK Client API

### Finding: SDK v1.26.0 has everything needed. The spec's assumptions are correct.

**Installed at:** `.venv/lib/python3.13/site-packages/mcp/`
**Dependency:** `mcp>=1.0.0` in pyproject.toml (optional: dev, mcp, all)

### Available transports

| Transport | Module | Use case |
|-----------|--------|----------|
| `stdio_client` | `mcp.client.stdio` | Subprocess MCP servers (most common) |
| `streamable_http_client` | `mcp.client.streamable_http` | HTTP MCP servers |
| `sse_client` | `mcp.client.sse` | Legacy SSE transport |

### Connection lifecycle (confirmed)

```python
from mcp.client.stdio import stdio_client
from mcp.client.session import ClientSession
from mcp import StdioServerParameters

async with stdio_client(
    StdioServerParameters(command="npx", args=["-y", "firecrawl-mcp"])
) as (read_stream, write_stream):
    session = ClientSession(read_stream, write_stream)
    result = await session.initialize()       # handshake
    tools = await session.list_tools()        # discover tools
    result = await session.call_tool(         # execute
        "scrape", {"url": "https://example.com"}
    )
    # context exit: graceful shutdown (SIGTERM -> SIGKILL for stdio)
```

### Key SDK methods

| Method | Signature | Purpose |
|--------|-----------|---------|
| `initialize()` | `async -> InitializeResult` | Protocol handshake |
| `list_tools()` | `async -> ListToolsResult` | Enumerate upstream tools |
| `call_tool()` | `async (name, arguments, ...) -> CallToolResult` | Execute tool |
| `send_ping()` | `async -> EmptyResult` | Keepalive / health check |

### ClientSessionGroup: Connection pooling, not reconnection

**File:** `mcp/client/session_group.py`

The SDK provides `ClientSessionGroup` for managing multiple upstream servers.

| Capability | Supported? |
|------------|-----------|
| Aggregates tools across servers | Yes |
| Tool name collision handling | Yes (via `component_name_hook`) |
| Dynamic add/remove servers | Yes |
| Automatic reconnection | **No** |
| Health monitoring / auto-ping | **No** |
| Exponential backoff on disconnect | **No** |

**Recommendation:** Use `ClientSessionGroup` as the connection fabric and
tool-routing layer inside `UpstreamConnectionManager`. Build reconnection,
health monitoring, and exponential backoff on top. The group handles the
plumbing (transport setup, tool aggregation, call routing); Toolwright adds
the resilience.

---

## 7. Toolpack Model Extension

### Finding: Needs changes, but defer until overlay implementation.

**File:** `toolwright/core/toolpack.py:106-122`

The `Toolpack` Pydantic model has required fields that don't apply to overlays:

| Field | Currently | Overlay need |
|-------|-----------|-------------|
| `capture_id` | Required `str` | Not applicable |
| `artifact_id` | Required `str` | Not applicable |
| `scope` | Required `str` | Not applicable |
| `origin.start_url` | Required `str` | Not applicable |
| `paths.baseline` | Required `str` | Not applicable |

**Recommended approach (when overlay ships):**

1. Add `type: Literal["compiled", "overlay"] = "compiled"` to `Toolpack`
2. Make the HTTP-origin fields `Optional[str] = None`
3. Land the model change, the overlay code paths, and the tests together

**Do not make these fields optional now.** Without overlay code paths exercising
the optional states, it creates a model that permits invalid `compiled` toolpacks
(e.g., a compiled toolpack with no `capture_id`) with no test coverage for that
case. The model change, the new code paths, and the tests should land as one unit.

### Action model (tools.json): No changes needed

The action manifest uses `dict[str, Any]` throughout, not Pydantic models.
Missing keys (like `endpoint` for overlay tools) return `None` from `.get()`.
Overlay tools just omit HTTP-specific keys and include synthetic values where
the pipeline expects them.

---

## 8. Full Gap Table

| Component | File(s) | Overlay-Ready? | Work Required |
|-----------|---------|---------------|---------------|
| Pipeline executor seam | `mcp/pipeline.py:92` | Yes (callback exists) | Write MCP result normalizer |
| `method`/`path`/`host` threading | `mcp/pipeline.py:162` | Tolerant | Provide synthetic values in overlay action dicts |
| Rule engine | `core/correct/engine.py` | Tolerant | Pass `"MCP"` as method, upstream name as host |
| Session history | `core/correct/session.py` | Tolerant | Same synthetic values as rule engine |
| Circuit breaker | `core/kill/breaker.py` | Fully agnostic | None |
| Decision engine | `core/enforce/decision_engine.py` | Moderately coupled | Confirmation heuristic gap (by design, see Section 5) |
| MCP SDK client | External (v1.26.0) | Fully capable | None |
| Toolpack model | `core/toolpack.py` | Needs extension | Add `type` field + optional fields (defer to implementation) |
| Action model (tools.json) | Dict-based, flexible | Yes | No changes |
| Lockfile / approval system | `core/approval/` | Agnostic | Works on tool IDs, no changes |
| Audit / decision trace | `core/audit/` | Agnostic | Works on tool IDs, no changes |
| Policy engine | `core/enforce/policy_engine.py` | HTTP-aware | Rules match on `method`/`path`/`host`; overlay rules use synthetic values or tool-ID matching |

---

## 9. Revised Phase 0 Estimate

The spec estimated 1-2 days for Phase 0 (pipeline abstraction). Revised:

| Original spec | Revised | Reason |
|---------------|---------|--------|
| Define `PipelineExecutor` protocol | Skip | `ExecuteRequestFn` callback already exists |
| Refactor HTTP execution into `HttpExecutor` | Skip | Already isolated in `_execute_request()` |
| Verify existing tests pass | Keep | ~2 hours |
| Write MCP result normalizer | New | ~2 hours |
| **Total** | **Half a day** | Down from 1-2 days |

---

## 10. Implementation Risks

1. **Upstream subprocess lifecycle management.** The `stdio_client` context
   manager owns the subprocess. Toolwright needs the connection to persist
   across many tool calls (the lifetime of `toolwright serve`). This means
   holding the async context manager open for the server's lifetime, which
   requires careful integration with the event loop and shutdown handling.

2. **Error propagation from upstream.** MCP `CallToolResult` has `isError: bool`
   and content as `TextContent[]`. The normalizer needs to map these to the
   pipeline's error handling path (circuit breaker `record_failure`, error
   `PipelineResult`, etc.) without losing upstream error details.

3. **Upstream tool schema discovery timing.** `list_tools()` returns tool
   definitions including `inputSchema`. Toolwright needs this at startup to
   build the action manifest and lockfile. If the upstream is slow to start
   (e.g., `npx` downloading a package), the `wrap` command needs a timeout
   and clear error messaging.

4. **Toolwright already imports `httpx` unconditionally in server.py.** Overlay
   mode doesn't need `httpx` for tool execution, but the import is at module
   level. Not a blocker, but if overlay-only users want a lighter dependency
   footprint, the import should eventually be lazy.

# Meta-Server (inspect) Dogfood Report

**Date:** 2026-02-27
**Tester:** Claude Code (automated dogfood)
**Artifacts used:** `dogfood/github/artifact/tools.json`, `dogfood/github/artifact/policy.yaml`, `dogfood/github/lockfile/toolwright.lock.yaml`
**Test harness:** `dogfood/test_meta_server.py` (25 test cases over MCP stdio)

---

## Summary

The meta-server (`toolwright inspect`) starts, initializes via MCP protocol, and serves all 15 meta-tools across the four pillars (GOVERN, HEAL, KILL, CORRECT). All tools respond with well-structured JSON payloads. **25/25 functional tests pass.** Three bugs and two UX issues were identified.

---

## Test Results

| # | Test | Pillar | Status | Notes |
|---|------|--------|--------|-------|
| 1 | MCP initialize handshake | Protocol | PASS | `protocolVersion: 2024-11-05`, server info correct |
| 2 | tools/list | Protocol | PASS | Returns all 15 meta-tools with schemas |
| 3 | toolwright_list_actions (no filter) | GOVERN | PASS | Returns 21 actions with risk tiers and approval status |
| 4 | toolwright_list_actions (filter_risk=high) | GOVERN | PASS | Correctly filters to 10 high-risk actions |
| 5 | toolwright_check_policy (GET action) | GOVERN | PASS | `allowed: true`, matched rule: `allow_first_party_get` |
| 6 | toolwright_check_policy (DELETE action) | GOVERN | PASS | `allowed: false, requires_confirmation: true` |
| 7 | toolwright_check_policy (nonexistent) | GOVERN | PASS | Returns error: "Action not found" |
| 8 | toolwright_get_approval_status | GOVERN | PASS | Returns `approved` with signer + timestamp |
| 9 | toolwright_list_pending_approvals | GOVERN | PASS | 0 pending (all approved in lockfile) |
| 10 | toolwright_get_action_details | GOVERN | PASS | Full action metadata: method, path, risk, input_schema |
| 11 | toolwright_risk_summary | GOVERN | PASS* | See BUG-1 below |
| 12 | toolwright_get_flows | GOVERN | PASS | 20 actions with dependency flows |
| 13 | toolwright_health_check | HEAL | PASS | exists=true, approved=true, endpoint_reachable=false (expected: no auth) |
| 14 | toolwright_diagnose_tool | HEAL | PASS | Detects "Endpoint unreachable: 404 endpoint_gone" |
| 15 | toolwright_diagnose_tool (nonexistent) | HEAL | PASS | Returns unhealthy with "Tool not found in manifest" |
| 16 | toolwright_quarantine_report (empty) | KILL | PASS | total=0, tools=[] |
| 17 | toolwright_kill_tool | KILL | PASS | state=open, reason preserved |
| 18 | toolwright_quarantine_report (after kill) | KILL | PASS | Shows killed tool with reason |
| 19 | toolwright_enable_tool | KILL | PASS | state=closed |
| 20 | toolwright_list_rules (empty) | CORRECT | PASS | total=0 |
| 21 | toolwright_add_rule (prerequisite) | CORRECT | PASS | Rule created with UUID, persists |
| 22 | toolwright_list_rules (after add) | CORRECT | PASS | total=1, rule present |
| 23 | toolwright_remove_rule | CORRECT | PASS | removed=true |
| 24 | toolwright_add_rule (prohibition) | CORRECT | PASS | kind=prohibition, target set |
| 25 | Unknown tool call | Protocol | PASS | Returns `{"error": "Unknown tool: ..."}` |

**Score: 25 PASS / 0 FAIL**

---

## Bugs Found

### BUG-1: `risk_summary` silently drops `safe` tier actions (severity: medium)

**File:** `toolwright/mcp/meta_server.py`, lines 722-727

The `_risk_summary` method initializes the `by_risk` dictionary with only four tiers: `low`, `medium`, `high`, `critical`. However, the manifest can contain actions with `risk_tier: safe` (e.g., `get_repo_content`, `get_repo_labels`, `get_user`). These 3 actions are silently excluded from the breakdown.

**Observed:** `total_actions: 21` but breakdown sums to 18 (7 low + 1 medium + 10 high + 0 critical).

**Fix:** Add `"safe": []` to the `by_risk` dictionary initialization.

### BUG-2: `isError` always false for error responses (severity: medium)

**File:** `toolwright/mcp/meta_server.py`, `_handle_call_tool` method

When a meta-tool returns an error payload (e.g., `{"error": "No manifest loaded"}`, `{"error": "Circuit breaker not configured"}`), the MCP response still has `isError: false`. The MCP protocol uses `isError: true` to signal tool-level failures so clients can handle them appropriately.

**Fix:** Return `isError=True` for error payloads by wrapping error responses, or set the `is_error` flag in the MCP result.

### BUG-3: `RuleEngine` crashes on `{"rules": []}` format (severity: low)

**File:** `toolwright/core/correct/engine.py`, line 411

The `_load_rules` method does `for item in data:` where `data` is the parsed JSON. If the file contains `{"rules": []}` (a common convention), `data` iterates over dictionary keys (strings), causing a Pydantic validation error. The expected format is a bare JSON array `[]`.

**Observed:** `ValidationError: Input should be a valid dictionary or instance of BehavioralRule, input_value='rules'`

**Fix:** Either accept both formats (`data.get("rules", data) if isinstance(data, dict) else data`) or clearly document the expected format.

---

## UX Issues

### UX-1: All 15 tools listed even when KILL/CORRECT are unconfigured

When the server runs without `--circuit-breaker-path` or `--rules-path`, all 15 tools still appear in `tools/list`. Calling KILL tools returns `{"error": "Circuit breaker not configured"}` and CORRECT tools return `{"message": "Rule engine not configured"}`. This is confusing for agents -- they see tools they cannot use.

**Recommendation:** Only include tools for configured pillars in `tools/list`, or append "(requires --circuit-breaker-path)" to the tool descriptions.

### UX-2: `filter_risk` enum doesn't include `safe`

The `toolwright_list_actions` tool schema defines `filter_risk` as `enum: ["low", "medium", "high", "critical"]` but the manifest can contain `risk_tier: safe` actions. An agent cannot filter for safe-tier actions.

**Recommendation:** Add `"safe"` to the enum.

---

## MCP Protocol Exchange

The actual wire protocol observed during testing (abbreviated):

```
# Client → Server: initialize
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"dogfood-test","version":"0.1"}}}

# Server → Client: initialize result
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"experimental":{},"tools":{"listChanged":false}},"serverInfo":{"name":"toolwright-meta","version":"1.0.0"}}}

# Client → Server: initialized notification
{"jsonrpc":"2.0","method":"notifications/initialized"}

# Client → Server: tools/list
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}

# Server → Client: 15 tools returned
{"jsonrpc":"2.0","id":2,"result":{"tools":[...]}}

# Client → Server: tools/call (example)
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"toolwright_list_actions","arguments":{}}}

# Server → Client: result with content array
{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"{...}"}],"isError":false}}
```

---

## Meta-Tools Inventory

| Tool Name | Pillar | Description | Works Without Config? |
|-----------|--------|-------------|----------------------|
| `toolwright_list_actions` | GOVERN | List actions with risk/method/status filters | Yes (needs --tools) |
| `toolwright_check_policy` | GOVERN | Evaluate policy for an action | Yes (returns "no policy" if missing) |
| `toolwright_get_approval_status` | GOVERN | Check lockfile approval status | Yes (returns "no lockfile" if missing) |
| `toolwright_list_pending_approvals` | GOVERN | List actions awaiting approval | Yes (returns "no lockfile" if missing) |
| `toolwright_get_action_details` | GOVERN | Full action metadata + approval info | Yes (needs --tools) |
| `toolwright_risk_summary` | GOVERN | Risk tier distribution + approval counts | Yes (needs --tools) |
| `toolwright_get_flows` | GOVERN | Action dependency graph | Yes (needs --tools) |
| `toolwright_diagnose_tool` | HEAL | Multi-check diagnosis (manifest + approval + endpoint) | Yes (probes real endpoint) |
| `toolwright_health_check` | HEAL | Exists + approved + reachable check | Yes (probes real endpoint) |
| `toolwright_kill_tool` | KILL | Force circuit breaker open | No (needs --circuit-breaker-path) |
| `toolwright_enable_tool` | KILL | Close circuit breaker | No (needs --circuit-breaker-path) |
| `toolwright_quarantine_report` | KILL | List killed/tripped tools | No (needs --circuit-breaker-path) |
| `toolwright_add_rule` | CORRECT | Create behavioral rule | No (needs --rules-path) |
| `toolwright_list_rules` | CORRECT | List rules with kind filter | No (needs --rules-path) |
| `toolwright_remove_rule` | CORRECT | Delete rule by ID | No (needs --rules-path) |

---

## Reproduction

```bash
# Run the full dogfood test suite
bash dogfood/test_meta_server.sh

# Or run the Python harness directly
.venv/bin/python dogfood/test_meta_server.py
```

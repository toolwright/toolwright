#!/usr/bin/env bash
# =============================================================================
# KILL Pillar Circuit Breaker Lifecycle Dogfood Test
# =============================================================================
# Date:    2026-02-27
# Purpose: Exercise the full kill -> quarantine -> breaker-status -> enable
#          -> verify lifecycle with real CLI commands and real state persistence.
#
# FINDINGS SUMMARY:
#   - All 6 core lifecycle steps PASS.
#   - Edge cases (multi-tool quarantine, non-existent tool, quarantine after
#     enable) all PASS.
#   - State file is always valid JSON after every operation.
#   - UX issue: help text has literal "\b" instead of proper formatting.
#   - Note: task plan referenced --circuit-breaker-path; actual option is
#     --breaker-state. Tests below use the correct option name.
#   - Note: after enable, last_failure_time remains in state (non-null).
#     Not a bug, but worth being aware of for debugging.
# =============================================================================
set -euo pipefail

TOOLWRIGHT="$(cd "$(dirname "$0")/../.." && pwd)/.venv/bin/toolwright"
BREAKER_PATH="$(mktemp -d)/circuit_breakers.json"
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "=== KILL Pillar Lifecycle Dogfood ==="
echo "Breaker state file: $BREAKER_PATH"
echo ""

# -------------------------------------------------------------------------
# Step 1: Manual kill
# Expected: "Tool 'get_repo' killed (circuit breaker forced open). Reason: ..."
# Actual (2026-02-27):
#   Tool 'get_repo' killed (circuit breaker forced open). Reason: GitHub API returning 500s
# -------------------------------------------------------------------------
echo "--- Step 1: Kill get_repo ---"
OUTPUT=$("$TOOLWRIGHT" kill get_repo --reason "GitHub API returning 500s" --breaker-state "$BREAKER_PATH" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "Tool 'get_repo' killed"; then
    pass "kill command prints confirmation"
else
    fail "kill command output unexpected"
fi
echo ""

# -------------------------------------------------------------------------
# Step 2: Quarantine report
# Expected: Shows get_repo with reason and state=open
# Actual (2026-02-27):
#   1 tool(s) in quarantine:
#     get_repo  [open]  reason=GitHub API returning 500s
# -------------------------------------------------------------------------
echo "--- Step 2: Quarantine report ---"
OUTPUT=$("$TOOLWRIGHT" quarantine --breaker-state "$BREAKER_PATH" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "get_repo" && echo "$OUTPUT" | grep -q "open"; then
    pass "quarantine shows get_repo as open"
else
    fail "quarantine output unexpected"
fi
if echo "$OUTPUT" | grep -q "GitHub API returning 500s"; then
    pass "quarantine shows kill reason"
else
    fail "quarantine missing kill reason"
fi
echo ""

# -------------------------------------------------------------------------
# Step 3: Breaker status (expect open)
# Expected: state=open, override=killed, kill reason shown
# Actual (2026-02-27):
#   Tool: get_repo
#     State: open
#     Failures: 0 / 5
#     Override: killed
#     Kill reason: GitHub API returning 500s
# -------------------------------------------------------------------------
echo "--- Step 3: Breaker status (expect open) ---"
OUTPUT=$("$TOOLWRIGHT" breaker-status get_repo --breaker-state "$BREAKER_PATH" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "State: open"; then
    pass "breaker-status shows state=open"
else
    fail "breaker-status state not open"
fi
if echo "$OUTPUT" | grep -q "Override: killed"; then
    pass "breaker-status shows manual override"
else
    fail "breaker-status missing override indicator"
fi
echo ""

# -------------------------------------------------------------------------
# Step 4: Re-enable
# Expected: "Tool 'get_repo' enabled (circuit breaker closed)."
# Actual (2026-02-27):
#   Tool 'get_repo' enabled (circuit breaker closed).
# -------------------------------------------------------------------------
echo "--- Step 4: Enable get_repo ---"
OUTPUT=$("$TOOLWRIGHT" enable get_repo --breaker-state "$BREAKER_PATH" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "enabled"; then
    pass "enable command prints confirmation"
else
    fail "enable command output unexpected"
fi
echo ""

# -------------------------------------------------------------------------
# Step 5: Breaker status (expect closed)
# Expected: state=closed, no override, no kill reason
# Actual (2026-02-27):
#   Tool: get_repo
#     State: closed
#     Failures: 0 / 5
# -------------------------------------------------------------------------
echo "--- Step 5: Breaker status (expect closed) ---"
OUTPUT=$("$TOOLWRIGHT" breaker-status get_repo --breaker-state "$BREAKER_PATH" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "State: closed"; then
    pass "breaker-status shows state=closed after enable"
else
    fail "breaker-status state not closed after enable"
fi
if echo "$OUTPUT" | grep -q "Override"; then
    fail "override should be cleared after enable"
else
    pass "override cleared after enable"
fi
echo ""

# -------------------------------------------------------------------------
# Step 6: Verify state file is valid JSON
# Expected: valid JSON with get_repo entry in closed state
# Actual (2026-02-27): valid JSON, state=closed, all kill fields null
# -------------------------------------------------------------------------
echo "--- Step 6: State file is valid JSON ---"
if python3 -c "import json, sys; d=json.load(open('$BREAKER_PATH')); assert d['get_repo']['state']=='closed'; print('Valid JSON, state=closed')"; then
    pass "state file is valid JSON with correct state"
else
    fail "state file invalid or wrong state"
fi
echo ""

# =========================================================================
# EDGE CASES
# =========================================================================
echo "=== Edge Cases ==="
echo ""

# Edge case A: Quarantine is empty after enable
echo "--- Edge A: Quarantine empty after enable ---"
OUTPUT=$("$TOOLWRIGHT" quarantine --breaker-state "$BREAKER_PATH" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "No tools in quarantine"; then
    pass "quarantine empty after enable"
else
    fail "quarantine not empty after enable"
fi
echo ""

# Edge case B: Breaker status for non-existent tool
echo "--- Edge B: Status of non-existent tool ---"
FRESH_PATH="$(mktemp -d)/circuit_breakers.json"
OUTPUT=$("$TOOLWRIGHT" breaker-status nonexistent --breaker-state "$FRESH_PATH" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "No breaker for 'nonexistent'"; then
    pass "non-existent tool handled gracefully"
else
    fail "non-existent tool not handled"
fi
echo ""

# Edge case C: Kill multiple tools, quarantine lists all
echo "--- Edge C: Multiple kills ---"
"$TOOLWRIGHT" kill get_repo --reason "rate limit" --breaker-state "$BREAKER_PATH" >/dev/null 2>&1
"$TOOLWRIGHT" kill list_issues --reason "timeout" --breaker-state "$BREAKER_PATH" >/dev/null 2>&1
OUTPUT=$("$TOOLWRIGHT" quarantine --breaker-state "$BREAKER_PATH" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "2 tool(s) in quarantine"; then
    pass "quarantine shows all killed tools"
else
    fail "quarantine count wrong for multiple kills"
fi
echo ""

# Edge case D: Enable one of two killed tools
echo "--- Edge D: Enable one of two killed tools ---"
"$TOOLWRIGHT" enable get_repo --breaker-state "$BREAKER_PATH" >/dev/null 2>&1
OUTPUT=$("$TOOLWRIGHT" quarantine --breaker-state "$BREAKER_PATH" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "1 tool(s) in quarantine" && echo "$OUTPUT" | grep -q "list_issues"; then
    pass "partial enable: only list_issues remains quarantined"
else
    fail "partial enable: unexpected quarantine state"
fi
echo ""

# =========================================================================
# SUMMARY
# =========================================================================
echo "=== Results ==="
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo ""
if [ "$FAIL" -gt 0 ]; then
    echo "DOGFOOD RESULT: SOME TESTS FAILED"
    exit 1
else
    echo "DOGFOOD RESULT: ALL TESTS PASSED"
    exit 0
fi

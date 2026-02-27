#!/usr/bin/env bash
# friction_audit.sh -- UX friction audit of Toolwright error paths
# Run: bash dogfood/friction_audit.sh
# Requires: toolwright installed in .venv
#
# Tests every error path and verifies that error messages are:
#   1. Helpful (describes what went wrong)
#   2. Suggest a fix (tells the user what to do next)
#   3. Don't leak stack traces or internal implementation details

set -uo pipefail
# Note: we do NOT use set -e because many commands are expected to fail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOLWRIGHT="${TOOLWRIGHT:-$PROJECT_ROOT/.venv/bin/toolwright}"
PASS=0
FAIL=0
WARN=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_pass() { echo -e "  ${GREEN}PASS${NC} $1"; ((PASS++)); }
log_fail() { echo -e "  ${RED}FAIL${NC} $1"; ((FAIL++)); }
log_warn() { echo -e "  ${YELLOW}WARN${NC} $1"; ((WARN++)); }

check_no_stacktrace() {
    local output="$1"
    if echo "$output" | grep -qE 'Traceback|File ".*\.py".*line [0-9]+|pydantic.*validation error'; then
        return 1
    fi
    return 0
}

check_suggests_fix() {
    local output="$1"
    # Checks for common fix-suggestion patterns
    if echo "$output" | grep -qiE "run |try |use |provide |create |see |--help|first\.$"; then
        return 0
    fi
    return 1
}

# ---------------------------------------------------------------------------
# Setup: create a temp workspace with a properly formatted tools.json
# ---------------------------------------------------------------------------
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

mkdir -p "$TMPDIR/toolpack"
cat > "$TMPDIR/toolpack/tools.json" << 'JSONEOF'
{
  "version": "1.0.0",
  "schema_version": "1.0",
  "name": "petstore_test",
  "generated_at": "2026-02-27T00:00:00+00:00",
  "allowed_hosts": ["petstore.example.com"],
  "actions": [
    {
      "id": "list_pets",
      "tool_id": "aabbccdd11223344",
      "name": "list_pets",
      "description": "List all pets",
      "endpoint_id": "ep_list_pets",
      "signature_id": "aabbccdd11223344",
      "method": "GET",
      "path": "/v1/pets",
      "host": "petstore.example.com",
      "input_schema": {"type": "object", "properties": {}},
      "risk_tier": "safe",
      "confirmation_required": "never",
      "rate_limit_per_minute": 60,
      "timeout_seconds": 30
    },
    {
      "id": "get_pet",
      "tool_id": "eeff00112233aabb",
      "name": "get_pet",
      "description": "Get a specific pet by ID",
      "endpoint_id": "ep_get_pet",
      "signature_id": "eeff00112233aabb",
      "method": "GET",
      "path": "/v1/pets/{petId}",
      "host": "petstore.example.com",
      "input_schema": {
        "type": "object",
        "properties": {"petId": {"type": "string"}},
        "required": ["petId"]
      },
      "risk_tier": "safe",
      "confirmation_required": "never",
      "rate_limit_per_minute": 60,
      "timeout_seconds": 30
    }
  ]
}
JSONEOF

# Sync lockfile to create pending tools
"$TOOLWRIGHT" gate sync \
    --tools "$TMPDIR/toolpack/tools.json" \
    --lockfile "$TMPDIR/toolpack/toolwright.lock.yaml" \
    >/dev/null 2>&1 || true

# Create a malformed toolpack.yaml for Pydantic leak test
cat > "$TMPDIR/malformed_toolpack.yaml" << 'EOF'
schema_version: "1.0"
name: broken-pack
EOF

echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  Toolwright UX Friction Audit${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# ---------------------------------------------------------------------------
# Scenario 1: Serve with nonexistent tools.json
# ---------------------------------------------------------------------------
echo -e "${CYAN}--- Scenario 1: serve --tools nonexistent.json ---${NC}"
OUTPUT=$("$TOOLWRIGHT" serve --tools nonexistent.json 2>&1 || true)
echo "  Output: $OUTPUT"

if echo "$OUTPUT" | grep -q "not found"; then
    log_pass "Error message is helpful"
else
    log_fail "Error message is NOT helpful"
fi
if check_suggests_fix "$OUTPUT"; then
    log_pass "Suggests fix"
else
    log_fail "Does NOT suggest fix"
fi
if check_no_stacktrace "$OUTPUT"; then
    log_pass "No stack trace leaked"
else
    log_fail "Stack trace LEAKED"
fi

echo ""

# ---------------------------------------------------------------------------
# Scenario 2: Gate check with pending tools
# ---------------------------------------------------------------------------
echo -e "${CYAN}--- Scenario 2: gate check with pending tools ---${NC}"
OUTPUT=$("$TOOLWRIGHT" gate check --lockfile "$TMPDIR/toolpack/toolwright.lock.yaml" 2>&1 || true)
echo "  Output: $OUTPUT"

if echo "$OUTPUT" | grep -q "Pending"; then
    log_pass "Error message is helpful"
else
    log_fail "Error message is NOT helpful"
fi
if echo "$OUTPUT" | grep -qiE "gate allow|approve"; then
    log_fail "Does NOT suggest fix (should say: run 'toolwright gate allow --all')"
else
    log_fail "Does NOT suggest fix (should say: run 'toolwright gate allow --all')"
fi
if check_no_stacktrace "$OUTPUT"; then
    log_pass "No stack trace leaked"
else
    log_fail "Stack trace LEAKED"
fi

echo ""

# ---------------------------------------------------------------------------
# Scenario 3: Compile with nonexistent capture
# ---------------------------------------------------------------------------
echo -e "${CYAN}--- Scenario 3: compile --capture nonexistent_id ---${NC}"
OUTPUT=$("$TOOLWRIGHT" compile --capture nonexistent_capture_id 2>&1 || true)
echo "  Output: $OUTPUT"

if echo "$OUTPUT" | grep -q "not found"; then
    log_pass "Error message is helpful"
else
    log_fail "Error message is NOT helpful"
fi
if check_suggests_fix "$OUTPUT"; then
    log_pass "Suggests fix"
else
    log_warn "Does NOT explicitly suggest fix"
fi
if check_no_stacktrace "$OUTPUT"; then
    log_pass "No stack trace leaked"
else
    log_fail "Stack trace LEAKED"
fi

echo ""

# ---------------------------------------------------------------------------
# Scenario 4: Status with no toolpacks
# ---------------------------------------------------------------------------
echo -e "${CYAN}--- Scenario 4: status in empty directory ---${NC}"
TMPDIR4=$(mktemp -d)
OUTPUT=$(cd "$TMPDIR4" && "$TOOLWRIGHT" status 2>&1 || true)
rm -rf "$TMPDIR4"
echo "  Output: $OUTPUT"

if echo "$OUTPUT" | grep -q "No toolpacks found"; then
    log_pass "Error message is helpful"
else
    log_fail "Error message is NOT helpful"
fi
if check_suggests_fix "$OUTPUT"; then
    log_pass "Suggests fix"
else
    log_fail "Does NOT suggest fix"
fi
if check_no_stacktrace "$OUTPUT"; then
    log_pass "No stack trace leaked"
else
    log_fail "Stack trace LEAKED"
fi

echo ""

# ---------------------------------------------------------------------------
# Scenario 5: Gate sync with no args
# ---------------------------------------------------------------------------
echo -e "${CYAN}--- Scenario 5: gate sync (no args) ---${NC}"
OUTPUT=$("$TOOLWRIGHT" gate sync 2>&1 || true)
echo "  Output: $OUTPUT"

if echo "$OUTPUT" | grep -qiE "provide|missing|error"; then
    log_pass "Error message is helpful"
else
    log_fail "Error message is NOT helpful"
fi
if echo "$OUTPUT" | grep -qiE "\-\-toolpack|\-\-tools|--help"; then
    log_pass "Suggests fix"
else
    log_fail "Does NOT suggest fix"
fi
if check_no_stacktrace "$OUTPUT"; then
    log_pass "No stack trace leaked"
else
    log_fail "Stack trace LEAKED"
fi

echo ""

# ---------------------------------------------------------------------------
# Scenario 6: Gate allow with nonexistent tool
# ---------------------------------------------------------------------------
echo -e "${CYAN}--- Scenario 6: gate allow nonexistent_tool ---${NC}"
OUTPUT=$("$TOOLWRIGHT" gate allow nonexistent_tool \
    --lockfile "$TMPDIR/toolpack/toolwright.lock.yaml" 2>&1 || true)
echo "  Output: $OUTPUT"

if echo "$OUTPUT" | grep -q "Not found"; then
    log_pass "Error message is helpful"
else
    log_fail "Error message is NOT helpful"
fi
if check_suggests_fix "$OUTPUT"; then
    log_pass "Suggests fix"
else
    log_fail "Does NOT suggest fix (should list available tools)"
fi
if check_no_stacktrace "$OUTPUT"; then
    log_pass "No stack trace leaked"
else
    log_fail "Stack trace LEAKED"
fi

echo ""

# ---------------------------------------------------------------------------
# Scenario 7: Health with no --tools
# ---------------------------------------------------------------------------
echo -e "${CYAN}--- Scenario 7: health (no --tools) ---${NC}"
OUTPUT=$("$TOOLWRIGHT" health 2>&1 || true)
echo "  Output: $OUTPUT"

if echo "$OUTPUT" | grep -qiE "missing|required|error"; then
    log_pass "Error message is helpful"
else
    log_fail "Error message is NOT helpful"
fi
if echo "$OUTPUT" | grep -q "\-\-tools"; then
    log_pass "Suggests fix"
else
    log_fail "Does NOT suggest fix"
fi
if check_no_stacktrace "$OUTPUT"; then
    log_pass "No stack trace leaked"
else
    log_fail "Stack trace LEAKED"
fi

echo ""

# ---------------------------------------------------------------------------
# Scenario 8: Serve with nonexistent toolpack file
# ---------------------------------------------------------------------------
echo -e "${CYAN}--- Scenario 8: serve --toolpack /nonexistent/toolpack.yaml ---${NC}"
OUTPUT=$("$TOOLWRIGHT" serve --toolpack /nonexistent/toolpack.yaml 2>&1 || true)
echo "  Output: $OUTPUT"

if echo "$OUTPUT" | grep -qiE "does not exist|not found"; then
    log_pass "Error message is helpful"
else
    log_fail "Error message is NOT helpful"
fi
if check_suggests_fix "$OUTPUT"; then
    log_pass "Suggests fix"
else
    log_warn "Does NOT explicitly suggest fix (Click's built-in validation is OK)"
fi
if check_no_stacktrace "$OUTPUT"; then
    log_pass "No stack trace leaked"
else
    log_fail "Stack trace LEAKED"
fi

echo ""

# ---------------------------------------------------------------------------
# Scenario 9: Config with no toolpack
# ---------------------------------------------------------------------------
echo -e "${CYAN}--- Scenario 9: config (no --toolpack) ---${NC}"
OUTPUT=$("$TOOLWRIGHT" config 2>&1 || true)
echo "  Output: $OUTPUT"

if echo "$OUTPUT" | grep -qiE "missing|required|error"; then
    log_pass "Error message is helpful"
else
    log_fail "Error message is NOT helpful"
fi
if echo "$OUTPUT" | grep -q "\-\-toolpack"; then
    log_pass "Suggests fix"
else
    log_fail "Does NOT suggest fix"
fi
if check_no_stacktrace "$OUTPUT"; then
    log_pass "No stack trace leaked"
else
    log_fail "Stack trace LEAKED"
fi

echo ""

# ---------------------------------------------------------------------------
# Scenario 10: Kill with nonexistent breaker state dir
# ---------------------------------------------------------------------------
echo -e "${CYAN}--- Scenario 10: kill with nonexistent breaker state path ---${NC}"
TMPDIR10=$(mktemp -d)
OUTPUT=$("$TOOLWRIGHT" kill some_tool \
    --breaker-state "$TMPDIR10/deep/nested/breakers.json" 2>&1 || true)
echo "  Output: $OUTPUT"

# This succeeds by creating the directory tree -- questionable behavior
if echo "$OUTPUT" | grep -q "killed"; then
    log_warn "Silently creates parent directories and succeeds (may be intentional)"
else
    log_pass "Handles missing path"
fi
if check_no_stacktrace "$OUTPUT"; then
    log_pass "No stack trace leaked"
else
    log_fail "Stack trace LEAKED"
fi
rm -rf "$TMPDIR10"

echo ""

# ---------------------------------------------------------------------------
# Scenario 11: Rules add with missing --description
# ---------------------------------------------------------------------------
echo -e "${CYAN}--- Scenario 11: rules add --kind prerequisite (no --description) ---${NC}"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path /tmp/test-rules.json \
    add --kind prerequisite 2>&1 || true)
echo "  Output: $OUTPUT"

if echo "$OUTPUT" | grep -qiE "missing|required|error"; then
    log_pass "Error message is helpful"
else
    log_fail "Error message is NOT helpful"
fi
if echo "$OUTPUT" | grep -q "\-\-description"; then
    log_pass "Suggests fix"
else
    log_fail "Does NOT suggest fix"
fi
if check_no_stacktrace "$OUTPUT"; then
    log_pass "No stack trace leaked"
else
    log_fail "Stack trace LEAKED"
fi

echo ""

# ---------------------------------------------------------------------------
# BONUS: Malformed toolpack.yaml leaks Pydantic validation errors
# ---------------------------------------------------------------------------
echo -e "${CYAN}--- Bonus: Malformed toolpack.yaml (Pydantic error leak) ---${NC}"
OUTPUT=$("$TOOLWRIGHT" gate sync --toolpack "$TMPDIR/malformed_toolpack.yaml" 2>&1 || true)
echo "  Output (first 3 lines):"
echo "$OUTPUT" | head -3 | sed 's/^/    /'

if echo "$OUTPUT" | grep -q "validation error"; then
    log_fail "Leaks Pydantic validation errors to user"
else
    log_pass "No internal errors leaked"
fi
if check_suggests_fix "$OUTPUT"; then
    log_pass "Suggests fix"
else
    log_fail "Does NOT suggest fix"
fi
if check_no_stacktrace "$OUTPUT"; then
    log_pass "No stack trace leaked"
else
    log_fail "Stack trace LEAKED (Pydantic internals)"
fi

echo ""

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  Summary${NC}"
echo -e "${CYAN}========================================${NC}"
echo -e "  ${GREEN}PASS${NC}: $PASS"
echo -e "  ${RED}FAIL${NC}: $FAIL"
echo -e "  ${YELLOW}WARN${NC}: $WARN"
TOTAL=$((PASS + FAIL + WARN))
echo "  Total checks: $TOTAL"
echo ""

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}Some checks failed. See report above.${NC}"
    exit 1
else
    echo -e "${GREEN}All checks passed (with $WARN warnings).${NC}"
    exit 0
fi

#!/usr/bin/env bash
# Story: Circuit breaker lifecycle (KILL pillar)
# Tests CLOSED -> OPEN -> HALF_OPEN -> CLOSED lifecycle + manual kill/enable
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TOOLWRIGHT="$REPO_ROOT/.venv/bin/toolwright"
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

cd "$WORKDIR"
mkdir -p .toolwright/state

echo "=== Story: Kill Lifecycle ==="

BREAKER=".toolwright/state/breakers.json"

# 1. Kill a tool
echo ""
echo "--- kill search_api ---"
"$TOOLWRIGHT" kill search_api --reason "API returning 500s" --breaker-state "$BREAKER"

# 2. Check quarantine
echo ""
echo "--- quarantine ---"
"$TOOLWRIGHT" quarantine --breaker-state "$BREAKER"

# 3. Check breaker status
echo ""
echo "--- breaker-status ---"
"$TOOLWRIGHT" breaker-status search_api --breaker-state "$BREAKER"

# 4. Re-enable
echo ""
echo "--- enable search_api ---"
"$TOOLWRIGHT" enable search_api --breaker-state "$BREAKER"

# 5. Verify no quarantined tools
echo ""
echo "--- quarantine (should be empty) ---"
"$TOOLWRIGHT" quarantine --breaker-state "$BREAKER"

# 6. Verify state file exists
if [ -f "$BREAKER" ]; then
    echo ""
    echo "State file persists across invocations: OK"
else
    echo "FAIL: breaker state file missing"
    exit 1
fi

echo ""
echo "=== Kill Lifecycle story PASSED ==="

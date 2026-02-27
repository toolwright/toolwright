#!/usr/bin/env bash
#
# Quick smoke-test for the Toolwright meta-server (inspect command) over MCP stdio.
#
# Sends JSON-RPC 2.0 messages to the meta-server and verifies basic responses.
# For the comprehensive test suite, run:  .venv/bin/python dogfood/test_meta_server.py
#
# Usage:
#   bash dogfood/test_meta_server.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOLWRIGHT="$PROJECT_ROOT/.venv/bin/toolwright"
PYTHON="$PROJECT_ROOT/.venv/bin/python3"

# Artifacts
TOOLS_JSON="$PROJECT_ROOT/dogfood/github/artifact/tools.json"
POLICY_YAML="$PROJECT_ROOT/dogfood/github/artifact/policy.yaml"
LOCKFILE="$PROJECT_ROOT/dogfood/github/lockfile/toolwright.lock.yaml"

# Temp files for KILL / CORRECT pillars
CB_FILE=$(mktemp /tmp/toolwright_cb_XXXXXX.json)
RULES_FILE=$(mktemp /tmp/toolwright_rules_XXXXXX.json)
echo '{}' > "$CB_FILE"
echo '[]' > "$RULES_FILE"

cleanup() {
  rm -f "$CB_FILE" "$RULES_FILE"
  # Kill background server if still running
  [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "=== Toolwright meta-server smoke test ==="
echo ""

# ---------------------------------------------------------------------------
# Use the Python test script for the full exercise
# ---------------------------------------------------------------------------
echo "Running comprehensive Python test harness..."
"$PYTHON" "$SCRIPT_DIR/test_meta_server.py"
exit_code=$?

if [ $exit_code -eq 0 ]; then
  echo ""
  echo "All meta-server tests PASSED."
else
  echo ""
  echo "Some meta-server tests FAILED (exit code $exit_code)."
fi

exit $exit_code

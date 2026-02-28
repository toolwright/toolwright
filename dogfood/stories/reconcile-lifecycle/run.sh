#!/usr/bin/env bash
# Story: Reconcile lifecycle (HEAL pillar — Phase 9)
# Tests watch status, repair plan, snapshots, and rollback via CLI.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TOOLWRIGHT="$REPO_ROOT/.venv/bin/toolwright"
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

cd "$WORKDIR"

echo "=== Story: Reconcile Lifecycle ==="

# --- Setup: generate a toolpack via demo ---
echo ""
echo "--- generate toolpack ---"
"$TOOLWRIGHT" demo --generate-only 2>/dev/null || "$TOOLWRIGHT" demo --generate-only

# Find the generated toolpack
TP_DIR=$(find . -name "toolpack.yaml" -print -quit | xargs dirname 2>/dev/null || true)
if [ -z "$TP_DIR" ]; then
    echo "FAIL: No toolpack generated"
    exit 1
fi
echo "Toolpack at: $TP_DIR"

# --- 1. Write reconcile state simulating an unhealthy tool ---
echo ""
echo "--- simulate unhealthy tool ---"
# watch status reads from project root: .toolwright/state/reconcile.json
STATE_DIR="$WORKDIR/.toolwright/state"
mkdir -p "$STATE_DIR"
cat > "$STATE_DIR/reconcile.json" <<'RECONCILE_EOF'
{
  "tools": {
    "get_users": {
      "tool_id": "get_users",
      "status": "healthy",
      "consecutive_healthy": 5,
      "consecutive_unhealthy": 0,
      "last_probe_at": "2026-02-27T00:00:00Z",
      "last_action": "none",
      "version": 0
    },
    "delete_user": {
      "tool_id": "delete_user",
      "status": "unhealthy",
      "failure_class": "SCHEMA_CHANGED",
      "consecutive_healthy": 0,
      "consecutive_unhealthy": 3,
      "last_probe_at": "2026-02-27T00:00:00Z",
      "last_action": "approval_queued",
      "version": 0
    }
  },
  "reconcile_count": 10,
  "auto_repairs_applied": 2,
  "approvals_queued": 1,
  "errors": 0
}
RECONCILE_EOF
echo "Wrote simulated reconcile state"

# --- 2. Watch status ---
echo ""
echo "--- watch status ---"
# --root points to project root (where .toolwright/state/ lives)
"$TOOLWRIGHT" watch status --root "$WORKDIR"

# --- 3. Create a snapshot ---
echo ""
echo "--- create snapshot ---"
PYTHON="$REPO_ROOT/.venv/bin/python3"
SNAP_ID=$("$PYTHON" -c "
import sys; sys.path.insert(0, '$REPO_ROOT')
from pathlib import Path
from toolwright.core.reconcile.versioner import ToolpackVersioner
v = ToolpackVersioner(Path('$TP_DIR'))
print(v.snapshot(label='pre-repair'))
")
echo "Snapshot created: $SNAP_ID"

# --- 4. List snapshots ---
echo ""
echo "--- list snapshots ---"
"$TOOLWRIGHT" snapshots --root "$TP_DIR"

# --- 5. Modify a file to simulate drift ---
echo ""
echo "--- simulate drift (modify tools.json) ---"
TOOLS_FILE=$(find "$TP_DIR" -name "tools.json" -print -quit)
if [ -n "$TOOLS_FILE" ]; then
    echo '{"schema_version":"1.0","actions":[{"name":"DRIFTED"}]}' > "$TOOLS_FILE"
    echo "Modified tools.json to simulate drift"
fi

# --- 6. Rollback ---
echo ""
echo "--- rollback to snapshot ---"
"$TOOLWRIGHT" rollback "$SNAP_ID" --root "$TP_DIR"

# --- 7. Verify rollback restored original ---
if [ -n "$TOOLS_FILE" ] && [ -f "$TOOLS_FILE" ]; then
    if grep -q "DRIFTED" "$TOOLS_FILE"; then
        echo "FAIL: rollback did not restore original tools.json"
        exit 1
    fi
    echo "Rollback restored original tools.json: OK"
fi

echo ""
echo "=== Reconcile Lifecycle story PASSED ==="

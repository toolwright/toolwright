#!/usr/bin/env bash
# Story: Capability request / rule suggestion lifecycle (Phase 9)
# Tests rules drafts, activate, disable — the human-gated workflow.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TOOLWRIGHT="$REPO_ROOT/.venv/bin/toolwright"
PYTHON="$REPO_ROOT/.venv/bin/python3"
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

cd "$WORKDIR"

# Initialize toolwright root
"$TOOLWRIGHT" init
ROOT="$WORKDIR/.toolwright"

echo "=== Story: Capability Request / Rule Suggestion ==="

# --- 1. Add an active rule (human-created) ---
echo ""
echo "--- add active prohibition rule ---"
"$TOOLWRIGHT" --root "$ROOT" rules add --kind prohibition --target delete_all \
  --description "Never delete all records"

# --- 2. List rules (should show 1 active) ---
echo ""
echo "--- list rules (expect 1) ---"
"$TOOLWRIGHT" --root "$ROOT" rules list

# --- 3. Check drafts (should be empty) ---
echo ""
echo "--- rules drafts (expect none) ---"
"$TOOLWRIGHT" --root "$ROOT" rules drafts

# --- 4. Simulate agent-suggested draft rule ---
echo ""
echo "--- simulate agent draft rule ---"
RULES_FILE="$ROOT/rules.json"
RULE_ID=$("$PYTHON" -c "
import sys; sys.path.insert(0, '$REPO_ROOT')
from pathlib import Path
from datetime import UTC, datetime
from toolwright.core.correct.engine import RuleEngine
from toolwright.models.rule import BehavioralRule, RuleKind, RuleStatus, PrerequisiteConfig

engine = RuleEngine(rules_path=Path('$RULES_FILE'))
rule = BehavioralRule(
    rule_id='rule_agent_001',
    kind=RuleKind.PREREQUISITE,
    description='Read user before update (agent-suggested)',
    status=RuleStatus.DRAFT,
    target_tool_ids=['update_user'],
    config=PrerequisiteConfig(required_tool_ids=['get_user']),
    created_at=datetime.now(UTC),
    created_by='agent',
)
engine.add_rule(rule)
print(rule.rule_id)
")
echo "Agent suggested rule: $RULE_ID"

# --- 5. Drafts now shows the agent rule ---
echo ""
echo "--- rules drafts (expect 1) ---"
OUTPUT=$("$TOOLWRIGHT" --root "$ROOT" rules drafts)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "$RULE_ID"; then
    echo "Draft rule visible: OK"
else
    echo "FAIL: draft rule not visible"
    exit 1
fi

# --- 6. Human activates the draft ---
echo ""
echo "--- activate agent rule ---"
"$TOOLWRIGHT" --root "$ROOT" rules activate "$RULE_ID"

# --- 7. Verify it's no longer in drafts ---
echo ""
echo "--- rules drafts (expect none again) ---"
OUTPUT=$("$TOOLWRIGHT" --root "$ROOT" rules drafts)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "$RULE_ID"; then
    echo "FAIL: activated rule still shows as draft"
    exit 1
fi
echo "Activated rule no longer in drafts: OK"

# --- 8. List all rules (should show 2: 1 original + 1 activated) ---
echo ""
echo "--- list rules (expect 2) ---"
"$TOOLWRIGHT" --root "$ROOT" rules list

# --- 9. Disable the agent rule ---
echo ""
echo "--- disable agent rule ---"
"$TOOLWRIGHT" --root "$ROOT" rules disable "$RULE_ID"

# --- 10. Verify disabled ---
echo ""
echo "--- list rules (rule should show disabled) ---"
"$TOOLWRIGHT" --root "$ROOT" rules list

echo ""
echo "=== Capability Request story PASSED ==="

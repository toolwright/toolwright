#!/usr/bin/env bash
# =============================================================================
# CORRECT Pillar Behavioral Rules Dogfood Test
# =============================================================================
# Date:    2026-02-27
# Purpose: Exercise the full rules CRUD + export/import lifecycle with real CLI
#          commands and real state persistence, using realistic GitHub API
#          operator rules.
#
# FINDINGS SUMMARY:
#   - All 11 core lifecycle steps PASS.
#   - Export/import round-trip preserves all rule data including regex patterns.
#   - BUG FOUND & FIXED: --pattern option was missing from `rules add` CLI.
#     The ParameterConfig model supported `pattern` but _build_config and the
#     Click option were not wired up. Fixed in commands_rules.py.
#   - UX ISSUE: --rules-path is a group-level option, so it must appear
#     BEFORE the subcommand: `toolwright rules --rules-path PATH add ...`
#     NOT: `toolwright rules add ... --rules-path PATH`
#     This is standard Click behavior for group options, but the task plan
#     had it at the end, which fails with "No such option: --rules-path".
#   - Rule IDs are auto-generated as rule_<8hex>. Clear enough for CLI use.
#   - `rules list` output is clean and scannable.
#   - `rules show` outputs full JSON with all config details.
# =============================================================================
set -euo pipefail

TOOLWRIGHT="$(cd "$(dirname "$0")/../.." && pwd)/.venv/bin/toolwright"
RULES_PATH="$(mktemp -d)/rules.json"
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "=== CORRECT Pillar Behavioral Rules Dogfood ==="
echo "Rules file: $RULES_PATH"
echo ""

# -------------------------------------------------------------------------
# Step 1: Safety rule - Must read a repo before modifying it
# Expected: "Rule '<id>' added (prerequisite)."
# -------------------------------------------------------------------------
echo "--- Step 1: Add prerequisite rule ---"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_PATH" add \
    --kind prerequisite \
    --target patch_repo_issue \
    --requires get_repo \
    --description "Must read repo context before modifying issues" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "added (prerequisite)"; then
    pass "prerequisite rule added"
else
    fail "prerequisite rule not added: $OUTPUT"
fi
echo ""

# -------------------------------------------------------------------------
# Step 2: Safety rule - Block content deletion entirely
# Expected: "Rule '<id>' added (prohibition)."
# -------------------------------------------------------------------------
echo "--- Step 2: Add prohibition rule ---"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_PATH" add \
    --kind prohibition \
    --target delete_repo_contents \
    --description "Never delete repository files" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "added (prohibition)"; then
    pass "prohibition rule added"
else
    fail "prohibition rule not added: $OUTPUT"
fi
echo ""

# -------------------------------------------------------------------------
# Step 3: Rate limit - Don't spam the issues API
# Expected: "Rule '<id>' added (rate)."
# -------------------------------------------------------------------------
echo "--- Step 3: Add rate rule ---"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_PATH" add \
    --kind rate \
    --target post_repo_issue \
    --max-calls 5 \
    --description "Max 5 new issues per session" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "added (rate)"; then
    pass "rate rule added"
else
    fail "rate rule not added: $OUTPUT"
fi
echo ""

# -------------------------------------------------------------------------
# Step 4: Parameter guard - Label color must be valid hex
# Expected: "Rule '<id>' added (parameter)."
# -------------------------------------------------------------------------
echo "--- Step 4: Add parameter rule with pattern ---"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_PATH" add \
    --kind parameter \
    --target post_repo_label \
    --param-name color \
    --pattern "^[0-9a-fA-F]{6}$" \
    --description "Label color must be valid hex" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "added (parameter)"; then
    pass "parameter rule with pattern added"
else
    fail "parameter rule not added: $OUTPUT"
fi
echo ""

# -------------------------------------------------------------------------
# Step 5: Verify rules - Must show 4 rules with correct types and targets
# -------------------------------------------------------------------------
echo "--- Step 5: List all rules ---"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_PATH" list 2>&1)
echo "$OUTPUT"
RULE_COUNT=$(echo "$OUTPUT" | grep -c "rule_")
if [ "$RULE_COUNT" -eq 4 ]; then
    pass "4 rules listed"
else
    fail "expected 4 rules, found $RULE_COUNT"
fi
if echo "$OUTPUT" | grep -q "prerequisite" && \
   echo "$OUTPUT" | grep -q "prohibition" && \
   echo "$OUTPUT" | grep -q "rate" && \
   echo "$OUTPUT" | grep -q "parameter"; then
    pass "all 4 rule kinds present"
else
    fail "missing rule kinds in list output"
fi
if echo "$OUTPUT" | grep -q "patch_repo_issue" && \
   echo "$OUTPUT" | grep -q "delete_repo_contents" && \
   echo "$OUTPUT" | grep -q "post_repo_issue" && \
   echo "$OUTPUT" | grep -q "post_repo_label"; then
    pass "all 4 targets present"
else
    fail "missing targets in list output"
fi
# Capture the first rule ID for later steps
FIRST_RULE_ID=$(echo "$OUTPUT" | grep "rule_" | head -1 | awk '{print $1}')
echo "  (First rule ID: $FIRST_RULE_ID)"
echo ""

# -------------------------------------------------------------------------
# Step 6: Export rules to a file
# Expected: "Exported 4 rule(s) to /tmp/github-rules.json."
# -------------------------------------------------------------------------
echo "--- Step 6: Export rules ---"
EXPORT_FILE="/tmp/github-rules-dogfood.json"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_PATH" export \
    --output "$EXPORT_FILE" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "Exported 4 rule(s)"; then
    pass "4 rules exported"
else
    fail "export output unexpected: $OUTPUT"
fi
if [ -f "$EXPORT_FILE" ]; then
    pass "export file exists"
else
    fail "export file not created"
fi
echo ""

# -------------------------------------------------------------------------
# Step 7: Import into a new location
# Expected: "Imported 4 rule(s)."
# -------------------------------------------------------------------------
echo "--- Step 7: Import rules into fresh location ---"
RULES_COPY="$(mktemp -d)/rules-copy.json"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_COPY" import \
    --input "$EXPORT_FILE" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "Imported 4 rule(s)"; then
    pass "4 rules imported"
else
    fail "import output unexpected: $OUTPUT"
fi
echo ""

# -------------------------------------------------------------------------
# Step 8: Verify import preserved rules
# Expected: Same 4 rules with same IDs, kinds, descriptions, targets
# -------------------------------------------------------------------------
echo "--- Step 8: Verify imported rules match ---"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_COPY" list 2>&1)
echo "$OUTPUT"
IMPORT_COUNT=$(echo "$OUTPUT" | grep -c "rule_")
if [ "$IMPORT_COUNT" -eq 4 ]; then
    pass "imported rules count matches (4)"
else
    fail "imported rules count: expected 4, got $IMPORT_COUNT"
fi
# Verify the pattern rule survived the round trip
PATTERN_CHECK=$(python3 -c "
import json
data = json.load(open('$RULES_COPY'))
param_rules = [r for r in data if r['kind'] == 'parameter']
if param_rules and param_rules[0]['config'].get('pattern') == '^[0-9a-fA-F]{6}\$':
    print('pattern_ok')
else:
    print('pattern_missing')
")
if [ "$PATTERN_CHECK" = "pattern_ok" ]; then
    pass "regex pattern preserved through export/import"
else
    fail "regex pattern lost in export/import round-trip"
fi
echo ""

# -------------------------------------------------------------------------
# Step 9: Show a specific rule
# Expected: Full JSON output with rule_id, kind, config, etc.
# -------------------------------------------------------------------------
echo "--- Step 9: Show specific rule ($FIRST_RULE_ID) ---"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_PATH" show "$FIRST_RULE_ID" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "\"rule_id\": \"$FIRST_RULE_ID\""; then
    pass "show displays correct rule_id"
else
    fail "show output missing rule_id"
fi
if echo "$OUTPUT" | grep -q "\"kind\": \"prerequisite\""; then
    pass "show displays correct kind"
else
    fail "show output missing kind"
fi
if echo "$OUTPUT" | grep -q "\"get_repo\""; then
    pass "show displays prerequisite config (get_repo)"
else
    fail "show output missing prerequisite config"
fi
echo ""

# -------------------------------------------------------------------------
# Step 10: Remove first rule
# Expected: "Rule '<id>' removed."
# -------------------------------------------------------------------------
echo "--- Step 10: Remove rule ($FIRST_RULE_ID) ---"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_PATH" remove "$FIRST_RULE_ID" 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "removed"; then
    pass "rule removed"
else
    fail "remove output unexpected: $OUTPUT"
fi
echo ""

# -------------------------------------------------------------------------
# Step 11: Verify removal - Must show 3 remaining
# -------------------------------------------------------------------------
echo "--- Step 11: Verify removal (expect 3 remaining) ---"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_PATH" list 2>&1)
echo "$OUTPUT"
REMAINING=$(echo "$OUTPUT" | grep -c "rule_")
if [ "$REMAINING" -eq 3 ]; then
    pass "3 rules remaining after removal"
else
    fail "expected 3 remaining, found $REMAINING"
fi
if echo "$OUTPUT" | grep -q "$FIRST_RULE_ID"; then
    fail "removed rule still appears in list"
else
    pass "removed rule no longer in list"
fi
echo ""

# =========================================================================
# EDGE CASES
# =========================================================================
echo "=== Edge Cases ==="
echo ""

# Edge case A: List with kind filter
echo "--- Edge A: List filtered by kind=prohibition ---"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_PATH" list --kind prohibition 2>&1)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -q "prohibition" && ! echo "$OUTPUT" | grep -q "rate"; then
    pass "kind filter works correctly"
else
    fail "kind filter did not work"
fi
echo ""

# Edge case B: Show non-existent rule
echo "--- Edge B: Show non-existent rule ---"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_PATH" show nonexistent 2>&1 || true)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -qi "not found"; then
    pass "non-existent rule handled gracefully"
else
    fail "non-existent rule not handled"
fi
echo ""

# Edge case C: Remove non-existent rule
echo "--- Edge C: Remove non-existent rule ---"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_PATH" remove nonexistent 2>&1 || true)
echo "$OUTPUT"
if echo "$OUTPUT" | grep -qi "not found"; then
    pass "remove non-existent handled gracefully"
else
    fail "remove non-existent not handled"
fi
echo ""

# Edge case D: Import skips duplicates
echo "--- Edge D: Import skips duplicates ---"
OUTPUT=$("$TOOLWRIGHT" rules --rules-path "$RULES_PATH" import --input "$EXPORT_FILE" 2>&1)
echo "$OUTPUT"
# Only 1 new rule should be imported (the prerequisite was removed, so it's new again)
# The other 3 already exist and should be skipped
if echo "$OUTPUT" | grep -q "Imported 1 rule(s)"; then
    pass "import skips duplicates correctly"
else
    fail "import duplicate handling unexpected: $OUTPUT"
fi
echo ""

# Edge case E: Rules file is valid JSON after all operations
echo "--- Edge E: Rules file is valid JSON ---"
if python3 -c "import json; json.load(open('$RULES_PATH')); print('Valid JSON')"; then
    pass "rules file is valid JSON"
else
    fail "rules file is not valid JSON"
fi
echo ""

# =========================================================================
# CLEANUP
# =========================================================================
rm -f "$EXPORT_FILE"
# temp dirs are cleaned up by the OS

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

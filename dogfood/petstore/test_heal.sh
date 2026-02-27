#!/usr/bin/env bash
# =============================================================================
# Dogfood: HEAL Pillar Test Script for Petstore API
# =============================================================================
# Tests drift detection, health checking, and repair using the Petstore API.
# Run from the toolwright project root.
#
# Usage:
#   ./dogfood/petstore/test_heal.sh
#
# Prerequisites:
#   - .venv/bin/toolwright available
#   - Network access to petstore3.swagger.io
# =============================================================================

set -euo pipefail

TOOLWRIGHT=".venv/bin/toolwright"
ROOT_DIR=".toolwright"
PASS=0
FAIL=0
WARN=0

# Helpers
pass_test() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail_test() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }
warn_test() { echo "  [WARN] $1"; WARN=$((WARN + 1)); }

separator() {
  echo ""
  echo "================================================================="
  echo "  $1"
  echo "================================================================="
  echo ""
}

# Clean up any previous test state in captures (leave existing ones alone)
cleanup_test_captures() {
  rm -rf "${ROOT_DIR}/captures/cap_petstore_test_a" 2>/dev/null || true
  rm -rf "${ROOT_DIR}/captures/cap_petstore_test_b" 2>/dev/null || true
}

# =============================================================================
# TEST 1: Capture — Import Petstore OpenAPI Spec
# =============================================================================
separator "TEST 1: Capture — Import Petstore OpenAPI Spec"

echo "Importing Petstore OpenAPI spec (first capture)..."
OUTPUT_A=$($TOOLWRIGHT capture import \
  https://petstore3.swagger.io/api/v3/openapi.json \
  -a petstore3.swagger.io \
  -n petstore_heal_a \
  --input-format openapi 2>&1) || true

CAPTURE_A_ID=$(echo "$OUTPUT_A" | grep "Capture saved:" | awk '{print $3}')
if [[ -n "$CAPTURE_A_ID" ]]; then
  pass_test "First capture created: $CAPTURE_A_ID"
else
  fail_test "First capture failed to create"
  echo "  Output: $OUTPUT_A"
fi

# Verify capture has 19 operations (Petstore v3 has 19 endpoints)
OPS_COUNT=$(echo "$OUTPUT_A" | grep "Operations:" | awk '{print $2}')
if [[ "$OPS_COUNT" == "19" ]]; then
  pass_test "Capture has expected 19 operations"
else
  fail_test "Expected 19 operations, got: $OPS_COUNT"
fi

echo ""
echo "Importing Petstore OpenAPI spec (second capture)..."
OUTPUT_B=$($TOOLWRIGHT capture import \
  https://petstore3.swagger.io/api/v3/openapi.json \
  -a petstore3.swagger.io \
  -n petstore_heal_b \
  --input-format openapi 2>&1) || true

CAPTURE_B_ID=$(echo "$OUTPUT_B" | grep "Capture saved:" | awk '{print $3}')
if [[ -n "$CAPTURE_B_ID" ]]; then
  pass_test "Second capture created: $CAPTURE_B_ID"
else
  fail_test "Second capture failed to create"
fi

# =============================================================================
# TEST 2: Drift — No Drift Between Identical Captures
# =============================================================================
separator "TEST 2: Drift — No Drift Between Identical Captures"

DRIFT_OUTPUT=$($TOOLWRIGHT drift \
  --from "$CAPTURE_A_ID" \
  --to "$CAPTURE_B_ID" \
  --volatile-metadata 2>&1) || true

TOTAL_DRIFTS=$(echo "$DRIFT_OUTPUT" | grep "Total Drifts:" | awk '{print $3}')
if [[ "$TOTAL_DRIFTS" == "0" ]]; then
  pass_test "No drift detected between identical captures"
else
  fail_test "Expected 0 drifts, got: $TOTAL_DRIFTS"
fi

EXIT_CODE=$(echo "$DRIFT_OUTPUT" | grep "Exit Code:" | awk '{print $3}')
if [[ "$EXIT_CODE" == "0" ]]; then
  pass_test "Drift exit code is 0 (no issues)"
else
  fail_test "Expected exit code 0, got: $EXIT_CODE"
fi

# =============================================================================
# TEST 3: Drift — Detect Simulated Schema Drift
# =============================================================================
separator "TEST 3: Drift — Detect Simulated Schema Drift"

echo "Modifying second capture to add 'weight' field to PUT /pet response..."
CAPTURE_B_DIR="${ROOT_DIR}/captures/${CAPTURE_B_ID}"
EXCHANGES_FILE="${CAPTURE_B_DIR}/exchanges.json"

if [[ -f "$EXCHANGES_FILE" ]]; then
  # Add a 'weight' field to the PUT /pet response_body_json
  # This simulates schema drift
  python3 -c "
import json
with open('$EXCHANGES_FILE') as f:
    data = json.load(f)
for ex in data:
    if ex['method'] == 'PUT' and ex['path'] == '/pet':
        if isinstance(ex.get('response_body_json'), dict):
            ex['response_body_json']['weight'] = 25.5
with open('$EXCHANGES_FILE', 'w') as f:
    json.dump(data, f, indent=2)
print('Modified PUT /pet response to include weight field')
"
  pass_test "Modified capture B to simulate schema drift"
else
  fail_test "Exchanges file not found: $EXCHANGES_FILE"
fi

DRIFT_OUTPUT=$($TOOLWRIGHT drift \
  --from "$CAPTURE_A_ID" \
  --to "$CAPTURE_B_ID" \
  --volatile-metadata 2>&1) || true

TOTAL_DRIFTS=$(echo "$DRIFT_OUTPUT" | grep "Total Drifts:" | awk '{print $3}')
SCHEMA_DRIFTS=$(echo "$DRIFT_OUTPUT" | grep "Schema:" | awk '{print $2}')
if [[ "$TOTAL_DRIFTS" -ge "1" ]]; then
  pass_test "Drift detected: $TOTAL_DRIFTS total drift(s)"
else
  fail_test "Expected at least 1 drift, got: $TOTAL_DRIFTS"
fi

if [[ "$SCHEMA_DRIFTS" -ge "1" ]]; then
  pass_test "Schema drift detected: $SCHEMA_DRIFTS schema drift(s)"
else
  fail_test "Expected at least 1 schema drift, got: $SCHEMA_DRIFTS"
fi

# Verify drift report files exist
if [[ -f "${ROOT_DIR}/reports/drift.json" ]]; then
  pass_test "Drift report JSON exists"
else
  fail_test "Drift report JSON not found"
fi
if [[ -f "${ROOT_DIR}/reports/drift.md" ]]; then
  pass_test "Drift report Markdown exists"
else
  fail_test "Drift report Markdown not found"
fi

# =============================================================================
# TEST 4: Compile — Create Toolpack from Capture
# =============================================================================
separator "TEST 4: Compile — Create Toolpack from Capture"

COMPILE_OUTPUT=$($TOOLWRIGHT compile \
  -c "$CAPTURE_A_ID" \
  --volatile-metadata 2>&1) || true

TOOLPACK_PATH=$(echo "$COMPILE_OUTPUT" | grep "Toolpack:" | awk '{print $2}')
if [[ -n "$TOOLPACK_PATH" ]]; then
  pass_test "Toolpack created: $TOOLPACK_PATH"
else
  fail_test "Toolpack path not found in compile output"
  echo "  Output: $COMPILE_OUTPUT"
fi

# Extract tools.json path
ARTIFACT_ID=$(echo "$COMPILE_OUTPUT" | grep "Compile complete:" | awk '{print $3}')
TOOLS_JSON="${ROOT_DIR}/artifacts/${ARTIFACT_ID}/tools.json"
if [[ -f "$TOOLS_JSON" ]]; then
  pass_test "tools.json exists: $TOOLS_JSON"
else
  fail_test "tools.json not found at: $TOOLS_JSON"
fi

# Verify tool count
TOOL_COUNT=$(python3 -c "import json; print(len(json.load(open('$TOOLS_JSON')).get('actions', [])))" 2>/dev/null || echo "0")
if [[ "$TOOL_COUNT" == "19" ]]; then
  pass_test "Compiled tools.json has 19 actions"
else
  warn_test "Expected 19 tools in manifest, got: $TOOL_COUNT"
fi

# =============================================================================
# TEST 5: Health Check — Probe Petstore Endpoints
# =============================================================================
separator "TEST 5: Health Check — Probe Petstore Endpoints"

HEALTH_OUTPUT=$($TOOLWRIGHT health --tools "$TOOLS_JSON" 2>&1) || true
HEALTH_EXIT=$?

# Count healthy and unhealthy
HEALTHY_COUNT=$(echo "$HEALTH_OUTPUT" | grep -c "healthy" || true)
UNHEALTHY_COUNT=$(echo "$HEALTH_OUTPUT" | grep -c "UNHEALTHY" || true)

echo "  Healthy:   $HEALTHY_COUNT"
echo "  Unhealthy: $UNHEALTHY_COUNT"

# POST/PUT/DELETE endpoints use OPTIONS probe -> should be healthy (204)
# GET endpoints use HEAD probe -> Petstore returns 404 for HEAD (known issue)
if [[ "$HEALTHY_COUNT" -gt 0 ]]; then
  pass_test "Some endpoints report healthy"
else
  fail_test "No healthy endpoints detected"
fi

# We expect GET endpoints to be unhealthy due to HEAD probe limitation
if echo "$HEALTH_OUTPUT" | grep -q "UNHEALTHY.*endpoint_gone"; then
  warn_test "GET endpoints report UNHEALTHY (known: Petstore doesn't support HEAD)"
fi

# Verify write endpoints are healthy (OPTIONS probe)
WRITE_HEALTHY=$(echo "$HEALTH_OUTPUT" | grep -E "^  (create_|update_|delete_|upload_)" | grep -c "healthy" || true)
if [[ "$WRITE_HEALTHY" -gt 0 ]]; then
  pass_test "Write endpoints report healthy via OPTIONS probe ($WRITE_HEALTHY endpoints)"
else
  fail_test "No write endpoints report healthy"
fi

# =============================================================================
# TEST 6: Repair — Diagnose and Propose Fixes
# =============================================================================
separator "TEST 6: Repair — Diagnose and Propose Fixes"

# 6a: Repair with auto-discover (no context should mean healthy)
REPAIR_OUTPUT=$($TOOLWRIGHT repair \
  --toolpack "$TOOLPACK_PATH" \
  --no-auto-discover 2>&1) || true

if echo "$REPAIR_OUTPUT" | grep -q "system is healthy"; then
  pass_test "Repair with no context reports healthy"
else
  fail_test "Repair should report healthy without context"
fi

# 6b: Repair with drift report as context
REPAIR_OUTPUT=$($TOOLWRIGHT repair \
  --toolpack "$TOOLPACK_PATH" \
  --from "${ROOT_DIR}/reports/drift.json" 2>&1) || true

if echo "$REPAIR_OUTPUT" | grep -q "issues found"; then
  ISSUE_COUNT=$(echo "$REPAIR_OUTPUT" | grep "issues found" | head -1 | awk '{print $2}')
  pass_test "Repair found $ISSUE_COUNT issue(s) from drift report"
else
  fail_test "Repair should find issues from drift report"
fi

# Verify repair artifacts
REPAIR_DIR=$(echo "$REPAIR_OUTPUT" | grep "Output:" | head -1 | awk '{print $2}')
if [[ -n "$REPAIR_DIR" ]]; then
  if [[ -f "${REPAIR_DIR}/repair.json" ]]; then
    pass_test "repair.json artifact exists"
  else
    fail_test "repair.json not found in: $REPAIR_DIR"
  fi

  if [[ -f "${REPAIR_DIR}/repair.md" ]]; then
    pass_test "repair.md artifact exists"
  else
    fail_test "repair.md not found in: $REPAIR_DIR"
  fi

  if [[ -f "${REPAIR_DIR}/patch.commands.sh" ]]; then
    pass_test "patch.commands.sh artifact exists"
  else
    fail_test "patch.commands.sh not found in: $REPAIR_DIR"
  fi

  if [[ -f "${REPAIR_DIR}/diagnosis.json" ]]; then
    pass_test "diagnosis.json artifact exists"
  else
    fail_test "diagnosis.json not found in: $REPAIR_DIR"
  fi
else
  fail_test "Could not extract repair output directory"
fi

# =============================================================================
# RESULTS SUMMARY
# =============================================================================
separator "RESULTS SUMMARY"

TOTAL=$((PASS + FAIL + WARN))
echo "  Tests run:  $TOTAL"
echo "  Passed:     $PASS"
echo "  Failed:     $FAIL"
echo "  Warnings:   $WARN"
echo ""

if [[ $FAIL -gt 0 ]]; then
  echo "  STATUS: SOME TESTS FAILED"
  exit 1
else
  echo "  STATUS: ALL TESTS PASSED"
  exit 0
fi

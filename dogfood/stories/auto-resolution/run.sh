#!/usr/bin/env bash
# Story: Auto-resolution end-to-end
# Validates that all commands work WITHOUT --toolpack when there's a single toolpack.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TOOLWRIGHT="$REPO_ROOT/.venv/bin/toolwright"
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

cd "$WORKDIR"
ROOT="$WORKDIR/.toolwright"

echo "=== Story: Auto-resolution ==="

# 1. Init (creates .toolwright directory)
"$TOOLWRIGHT" init

# 2. Generate demo content (creates a single toolpack)
"$TOOLWRIGHT" --root "$ROOT" demo --generate-only --out "$ROOT"

# 3. Auto-resolution should work (single toolpack) — NO --toolpack flag anywhere
echo ""
echo "--- gate status (auto-resolved) ---"
"$TOOLWRIGHT" --root "$ROOT" gate status

echo ""
echo "--- gate allow --all (auto-resolved) ---"
"$TOOLWRIGHT" --root "$ROOT" gate allow --all

echo ""
echo "--- gate check (auto-resolved) ---"
"$TOOLWRIGHT" --root "$ROOT" gate check

echo ""
echo "--- status (auto-resolved) ---"
"$TOOLWRIGHT" --root "$ROOT" status

echo ""
echo "--- config (auto-resolved) ---"
"$TOOLWRIGHT" --root "$ROOT" config | python3 -c "import sys,json; json.load(sys.stdin)" || { echo "FAIL: config output is not valid JSON"; exit 1; }
echo "Config JSON validated successfully"

echo ""
echo "=== Auto-resolution story PASSED ==="

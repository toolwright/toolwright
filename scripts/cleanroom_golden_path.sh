#!/usr/bin/env bash
# cleanroom_golden_path.sh — Deterministic golden-path proof for Toolwright.
#
# Runs the full kernel loop offline:
#   demo --generate-only → gate allow → gate check → serve (dry-run tool call) → verify
#
# Environment variables:
#   TOOLWRIGHT_DEV=1       Install from local repo checkout (editable) instead of PyPI.
#   TOOLWRIGHT_VERSION     Pin toolwright version for PyPI install (e.g. 0.2.0).
#   TOOLWRIGHT_PYTHON      Python binary to use (default: python3).
#   TOOLWRIGHT_EXTRA_PIP   Extra pip install args (e.g. --index-url for private PyPI).
#
# Exit codes:
#   0  All checks passed.
#   1  A check failed.
set -euo pipefail

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
PYTHON="${TOOLWRIGHT_PYTHON:-python3}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TMPBASE="${TMPDIR:-/tmp}"
TMPBASE="${TMPBASE%/}"
WORKDIR="$(mktemp -d "${TMPBASE}/toolwright-golden-XXXXXX")"
FAILED=0

# --------------------------------------------------------------------------- #
# Cleanup
# --------------------------------------------------------------------------- #
cleanup() {
  if [[ "${TOOLWRIGHT_KEEP_WORKDIR:-}" == "1" ]]; then
    echo ""
    echo "Keeping workdir: $WORKDIR"
  else
    rm -rf "$WORKDIR"
  fi
}
trap cleanup EXIT

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
log() { printf '\n=== %s ===\n' "$*"; }

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  FAILED=1
}

check() {
  # Usage: check "description" command...
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    printf '  ok   %s\n' "$desc"
  else
    printf '  FAIL %s\n' "$desc" >&2
    FAILED=1
  fi
}

# --------------------------------------------------------------------------- #
# Step 0: Validate python version
# --------------------------------------------------------------------------- #
log "Step 0: Validate environment"

if ! command -v "$PYTHON" &>/dev/null; then
  fail "python3 not found on PATH"
  exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")

if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 11 ]]; }; then
  fail "Python >= 3.11 required, found $PY_VERSION"
  exit 1
fi

printf '  python:  %s (%s)\n' "$PY_VERSION" "$(command -v "$PYTHON")"
printf '  workdir: %s\n' "$WORKDIR"

# --------------------------------------------------------------------------- #
# Step 1: Create venv and install
# --------------------------------------------------------------------------- #
log "Step 1: Create venv and install Toolwright"

VENV_DIR="$WORKDIR/.venv"
"$PYTHON" -m venv "$VENV_DIR"

# Activate venv
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Upgrade pip silently
pip install --upgrade pip --quiet 2>/dev/null || true

if [[ "${TOOLWRIGHT_DEV:-}" == "1" ]]; then
  echo "  Installing from local checkout: $REPO_DIR"
  pip install --quiet -e "${REPO_DIR}[mcp]"
else
  if [[ -n "${TOOLWRIGHT_VERSION:-}" ]]; then
    echo "  Installing from PyPI (pinned: $TOOLWRIGHT_VERSION)"
    pip install --quiet "toolwright[mcp]==${TOOLWRIGHT_VERSION}" ${TOOLWRIGHT_EXTRA_PIP:-}
  else
    echo "  Installing from PyPI (latest)"
    pip install --quiet "toolwright[mcp]" ${TOOLWRIGHT_EXTRA_PIP:-}
  fi
fi

# Verify toolwright is available
TOOLWRIGHT_BIN="$(command -v toolwright)"
TOOLWRIGHT_VERSION="$(toolwright --version)"
printf '  toolwright:    %s (%s)\n' "$TOOLWRIGHT_VERSION" "$TOOLWRIGHT_BIN"

# --------------------------------------------------------------------------- #
# Step 2: Generate fixture toolpack (offline)
# --------------------------------------------------------------------------- #
log "Step 2: Generate fixture toolpack (offline)"

TOOLWRIGHT_NON_INTERACTIVE=1 toolwright --no-interactive demo --generate-only --out "$WORKDIR" 2>&1

# Find toolpack directory (expect exactly one tp_* dir)
TP_CANDIDATES=("$WORKDIR"/toolpacks/tp_*)
if [[ ${#TP_CANDIDATES[@]} -eq 0 ]] || [[ ! -d "${TP_CANDIDATES[0]}" ]]; then
  fail "demo --generate-only did not produce a toolpack"
  exit 1
fi
if [[ ${#TP_CANDIDATES[@]} -gt 1 ]]; then
  fail "expected 1 toolpack, found ${#TP_CANDIDATES[@]}: ${TP_CANDIDATES[*]}"
  exit 1
fi
TOOLPACK_DIR="${TP_CANDIDATES[0]}"
if [[ ! -f "$TOOLPACK_DIR/toolpack.yaml" ]]; then
  fail "toolpack directory exists but toolpack.yaml is missing: $TOOLPACK_DIR"
  exit 1
fi

TOOLPACK="$TOOLPACK_DIR/toolpack.yaml"
PENDING_LOCK="$TOOLPACK_DIR/lockfile/toolwright.lock.pending.yaml"
TOOLS_JSON="$TOOLPACK_DIR/artifact/tools.json"

check "toolpack.yaml exists" test -f "$TOOLPACK"
check "tools.json exists" test -f "$TOOLS_JSON"
check "pending lockfile exists" test -f "$PENDING_LOCK"

# --------------------------------------------------------------------------- #
# Step 3: Approve all tools
# --------------------------------------------------------------------------- #
log "Step 3: Gate — approve all tools"

GATE_OUTPUT=$(TOOLWRIGHT_NON_INTERACTIVE=1 toolwright --no-interactive --root "$WORKDIR" \
  gate allow --all --lockfile "$PENDING_LOCK" 2>&1)
echo "  $GATE_OUTPUT"

APPROVED_LOCK="$TOOLPACK_DIR/lockfile/toolwright.lock.yaml"
check "approved lockfile created" test -f "$APPROVED_LOCK"

# --------------------------------------------------------------------------- #
# Step 4: Gate check (CI gate)
# --------------------------------------------------------------------------- #
log "Step 4: Gate — CI check"

GATE_CHECK_OUTPUT=$(TOOLWRIGHT_NON_INTERACTIVE=1 toolwright --no-interactive --root "$WORKDIR" \
  gate check --lockfile "$APPROVED_LOCK" 2>&1) || {
  fail "gate check exited non-zero"
}
echo "  $GATE_CHECK_OUTPUT"

# --------------------------------------------------------------------------- #
# Step 5: MCP serve dry-run tool call
# --------------------------------------------------------------------------- #
log "Step 5: Serve — dry-run MCP tool call"

MCP_STDERR_FILE="$WORKDIR/mcp_serve_stderr.log"
export WORKDIR TOOLPACK APPROVED_LOCK MCP_STDERR_FILE
TOOL_CALL_RESULT=$("$PYTHON" -c "
import json, subprocess, sys, os, time, select

proc = subprocess.Popen(
    ['toolwright', '--no-interactive', '--root', os.environ['WORKDIR'],
     'serve', '--toolpack', os.environ['TOOLPACK'],
     '--lockfile', os.environ['APPROVED_LOCK'], '--dry-run'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True,
    env={**os.environ, 'TOOLWRIGHT_NON_INTERACTIVE': '1'})

def send(msg):
    proc.stdin.write(json.dumps(msg) + '\n')
    proc.stdin.flush()

def recv_until_id(want_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r, _, _ = select.select([proc.stdout], [], [], 0.25)
        if not r:
            continue
        line = proc.stdout.readline()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get('id') == want_id:
            return msg
    raise RuntimeError(f'Timed out waiting for id={want_id}')

send({'jsonrpc':'2.0','id':1,'method':'initialize',
      'params':{'protocolVersion':'2024-11-05','capabilities':{},
                'clientInfo':{'name':'golden-path','version':'1.0'}}})
init = recv_until_id(1)

send({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
tools_resp = recv_until_id(2)
tools = tools_resp.get('result',{}).get('tools',[])

# Pick get_products if available, otherwise first tool
tool_name = None
for t in tools:
    if t.get('name') == 'get_products':
        tool_name = 'get_products'
        break
tool_name = tool_name or (tools[0]['name'] if tools else None)
if not tool_name:
    raise RuntimeError('No tools returned from tools/list')

send({'jsonrpc':'2.0','id':3,'method':'tools/call',
      'params':{'name':tool_name,'arguments':{}}})
call_resp = recv_until_id(3)

# Graceful shutdown: terminate then communicate to reliably capture stderr
proc.terminate()
try:
    _, stderr_out = proc.communicate(timeout=2)
except subprocess.TimeoutExpired:
    proc.kill()
    _, stderr_out = proc.communicate()
if stderr_out:
    with open(os.environ['MCP_STDERR_FILE'], 'w') as f:
        f.write(stderr_out)

if 'result' not in call_resp:
    raise RuntimeError('tool call failed')

content = call_resp['result']['content'][0]['text']
result = json.loads(content)
print(json.dumps({
    'tools_count': len(tools),
    'tool_called': tool_name,
    'decision': result.get('decision'),
    'reason_code': result.get('reason_code'),
    'action': result.get('action'),
    'is_error': call_resp['result'].get('isError', False),
}))
" 2>/dev/null) || {
  fail "MCP serve dry-run tool call failed"
  if [[ -f "$MCP_STDERR_FILE" ]]; then
    echo "  Server stderr:" >&2
    sed 's/^/    /' "$MCP_STDERR_FILE" >&2
  fi
  TOOL_CALL_RESULT='{"tools_count":0,"tool_called":"none","decision":"error","reason_code":"error","action":"none","is_error":true}'
}

TC_DECISION=$("$PYTHON" -c "import json,sys; d=json.loads(sys.argv[1]); print(d['decision'])" "$TOOL_CALL_RESULT")
TC_REASON=$("$PYTHON" -c "import json,sys; d=json.loads(sys.argv[1]); print(d['reason_code'])" "$TOOL_CALL_RESULT")
TC_ACTION=$("$PYTHON" -c "import json,sys; d=json.loads(sys.argv[1]); print(d['action'])" "$TOOL_CALL_RESULT")
TC_TOOLS=$("$PYTHON" -c "import json,sys; d=json.loads(sys.argv[1]); print(d['tools_count'])" "$TOOL_CALL_RESULT")
TC_TOOL=$("$PYTHON" -c "import json,sys; d=json.loads(sys.argv[1]); print(d['tool_called'])" "$TOOL_CALL_RESULT")

printf '  tools listed:  %s\n' "$TC_TOOLS"
printf '  tool called:   %s\n' "$TC_TOOL"
printf '  decision:      %s\n' "$TC_DECISION"
printf '  reason_code:   %s\n' "$TC_REASON"
printf '  action:        %s\n' "$TC_ACTION"

if [[ "$TC_DECISION" != "allow" ]]; then
  fail "tool call decision was '$TC_DECISION', expected 'allow'"
fi
if [[ "$TC_REASON" != "allowed_policy" ]]; then
  fail "tool call reason was '$TC_REASON', expected 'allowed_policy'"
fi

# --------------------------------------------------------------------------- #
# Step 6: Verify contracts
# --------------------------------------------------------------------------- #
log "Step 6: Verify — contracts mode"

VERIFY_OUTPUT=$(TOOLWRIGHT_NON_INTERACTIVE=1 toolwright --no-interactive --root "$WORKDIR" \
  verify --toolpack "$TOOLPACK" --mode contracts 2>&1) || {
  fail "verify exited non-zero"
}
echo "$VERIFY_OUTPUT" | sed 's/^/  /'

# --------------------------------------------------------------------------- #
# Result Summary
# --------------------------------------------------------------------------- #
echo ""
echo "============================================================"
echo "  Result Summary"
echo "============================================================"
echo ""
printf '  %-24s %s\n' "status:" "$(if [[ $FAILED -eq 0 ]]; then echo 'PASS'; else echo 'FAIL'; fi)"
printf '  %-24s %s\n' "workspace:" "$WORKDIR"
printf '  %-24s %s\n' "root:" "$WORKDIR"
printf '  %-24s %s\n' "toolpack:" "$TOOLPACK"
printf '  %-24s %s\n' "approved lockfile:" "$APPROVED_LOCK"
printf '  %-24s %s\n' "tools.json:" "$TOOLS_JSON"
printf '  %-24s %s\n' "tool call decision:" "$TC_DECISION ($TC_REASON)"
printf '  %-24s %s\n' "server stderr log:" "$MCP_STDERR_FILE"
echo ""
printf '  re-run serve:\n'
printf '    toolwright --root %s serve --toolpack %s --lockfile %s --dry-run\n' "$WORKDIR" "$TOOLPACK" "$APPROVED_LOCK"
echo ""

if [[ $FAILED -ne 0 ]]; then
  echo "GOLDEN PATH FAILED"
  exit 1
fi

echo "GOLDEN PATH PASSED"

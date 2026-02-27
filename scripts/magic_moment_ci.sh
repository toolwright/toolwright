#!/usr/bin/env bash
set -euo pipefail

AF_BIN=${TOOLWRIGHT_BIN:-toolwright}
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/toolwright-magic-XXXXXX")"
AF_PYTHON=${TOOLWRIGHT_PYTHON:-}

if [[ -z "$AF_PYTHON" ]]; then
  AF_BIN_RESOLVED="$(command -v "$AF_BIN" 2>/dev/null || true)"
  if [[ -n "$AF_BIN_RESOLVED" ]] && [[ -x "$(dirname "$AF_BIN_RESOLVED")/python" ]]; then
    AF_PYTHON="$(dirname "$AF_BIN_RESOLVED")/python"
  else
    AF_PYTHON="python3"
  fi
fi

cleanup() {
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

log() {
  printf '\n==> %s\n' "$*"
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

latest_dir() {
  local base="$1"
  ls -1t "${base}" | head -n1
}

extract_tools() {
  local tools_json="$1"
  "$AF_PYTHON" - "$tools_json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
actions = payload.get("actions", [])
reads = [a["name"] for a in actions if a.get("method", "GET").upper() in {"GET", "HEAD", "OPTIONS"}]
writes = [a["name"] for a in actions if a.get("method", "GET").upper() in {"POST", "PUT", "PATCH", "DELETE"}]
if not reads or not writes:
    raise SystemExit("missing read/write actions")
print(reads[0])
print(writes[0])
PY
}

assert_readonly_excludes_write() {
  local toolsets_yaml="$1"
  local write_tool="$2"
  "$AF_PYTHON" - "$toolsets_yaml" "$write_tool" <<'PY'
import sys
from pathlib import Path
import yaml

payload = yaml.safe_load(Path(sys.argv[1]).read_text()) or {}
readonly = set(payload.get("toolsets", {}).get("readonly", {}).get("actions", []))
write_tool = sys.argv[2]
if write_tool in readonly:
    raise SystemExit(f"write tool unexpectedly present in readonly: {write_tool}")
print(f"readonly excludes write tool: {write_tool}")
PY
}

assert_reason() {
  local json_payload="$1"
  local expected_reason="$2"
  "$AF_PYTHON" - "$expected_reason" "$json_payload" <<'PY'
import json
import sys

expected = sys.argv[1]
payload = json.loads(sys.argv[2])
reason = payload.get("reason_code")
if reason != expected:
    raise SystemExit(f"expected reason_code={expected}, got {reason}: {payload}")
print(f"reason_code={reason}")
PY
}

extract_confirmation_token() {
  local json_payload="$1"
  "$AF_PYTHON" - "$json_payload" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
if payload.get("decision") != "confirm":
    raise SystemExit(f"expected decision=confirm, got {payload}")
token = payload.get("confirmation_token_id")
if not token:
    raise SystemExit(f"missing confirmation_token_id: {payload}")
print(token)
PY
}

assert_allow() {
  local json_payload="$1"
  "$AF_PYTHON" - "$json_payload" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
if not payload.get("allowed"):
    raise SystemExit(f"expected allowed=true, got {payload}")
if payload.get("decision") != "allow":
    raise SystemExit(f"expected decision=allow, got {payload}")
print("decision=allow")
PY
}

gateway_execute() {
  local tools_json="$1"
  local toolsets_yaml="$2"
  local policy_yaml="$3"
  local lockfile_yaml="$4"
  local action_name="$5"
  local params_json="$6"
  local confirmation_token="${7:-}"

  "$AF_PYTHON" - "$tools_json" "$toolsets_yaml" "$policy_yaml" "$lockfile_yaml" "$action_name" "$params_json" "$confirmation_token" <<'PY'
import json
import sys

from toolwright.cli.enforce import EnforcementGateway

tools, toolsets, policy, lockfile, action_name, params_raw, token = sys.argv[1:]
params = json.loads(params_raw)
gateway = EnforcementGateway(
    tools_path=tools,
    toolsets_path=toolsets,
    toolset_name="operator",
    policy_path=policy,
    lockfile_path=lockfile,
    mode="proxy",
    dry_run=True,
    confirmation_store_path=".toolwright/confirmations.db",
)
result = gateway.execute_action(action_name, params, token or None)
print(json.dumps(result))
PY
}

log "Preparing isolated workspace"
if [[ -f "${ROOT_DIR}/examples/sample.har" ]]; then
  cp "${ROOT_DIR}/examples/sample.har" "${WORKDIR}/sample.har"
else
  "$AF_PYTHON" - "${WORKDIR}/sample.har" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
har = {
    "log": {
        "version": "1.2",
        "creator": {"name": "Toolwright CI Fixture", "version": "1.0.0"},
        "entries": [
            {
                "startedDateTime": "2026-01-01T00:00:00.000Z",
                "time": 42,
                "request": {
                    "method": "GET",
                    "url": "https://api.example.com/api/users?page=1",
                    "httpVersion": "HTTP/1.1",
                    "headers": [{"name": "Host", "value": "api.example.com"}],
                    "queryString": [{"name": "page", "value": "1"}],
                },
                "response": {
                    "status": 200,
                    "statusText": "OK",
                    "httpVersion": "HTTP/1.1",
                    "headers": [{"name": "Content-Type", "value": "application/json"}],
                    "content": {
                        "mimeType": "application/json",
                        "text": "{\"data\": [{\"id\": \"usr_1\", \"name\": \"Jane\"}]}",
                    },
                },
            },
            {
                "startedDateTime": "2026-01-01T00:00:01.000Z",
                "time": 65,
                "request": {
                    "method": "POST",
                    "url": "https://api.example.com/api/users",
                    "httpVersion": "HTTP/1.1",
                    "headers": [{"name": "Content-Type", "value": "application/json"}],
                    "postData": {
                        "mimeType": "application/json",
                        "text": "{\"name\": \"Jane\"}",
                    },
                },
                "response": {
                    "status": 201,
                    "statusText": "Created",
                    "httpVersion": "HTTP/1.1",
                    "headers": [{"name": "Content-Type", "value": "application/json"}],
                    "content": {
                        "mimeType": "application/json",
                        "text": "{\"id\": \"usr_2\", \"name\": \"Jane\"}",
                    },
                },
            },
        ],
    }
}
target.write_text(json.dumps(har, indent=2))
PY
fi
cd "$WORKDIR"

log "1) Compile from capture"
"$AF_BIN" capture import sample.har --allowed-hosts api.example.com --name "Magic Base"
CAPTURE_BASE="$(latest_dir .toolwright/captures)"
"$AF_BIN" compile --capture "$CAPTURE_BASE" --scope first_party_only --format all
ARTIFACT_BASE="$(latest_dir .toolwright/artifacts)"
TOOLS_BASE=".toolwright/artifacts/${ARTIFACT_BASE}/tools.json"
POLICY_BASE=".toolwright/artifacts/${ARTIFACT_BASE}/policy.yaml"
TOOLSETS_BASE=".toolwright/artifacts/${ARTIFACT_BASE}/toolsets.yaml"
BASELINE_BASE=".toolwright/artifacts/${ARTIFACT_BASE}/baseline.json"

TOOLS_OUTPUT="$(extract_tools "$TOOLS_BASE")"
READ_TOOL="$(printf '%s\n' "$TOOLS_OUTPUT" | sed -n '1p')"
WRITE_TOOL="$(printf '%s\n' "$TOOLS_OUTPUT" | sed -n '2p')"
log "Selected read tool: ${READ_TOOL}; write tool: ${WRITE_TOOL}"

log "2) Generate curated read-only toolset"
assert_readonly_excludes_write "$TOOLSETS_BASE" "$WRITE_TOOL"

log "3) Show blocked state-changing call (pending approval)"
set +e
"$AF_BIN" gate sync --tools "$TOOLS_BASE" --policy "$POLICY_BASE" --toolsets "$TOOLSETS_BASE" --lockfile toolwright.lock.yaml >/tmp/af_sync1.log 2>&1
SYNC1_EXIT=$?
set -e
if [[ $SYNC1_EXIT -eq 0 ]]; then
  fail "expected gate sync to fail with pending tools"
fi

BLOCKED_PAYLOAD="$(gateway_execute "$TOOLS_BASE" "$TOOLSETS_BASE" "$POLICY_BASE" "toolwright.lock.yaml" "$WRITE_TOOL" '{"name":"Jane"}')"
assert_reason "$BLOCKED_PAYLOAD" "denied_not_approved"

log "4) Approve via lockfile"
"$AF_BIN" gate allow --all --lockfile toolwright.lock.yaml --by "ci@toolwright"

# Build minimal toolpack structure for snapshot
TOOLPACK_DIR="$WORKDIR/.toolwright/toolpack_ci"
mkdir -p "$TOOLPACK_DIR/artifact" "$TOOLPACK_DIR/lockfile"
cp "$TOOLS_BASE" "$TOOLPACK_DIR/artifact/tools.json"
cp "$TOOLSETS_BASE" "$TOOLPACK_DIR/artifact/toolsets.yaml"
cp "$POLICY_BASE" "$TOOLPACK_DIR/artifact/policy.yaml"
cp "$BASELINE_BASE" "$TOOLPACK_DIR/artifact/baseline.json"
cp toolwright.lock.yaml "$TOOLPACK_DIR/lockfile/toolwright.lock.yaml"
"$AF_PYTHON" - "$TOOLPACK_DIR/toolpack.yaml" "$CAPTURE_BASE" <<'PY'
import sys, yaml
from pathlib import Path
tp = {
    "version": "1.0.0",
    "schema_version": "1.0",
    "toolpack_id": "tp_ci_harness",
    "created_at": "2026-01-01T00:00:00Z",
    "capture_id": sys.argv[2],
    "artifact_id": "art_ci",
    "scope": "first_party_only",
    "allowed_hosts": ["api.example.com"],
    "origin": {"start_url": "https://api.example.com", "name": "CI Harness"},
    "paths": {
        "tools": "artifact/tools.json",
        "toolsets": "artifact/toolsets.yaml",
        "policy": "artifact/policy.yaml",
        "baseline": "artifact/baseline.json",
        "lockfiles": {"pending": "lockfile/toolwright.lock.yaml"},
    },
    "runtime": {"mode": "local", "container": None},
}
Path(sys.argv[1]).write_text(yaml.dump(tp, default_flow_style=False))
PY
"$AF_BIN" gate snapshot --lockfile "$TOOLPACK_DIR/lockfile/toolwright.lock.yaml"
"$AF_BIN" gate check --lockfile "$TOOLPACK_DIR/lockfile/toolwright.lock.yaml"
# Copy back updated lockfile
cp "$TOOLPACK_DIR/lockfile/toolwright.lock.yaml" toolwright.lock.yaml

log "5) Show allowed call after approval + out-of-band grant"
CONFIRM_PAYLOAD="$(gateway_execute "$TOOLS_BASE" "$TOOLSETS_BASE" "$POLICY_BASE" "toolwright.lock.yaml" "$WRITE_TOOL" '{"name":"Jane"}')"
CONFIRM_TOKEN="$(extract_confirmation_token "$CONFIRM_PAYLOAD")"
"$AF_BIN" confirm grant "$CONFIRM_TOKEN" --store .toolwright/confirmations.db

ALLOWED_PAYLOAD="$(gateway_execute "$TOOLS_BASE" "$TOOLSETS_BASE" "$POLICY_BASE" "toolwright.lock.yaml" "$WRITE_TOOL" '{"name":"Jane"}' "$CONFIRM_TOKEN")"
assert_allow "$ALLOWED_PAYLOAD"

log "6) Introduce drift and show CI failure until re-approval"
"$AF_PYTHON" - <<'PY'
import json
from pathlib import Path

har = json.loads(Path("sample.har").read_text())
for entry in har["log"].get("entries", []):
    req = entry.get("request", {})
    if req.get("method") == "POST" and "/api/users" in req.get("url", ""):
        req["url"] = req["url"].replace("/api/users", "/api/v2/users", 1)
        req.setdefault("queryString", []).append({"name": "source", "value": "ci"})
        break
Path("sample_drift.har").write_text(json.dumps(har, indent=2))
PY

"$AF_BIN" capture import sample_drift.har --allowed-hosts api.example.com --name "Magic Drift"
CAPTURE_DRIFT="$(latest_dir .toolwright/captures)"
"$AF_BIN" compile --capture "$CAPTURE_DRIFT" --scope first_party_only --format all
ARTIFACT_DRIFT="$(latest_dir .toolwright/artifacts)"
TOOLS_DRIFT=".toolwright/artifacts/${ARTIFACT_DRIFT}/tools.json"
POLICY_DRIFT=".toolwright/artifacts/${ARTIFACT_DRIFT}/policy.yaml"
TOOLSETS_DRIFT=".toolwright/artifacts/${ARTIFACT_DRIFT}/toolsets.yaml"

# Force a signature/path change in the drift artifact to simulate a changed endpoint contract.
"$AF_PYTHON" - "$TOOLS_DRIFT" <<'PY'
import json
import sys
from pathlib import Path

tools_path = Path(sys.argv[1])
payload = json.loads(tools_path.read_text())
for action in payload.get("actions", []):
    method = action.get("method", "GET").upper()
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        action["path"] = f"{action.get('path', '/').rstrip('/')}/v2"
        original_sig = str(action.get("signature_id", "sig"))
        action["signature_id"] = f"drift_{original_sig}"
        action["tool_id"] = action["signature_id"]
        break
tools_path.write_text(json.dumps(payload, indent=2))
PY

set +e
"$AF_BIN" drift --baseline "$BASELINE_BASE" --capture "$CAPTURE_DRIFT" --format both >/tmp/af_drift.log 2>&1
DRIFT_EXIT=$?
set -e
if [[ $DRIFT_EXIT -eq 0 ]]; then
  fail "expected drift command to report non-zero for changed endpoint"
fi

set +e
"$AF_BIN" gate sync --tools "$TOOLS_DRIFT" --policy "$POLICY_DRIFT" --toolsets "$TOOLSETS_DRIFT" --lockfile toolwright.lock.yaml >/tmp/af_sync2.log 2>&1
SYNC2_EXIT=$?
cp toolwright.lock.yaml "$TOOLPACK_DIR/lockfile/toolwright.lock.yaml"
set -e
if [[ $SYNC2_EXIT -eq 0 ]]; then
  fail "expected second gate sync to fail with pending approvals"
fi

set +e
"$AF_BIN" gate check --lockfile "$TOOLPACK_DIR/lockfile/toolwright.lock.yaml" >/tmp/af_check_fail.log 2>&1
CHECK_EXIT=$?
set -e
if [[ $CHECK_EXIT -eq 0 ]]; then
  fail "expected gate check to fail until re-approval"
fi

# Update toolpack with drifted artifacts for final gate allow+check
cp "$TOOLS_DRIFT" "$TOOLPACK_DIR/artifact/tools.json"
cp "$TOOLSETS_DRIFT" "$TOOLPACK_DIR/artifact/toolsets.yaml"
cp "$POLICY_DRIFT" "$TOOLPACK_DIR/artifact/policy.yaml"
cp toolwright.lock.yaml "$TOOLPACK_DIR/lockfile/toolwright.lock.yaml"

"$AF_BIN" gate allow --all --lockfile "$TOOLPACK_DIR/lockfile/toolwright.lock.yaml" --by "ci@toolwright"
"$AF_BIN" gate snapshot --lockfile "$TOOLPACK_DIR/lockfile/toolwright.lock.yaml"
"$AF_BIN" gate check --lockfile "$TOOLPACK_DIR/lockfile/toolwright.lock.yaml"

log "Magic moment harness passed"

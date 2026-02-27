# Toolwright Golden Path

Copy-paste runbook. Requires only `python3 >= 3.11`. Works offline, no accounts needed.

## Prerequisites

- Python 3.11+
- macOS or Linux
- No network access required (uses bundled fixtures)

## Steps

### 1. Create workspace and install

```bash
WORKDIR=$(mktemp -d)
cd "$WORKDIR"
python3 -m venv .venv
source .venv/bin/activate
pip install "toolwright[mcp]"
```

The `[mcp]` extra installs the MCP runtime needed for Step 5 (serve). For local dev install from repo checkout:

```bash
pip install -e "/path/to/Toolwright[mcp]"
```

### 2. Generate a fixture toolpack (offline)

```bash
cask --no-interactive demo --generate-only --out "$WORKDIR"
```

This imports the bundled `sample.har` fixture, compiles 8 API tools, and produces:

- `$WORKDIR/toolpacks/<tp_id>/toolpack.yaml` — toolpack manifest
- `$WORKDIR/toolpacks/<tp_id>/artifact/tools.json` — tool definitions
- `$WORKDIR/toolpacks/<tp_id>/lockfile/toolwright.lock.pending.yaml` — pending lockfile

**Expected output (summary):**
```
8 tools compiled from bundled API fixture
Toolpack:     $WORKDIR/toolpacks/tp_<hash>/toolpack.yaml
Pending lock: $WORKDIR/toolpacks/tp_<hash>/lockfile/toolwright.lock.pending.yaml
Pending:      8 tools awaiting approval
```

> **Note:** The toolpack contains 8 tools across multiple toolsets (readonly, operator). When serving, the server defaults to the `readonly` toolset, so `tools/list` returns fewer tools (typically 4) than the total in `tools.json`.

### 3. Approve all tools

```bash
# Expect exactly one toolpack
TP_COUNT=$(ls -1d "$WORKDIR"/toolpacks/tp_* 2>/dev/null | wc -l)
[[ "$TP_COUNT" -eq 1 ]] || { echo "Expected 1 toolpack, found $TP_COUNT"; exit 1; }
TOOLPACK_DIR=$(ls -1d "$WORKDIR"/toolpacks/tp_*)
cask --no-interactive --root "$WORKDIR" gate allow --all \
  --lockfile "$TOOLPACK_DIR/lockfile/toolwright.lock.pending.yaml"
```

**Expected output:**
```
Approved 8 tools
```

This creates `$TOOLPACK_DIR/lockfile/toolwright.lock.yaml` (the approved lockfile).

### 4. Verify the gate passes

```bash
cask --no-interactive --root "$WORKDIR" gate check \
  --lockfile "$TOOLPACK_DIR/lockfile/toolwright.lock.yaml"
```

**Expected output (exit code 0):**
```
All tools approved with verified baseline snapshot
```

### 5. Prove a tool call succeeds (dry-run MCP)

Start the MCP server in dry-run mode with the **approved lockfile** and send a single tool call. Passing `--lockfile` explicitly proves the server loaded approved governance (without it, serve refuses to start). The `recv_until_id` helper matches JSON-RPC responses by `id`, avoiding desync from server notifications:

```bash
APPROVED_LOCK="$TOOLPACK_DIR/lockfile/toolwright.lock.yaml"
export WORKDIR TOOLPACK_DIR APPROVED_LOCK
python3 -c "
import json, subprocess, sys, os, time, select

proc = subprocess.Popen(
    ['cask', '--no-interactive', '--root', os.environ['WORKDIR'],
     'serve', '--toolpack', os.environ['TOOLPACK_DIR'] + '/toolpack.yaml',
     '--lockfile', os.environ['APPROVED_LOCK'], '--dry-run'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True)

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

# Prefer get_products, fall back to first available tool
tool_name = next((t['name'] for t in tools if t['name'] == 'get_products'), None)
tool_name = tool_name or (tools[0]['name'] if tools else None)
if not tool_name:
    raise RuntimeError('No tools returned')
print(f'Tools listed: {len(tools)}')

send({'jsonrpc':'2.0','id':3,'method':'tools/call',
      'params':{'name':tool_name,'arguments':{}}})
call_resp = recv_until_id(3)
content = call_resp['result']['content'][0]['text']
result = json.loads(content)
print(f'Tool called: {tool_name}')
print(f'Decision:    {result[\"decision\"]}')
print(f'Reason:      {result[\"reason_code\"]}')

proc.terminate()
try:
    proc.communicate(timeout=2)
except subprocess.TimeoutExpired:
    proc.kill()
    proc.communicate()
"
```

> **Debugging:** If this step fails, run the automated script (`scripts/cleanroom_golden_path.sh`) with `CASK_KEEP_WORKDIR=1` — it captures server stderr to `$WORKDIR/mcp_serve_stderr.log`.

**Expected output:**
```
Tools listed: 4
Tool called: get_products
Decision:    allow
Reason:      allowed_policy
```

### 6. Verify contracts

```bash
cask --no-interactive --root "$WORKDIR" verify \
  --toolpack "$TOOLPACK_DIR/toolpack.yaml" --mode contracts
```

**Expected output (exit code 0):**
```
Verification complete: tp_<hash>
  Mode: contracts
  Governance mode: approved
  Status: pass
```

### 7. Inspect artifacts

After the golden path, these files exist:

```
$WORKDIR/
├── toolpacks/tp_<hash>/
│   ├── toolpack.yaml                          # toolpack manifest
│   ├── artifact/
│   │   ├── tools.json                         # 8 tool definitions
│   │   ├── policy.yaml                        # generated policy rules
│   │   ├── toolsets.yaml                      # readonly/operator toolsets
│   │   └── baseline.json                      # endpoint snapshot
│   └── lockfile/
│       ├── toolwright.lock.pending.yaml          # initial pending lockfile
│       └── toolwright.lock.yaml                  # approved lockfile
├── captures/cap_<hash>/                       # imported capture session
├── artifacts/art_<hash>/                      # compiled artifacts
└── reports/verify_tp_<hash>.json              # verification report
```

## Automated Script

Run the entire golden path with a single command:

```bash
./scripts/cleanroom_golden_path.sh
```

Or from a local dev checkout:

```bash
CASK_DEV=1 ./scripts/cleanroom_golden_path.sh
```

To pin a specific version (for reproducible CI):

```bash
CASK_VERSION=0.2.0rc1 ./scripts/cleanroom_golden_path.sh
```

To keep the workspace for debugging failures:

```bash
CASK_KEEP_WORKDIR=1 CASK_DEV=1 ./scripts/cleanroom_golden_path.sh
```

The workspace path is printed in the Result Summary. All artifacts (toolpack, lockfile, verify report, MCP server stderr log) remain in the workspace for inspection.

# Toolwright

> Self-expanding, self-repairing, human-correctable tool infrastructure for AI agents.

AI agents today are trapped in static toolkits. When tools break, agents fail. When agents need new capabilities, humans must manually build them. When agents misuse tools, there's no way to correct behavior without retraining.

**Toolwright closes the full loop:**

Tool doesn't exist &rarr; tool exists &rarr; tool broke &rarr; **tool fixed** &rarr; agent misused it &rarr; **agent corrected**

Point it at any web app. It discovers API endpoints, compiles governed MCP tools, and enforces safety policies -- all without writing a single line of code.

## Try It in 30 Seconds

```bash
pip install toolwright
toolwright demo
```

That's it. Toolwright captures a sample API, compiles governed tools, generates a lockfile, and shows you the full pipeline end to end.

## Installation

```bash
pip install toolwright
```

For browser-based API discovery:

```bash
pip install "toolwright[playwright]"
playwright install chromium
```

For MCP server functionality:

```bash
pip install "toolwright[mcp]"
```

Install everything:

```bash
pip install "toolwright[all]"
```

## Quick Start

### 1. Initialize

```bash
toolwright init
```

### 2. Discover and compile tools

**Option A: Browser capture** (automatic API discovery)

```bash
toolwright mint https://app.example.com -a api.example.com
```

**Option B: Import from HAR file**

```bash
toolwright capture import recording.har -a api.example.com
toolwright compile --capture <capture_id> --scope first_party_only
```

**Option C: Import from OpenAPI spec**

```bash
toolwright capture import https://api.example.com/openapi.json
toolwright compile --capture <capture_id> --scope first_party_only
```

### 3. Approve tools

```bash
# Review what was discovered
toolwright gate sync --toolpack .toolwright/toolpacks/example-api/toolpack.yaml

# Approve all tools (or selectively)
toolwright gate allow --all --toolpack .toolwright/toolpacks/example-api/toolpack.yaml

# Create a tamper-proof snapshot
toolwright gate snapshot --toolpack .toolwright/toolpacks/example-api/toolpack.yaml
```

### 4. Start the governed MCP server

```bash
toolwright serve --toolpack .toolwright/toolpacks/example-api/toolpack.yaml
```

### 5. Connect to your AI agent

```bash
# Generate MCP client config for Claude Desktop, Cursor, etc.
toolwright config --toolpack .toolwright/toolpacks/example-api/toolpack.yaml
```

### What just happened?

1. **Discover**: Toolwright captured real API traffic and identified every endpoint, method, and parameter.
2. **Compile**: Those raw observations became typed MCP tool definitions with inferred schemas and risk tiers.
3. **Govern**: A cryptographic lockfile tracks approval state. Nothing runs without explicit sign-off.
4. **Serve**: The MCP server exposes only approved tools, enforcing policy, confirmation gates, and circuit breakers at runtime.

Your agent now has governed, auditable access to the API -- and Toolwright keeps watching for drift, failures, and misuse.

## The Five Pillars

| Pillar | What It Does |
|--------|-------------|
| **CONNECT** | Discover, compile, and register new API tools at runtime |
| **GOVERN** | Risk-classify, sign, approve, and audit every tool |
| **HEAL** | Diagnose failures and recompile broken tools automatically |
| **KILL** | Circuit-break misbehaving tools with instant kill switches |
| **CORRECT** | Enforce durable behavioral rules that persist across sessions |

## Authentication

Set auth via environment variable (recommended):

```bash
export TOOLWRIGHT_AUTH_HEADER="Bearer your-token-here"
toolwright serve --toolpack .toolwright/toolpacks/example-api/toolpack.yaml
```

Or per-host for multi-API toolpacks:

```bash
export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer github-token"
export TOOLWRIGHT_AUTH_API_STRIPE_COM="Bearer stripe-token"
```

Or via CLI flag:

```bash
toolwright serve --toolpack .toolwright/toolpacks/example-api/toolpack.yaml --auth "Bearer your-token"
```

**Priority order:** `--auth` flag / `TOOLWRIGHT_AUTH_HEADER` env var > per-host `TOOLWRIGHT_AUTH_<HOST>` env var.

Per-host env var naming: replace dots and hyphens with underscores, uppercase everything. `api.github.com` becomes `TOOLWRIGHT_AUTH_API_GITHUB_COM`.

## Key Features

### Automatic API Discovery

Point Toolwright at any web application and it automatically:
- Captures HTTP traffic via browser automation or HAR import
- Identifies API endpoints, methods, and parameters
- Infers input schemas from observed requests
- Detects authentication patterns (Bearer, OAuth, API keys)
- Classifies risk tiers (read vs write operations)

### Governance & Approval

Every tool goes through a governance pipeline:
- **Risk classification**: Automatic tiering based on HTTP method and endpoint patterns
- **Ed25519 signing**: Cryptographic approval of tool definitions
- **Lockfile integrity**: Tamper-evident approval records
- **Policy engine**: Configurable rules for method filtering, rate limits, and access control
- **Audit logging**: Every decision (allow/deny) is logged with full context

### Drift Detection

Detect when APIs change underneath your tools:

```bash
toolwright drift --capture-a <old> --capture-b <new>
```

### Repair Engine

Automatically diagnose and fix broken tools:

```bash
toolwright repair --toolpack .toolwright/toolpacks/example-api/toolpack.yaml
```

### Health Checker (HEAL Pillar)

Non-mutating health probes verify your API endpoints are reachable without causing side effects. Integrated into the meta-server and available as a standalone CLI command:

```bash
# CLI: probe all endpoints in a tools manifest
toolwright health --tools output/tools.json
```

The health checker is also wired into the `toolwright_health_check` and `toolwright_diagnose_tool` meta-tools, so agents can probe endpoint health programmatically via MCP.

```python
# Python API
from toolwright.core.health.checker import HealthChecker

checker = HealthChecker()
actions = [
    {"name": "get_user", "method": "GET", "host": "api.example.com", "path": "/api/users/{id}"},
    {"name": "create_user", "method": "POST", "host": "api.example.com", "path": "/api/users"},
]

# Probe all endpoints concurrently
results = await checker.check_all(actions)
for r in results:
    if not r.healthy:
        print(f"{r.tool_id}: {r.failure_class} (HTTP {r.status_code})")
```

Failure classification: `auth_expired`, `endpoint_gone`, `rate_limited`, `server_error`, `network_unreachable`, `schema_changed`.

### OAuth2 Token Management

Per-host OAuth2 client-credentials flow with automatic token refresh:

```python
from toolwright.core.auth.oauth import OAuthCredentialProvider, OAuthConfig

provider = OAuthCredentialProvider(expiry_margin_seconds=60)
provider.configure("api.example.com", OAuthConfig(
    token_url="https://auth.example.com/token",
    client_id="my-client",
    client_secret="my-secret",
    scopes=["read", "write"],
))

token = await provider.get_token("api.example.com")  # Cached + auto-refresh
```

Install the optional OAuth dependency: `pip install "toolwright[oauth]"`

### MCP Meta-Server

Toolwright exposes introspection and self-service tools via MCP, letting agents query and manage their own tool infrastructure:

**GOVERN** -- introspection:
- `toolwright_list_actions` -- list available tools
- `toolwright_check_policy` -- check if a tool call would be allowed
- `toolwright_risk_summary` -- get risk breakdown
- `toolwright_get_approval_status` -- check approval state
- `toolwright_get_action_details` -- get tool schema and metadata
- `toolwright_list_pending_approvals` -- find unapproved tools
- `toolwright_get_flows` -- get multi-step API workflows

**HEAL** -- diagnosis:
- `toolwright_diagnose_tool` -- diagnose tool issues (manifest, approval, breaker state)
- `toolwright_health_check` -- check if a tool exists and is approved

**KILL** -- circuit breakers:
- `toolwright_kill_tool` -- force a tool's circuit breaker open
- `toolwright_enable_tool` -- re-enable a killed tool
- `toolwright_quarantine_report` -- list all quarantined tools

**CORRECT** -- behavioral rules:
- `toolwright_add_rule` -- create a behavioral rule
- `toolwright_list_rules` -- list rules with optional kind filter
- `toolwright_remove_rule` -- remove a rule by ID

### Behavioral Rules (CORRECT Pillar)

Define persistent behavioral constraints that agents must follow across sessions. Six rule types cover common safety patterns:

```bash
# Require get_user before update_user
toolwright rules add --kind prerequisite --target update_user \
  --requires get_user --description "Must fetch before update"

# Block delete_user entirely
toolwright rules add --kind prohibition --target delete_user \
  --description "Never delete users"

# Restrict parameter values
toolwright rules add --kind parameter --target update_user \
  --param-name role --allowed-values "user,moderator" \
  --description "Role must be user or moderator"

# Rate limit search calls
toolwright rules add --kind rate --target search \
  --max-calls 10 --description "Max 10 searches per session"

# List all rules
toolwright rules list

# Start server with rules enforced
toolwright serve --toolpack toolpack.yaml --rules-path .toolwright/rules.json
```

When an agent violates a rule, Toolwright returns structured feedback explaining what went wrong and how to fix it -- no retraining required.

### Circuit Breakers (KILL Pillar)

Per-tool circuit breakers automatically trip after repeated failures and recover after a timeout. Operators can also manually kill or enable tools:

```bash
# Kill a tool immediately
toolwright kill flaky_api --reason "Upstream 500s"

# Check quarantined tools
toolwright quarantine

# Re-enable a tool
toolwright enable flaky_api

# Check a specific breaker
toolwright breaker-status flaky_api

# Start server with circuit breakers
toolwright serve --toolpack toolpack.yaml --circuit-breaker-path .toolwright/state/circuit_breakers.json
```

The circuit breaker follows a three-state model:
- **CLOSED** (normal) -- tool calls pass through. Trips OPEN after 5 consecutive failures.
- **OPEN** (blocked) -- all tool calls blocked. Auto-transitions to HALF_OPEN after 60s timeout.
- **HALF_OPEN** (probing) -- allows one probe call. Resets to CLOSED after 3 successes, or back to OPEN on failure.

Manually killed tools never auto-recover -- they require explicit `toolwright enable`.

### Confirmation Flow

Write operations require human confirmation:
1. Agent calls a POST/PUT/DELETE tool
2. Toolwright returns a confirmation token
3. Human grants the token: `toolwright confirm grant <token>`
4. Agent retries with the granted token
5. Single-use: replay is automatically blocked

### Dry Run Mode

Test tool execution without making real HTTP requests:

```bash
toolwright serve --toolpack toolpack.yaml --dry-run
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `toolwright init` | Initialize project with guided setup |
| `toolwright demo` | Run self-contained demo of the full pipeline |
| `toolwright mint` | Browser-based API discovery and tool compilation |
| `toolwright capture import` | Import HAR files or OpenAPI specs |
| `toolwright compile` | Compile captured traffic into governed tools |
| `toolwright gate sync` | Sync lockfile with compiled tools |
| `toolwright gate status` | List tool approval states |
| `toolwright gate allow` | Approve tools for use |
| `toolwright gate block` | Block tools from use |
| `toolwright gate snapshot` | Create tamper-proof approval snapshot |
| `toolwright gate check` | Verify lockfile integrity (CI gate) |
| `toolwright gate reseal` | Re-sign approval signatures |
| `toolwright serve` | Start the governed MCP server |
| `toolwright config` | Generate MCP client configuration |
| `toolwright drift` | Detect API changes between captures |
| `toolwright repair` | Diagnose and fix broken tools |
| `toolwright doctor` | Check system health and dependencies |
| `toolwright health` | Probe endpoint health |
| `toolwright lint` | Validate tool definitions |
| `toolwright verify` | Run contract and baseline verification |
| `toolwright diff` | Compare current tools against approved baseline |
| `toolwright rules add` | Add a behavioral rule |
| `toolwright rules list` | List all behavioral rules |
| `toolwright rules remove` | Remove a behavioral rule |
| `toolwright rules show` | Show rule details |
| `toolwright rules export` | Export rules to JSON |
| `toolwright rules import` | Import rules from JSON |
| `toolwright kill` | Kill a tool (force circuit breaker open) |
| `toolwright enable` | Re-enable a killed tool |
| `toolwright quarantine` | List all killed/tripped tools |
| `toolwright breaker-status` | Check a tool's circuit breaker state |
| `toolwright confirm grant` | Grant a confirmation token |
| `toolwright status` | Show project status |
| `toolwright inspect` | Start the MCP meta-server for introspection |

**Alias:** `tw` works as a shorthand for `toolwright`.

## Architecture

```
  Agent (Claude, GPT, etc.)
       |
       v
  +---------------+
  |  MCP Server   |  <-- toolwright serve
  |  (governed)   |
  +-------+-------+
          |
  +-------+-------+
  | Policy        |  Risk tiers, method filtering,
  | Engine        |  rate limits, confirmations
  +-------+-------+
          |
  +-------+-------+
  | Decision      |  Allow / Deny / Confirm
  | Engine        |  with audit trail
  +-------+-------+
          |
  +-------+-------+
  | Rule          |  Prerequisite, prohibition,
  | Engine        |  parameter, sequence, rate,
  | (CORRECT)     |  approval rules
  +-------+-------+
          |
  +-------+-------+
  | Circuit       |  Per-tool CLOSED/OPEN/HALF_OPEN
  | Breaker       |  with auto-recovery & kill switch
  | (KILL)        |
  +-------+-------+
          |
          v
    Upstream API
```

## Design Principles

- **Safe by default**: All capture and enforcement requires explicit allowlists
- **Redaction on**: Sensitive data (cookies, tokens, PII) is removed by default
- **Audit everything**: Every compile, drift, and enforce decision is logged
- **Compiler mindset**: Convert behavior into contracts, not scan for vulnerabilities
- **Plug and play**: Minimal configuration required to get started

## License

MIT

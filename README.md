# Toolwright

> Self-expanding, self-repairing, human-correctable tool infrastructure for AI agents.

**Toolwright** is an MCP meta-server that gives AI agents the power to build, govern, repair, and correct their own tools at runtime. Point it at any web app, and it automatically discovers API endpoints, compiles governed MCP tools, and enforces safety policies -- all without writing a single line of code.

## Why Toolwright?

AI agents today are trapped in static toolkits. When tools break, agents fail. When agents need new capabilities, humans must manually build them. When agents misuse tools, there's no way to correct behavior without retraining.

Toolwright closes the full loop:

**Tool doesn't exist** &rarr; tool exists &rarr; tool broke &rarr; **tool fixed** &rarr; agent misused it &rarr; **agent corrected**

## The Five Pillars

| Pillar | What It Does |
|--------|-------------|
| **CONNECT** | Discover, compile, and register new API tools at runtime |
| **GOVERN** | Risk-classify, sign, approve, and audit every tool |
| **HEAL** | Diagnose failures and recompile broken tools automatically |
| **KILL** | Circuit-break misbehaving tools with instant kill switches |
| **CORRECT** | Enforce durable behavioral rules that persist across sessions |

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
toolwright gate sync --toolpack .toolwright/toolpacks/*/toolpack.yaml

# Approve all tools (or selectively)
toolwright gate allow --all

# Create a tamper-proof snapshot
toolwright gate snapshot
```

### 4. Start the governed MCP server

```bash
toolwright serve --toolpack .toolwright/toolpacks/*/toolpack.yaml
```

### 5. Connect to your AI agent

```bash
# Generate MCP client config for Claude Desktop, Cursor, etc.
toolwright config
```

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
toolwright repair --toolpack .toolwright/toolpacks/*/toolpack.yaml
```

### MCP Meta-Server

Toolwright exposes introspection tools via MCP, letting agents query their own tool infrastructure:
- `toolwright_list_actions` -- list available tools
- `toolwright_check_policy` -- check if a tool call would be allowed
- `toolwright_risk_summary` -- get risk breakdown
- `toolwright_get_approval_status` -- check approval state
- `toolwright_get_action_details` -- get tool schema and metadata
- `toolwright_list_pending_approvals` -- find unapproved tools
- `toolwright_get_flows` -- get multi-step API workflows

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
toolwright serve --toolpack ... --dry-run
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `toolwright init` | Initialize project with guided setup |
| `toolwright mint` | Browser-based API discovery and tool compilation |
| `toolwright capture import` | Import HAR files or OpenAPI specs |
| `toolwright compile` | Compile captured traffic into governed tools |
| `toolwright gate sync` | Sync lockfile with compiled tools |
| `toolwright gate allow` | Approve tools for use |
| `toolwright gate snapshot` | Create tamper-proof approval snapshot |
| `toolwright gate check` | Verify lockfile integrity |
| `toolwright serve` | Start the governed MCP server |
| `toolwright config` | Generate MCP client configuration |
| `toolwright drift` | Detect API changes between captures |
| `toolwright repair` | Diagnose and fix broken tools |
| `toolwright doctor` | Check system health and dependencies |
| `toolwright lint` | Validate tool definitions |
| `toolwright verify` | Run contract and baseline verification |
| `toolwright diff` | Compare current tools against approved baseline |
| `toolwright confirm grant` | Grant a confirmation token |
| `toolwright status` | Show project status |
| `toolwright inspect` | Start the MCP meta-server for introspection |

**Alias:** `tw` works as a shorthand for `toolwright`.

## Architecture

```
  Agent (Claude, GPT, etc.)
       │
       ▼
  ┌─────────────┐
  │  MCP Server  │  ← toolwright serve
  │  (governed)  │
  └──────┬──────┘
         │
  ┌──────┴──────┐
  │ Policy      │  Risk tiers, method filtering,
  │ Engine      │  rate limits, confirmations
  └──────┬──────┘
         │
  ┌──────┴──────┐
  │ Decision    │  Allow / Deny / Confirm
  │ Engine      │  with audit trail
  └──────┬──────┘
         │
         ▼
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

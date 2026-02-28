# Toolwright

> Give your AI agent any API. Safely.

Toolwright turns API traffic into governed MCP tools and keeps them working. Point it at an OpenAPI spec, a HAR file, or a live web app; it compiles typed tool definitions, classifies every tool by risk, and serves them through an MCP server that enforces approval gates, circuit breakers, and behavioral rules at runtime. Your credentials are automatically redacted from captured traffic. Nothing runs without your explicit sign-off.

![Toolwright hero demo](demos/outputs/hero.gif)

## What It Looks Like

```bash
$ toolwright mint https://dashboard.stripe.com -a api.stripe.com
  ✓ Captured 47 API calls across 12 endpoints
  ✓ Compiled 12 tools (8 read, 3 write, 1 admin)
  ✓ Risk classified: 3 low, 6 medium, 2 high, 1 critical
  ✓ Auth detected: Bearer token (Authorization header)
  ✓ Credentials redacted from captured traffic

  Set before serving:
    export TOOLWRIGHT_AUTH_API_STRIPE_COM="Bearer <your-token>"

$ toolwright gate allow --all        # review and approve every tool
$ toolwright serve                   # start the governed MCP server
  12 governed tools ready
```

The `-a` flag specifies which host to capture -- only traffic to that host is recorded. For OpenAPI specs and HAR files, the host is detected automatically.

```bash
# Later, the API changes under you:
$ toolwright repair plan
  SAFE (auto-apply):
    + update_user: response field added (role)
  APPROVAL_REQUIRED:
    ~ delete_user: path changed /users/{id} -> /v2/users/{id}

$ toolwright repair apply
  Applied 1 safe patch. 1 queued for your review.
```

> **No paths to memorize.** Toolwright auto-detects your toolpack when there's only one. For multiple toolpacks, run `toolwright use stripe` to set a default.

## Try It Now

```bash
pip install toolwright
toolwright demo
```

Compiles a governed toolpack from bundled traffic, enforces fail-closed gates, and writes a full audit log. Exit `0` means every safety check passed.

## Commands

**Getting started:**

```bash
toolwright demo          # see it work (60 seconds)
toolwright ship          # build + approve + serve (your API)
toolwright ship <url>    # one-command onboarding from URL
toolwright serve         # run your governed MCP server (stdio)
toolwright serve --http  # serve over HTTP with web dashboard
```

**Operations:**

```bash
toolwright drift         # check for API changes
toolwright repair plan   # see what needs fixing
toolwright repair apply  # apply fixes
toolwright kill <tool>   # emergency stop a tool
toolwright quarantine    # list stopped tools
toolwright watch status  # reconciliation status
```

**Sharing & notifications:**

```bash
toolwright share <toolpack>   # package into signed .twp bundle
toolwright install <file.twp> # verify + install a shared bundle
```

**All commands:** `toolwright --help`

## Why This Exists

APIs change silently. Tools break with no warning. Nobody knows until the agent starts failing. And giving an AI agent API access today still means writing MCP tool definitions by hand, then hoping it doesn't call a destructive endpoint.

Toolwright closes that gap. It compiles tools from real API traffic, classifies them by risk, enforces approval gates before anything can run, and automatically circuit-breaks tools that start failing -- before the failures cascade to your agent.

## How It Stays Safe

**Secrets are redacted before anything reaches disk.** Captured traffic is redacted in memory -- tokens, cookies, API keys, and PII are stripped before toolpacks, logs, and evidence bundles are written. Auth is injected at runtime via environment variables, never stored in any artifact Toolwright produces.

**Nothing runs without approval.** Toolwright is fail-closed. Every tool must pass through a gate review before it can execute. The approval is cryptographically signed and recorded in a tamper-evident lockfile. If a tool isn't explicitly approved, it doesn't run. There is no "allow by default" mode.

**You see everything before it ships.** During compilation, every tool is classified by risk tier -- critical (destructive operations), high (writes), medium (sensitive reads), low (read-only). You approve tools individually or by tier, with full visibility into what each one does.

**Agents propose, you decide.** Agents can propose new API capabilities and suggest behavioral rules through MCP meta-tools. Both create DRAFT proposals that require your explicit activation. The agent never gains a capability it didn't ask for, and you never approve something you haven't reviewed.

## When APIs Break

**Drift detection and repair.** When an API changes under you, drift detection catches it and repair proposes classified fixes -- safe (auto-apply), approval-required, or manual:

```bash
toolwright drift                           # detect what changed
toolwright repair plan                     # Terraform-style diff
toolwright repair apply                    # apply with confirmation
```

**Continuous reconciliation.** Start the MCP server with `--watch` and Toolwright monitors every tool on a risk-tier schedule. When drift is detected, safe patches auto-apply; risky ones queue for your review:

```bash
toolwright serve --watch --auto-heal safe
toolwright watch status                    # see per-tool health
```

**Snapshots and rollback.** Every auto-repair is preceded by a snapshot. If something goes wrong, restore the exact previous state:

```bash
toolwright snapshots                       # list available snapshots
toolwright rollback <snapshot-id>          # restore
```

## Runtime Safety

**Circuit breakers.** When an API starts failing, per-tool circuit breakers trip automatically after repeated errors, blocking further calls until the API recovers. You can also kill or re-enable tools manually:

```bash
toolwright kill search_api --reason "Upstream 500s"
toolwright quarantine             # see what's killed and why
toolwright enable search_api      # bring it back
```

![Circuit breaker lifecycle demo](demos/outputs/kill_cycle.gif)

**Behavioral rules.** Define constraints that persist across agent sessions -- no retraining, no prompt engineering. When a rule is violated, the agent gets structured feedback explaining what went wrong and how to proceed:

```bash
toolwright rules add --kind prerequisite --target update_issue \
  --requires get_repo --description "Read context before modifying"

toolwright rules add --kind prohibition --target delete_contents \
  --description "Never delete repository files"
```

Six rule types: prerequisites, prohibitions, parameter constraints, rate limits, call sequencing, and approval gates. Agents can suggest new rules via MCP meta-tools. Suggestions start as DRAFT and require `toolwright rules activate` before taking effect.

## Start Where You Are

| You have... | Run |
|------------|-----|
| A web app | `toolwright mint https://app.example.com -a api.example.com` |
| An OpenAPI spec | `toolwright capture import openapi.yaml` |
| A HAR file from DevTools | `toolwright capture import traffic.har` |
| OpenTelemetry traces | `toolwright capture import traces.json --input-format otel` |
| No idea | `toolwright ship` |

All paths converge: capture → compile → approve → serve.

## What's Inside

| Capability | What It Does | Maturity |
|-----------|-------------|----------|
| **Connect** | Compile MCP tools from any API source (browser, spec, HAR, OTEL) | Stable |
| **Govern** | Risk classification, cryptographic signing, approval gates, audit logging | Stable |
| **Heal** | Drift detection, auto-repair, continuous reconciliation, snapshots & rollback | Stable (incl. reconciliation & auto-heal) |
| **Kill** | Per-tool circuit breakers with auto-recovery and manual kill switches | Stable |
| **Correct** | Persistent behavioral rules with agent suggestion and human-gated activation | Stable |
| **Transport** | HTTP server, web dashboard, SSE live feed, token auth | Stable |
| **Share** | Signed .twp bundles for toolpack distribution | Stable |
| **Observe** | OTEL-compatible tracing, Prometheus metrics (no-op fallback) | Stable |
| **Notify** | Webhook notifications with Slack auto-detection | Stable |

87 capabilities. 2150+ tests.

Agents introspect their own governance via MCP meta-tools -- check risk summaries, diagnose failures, manage circuit breakers, and read behavioral rules. Agents can also propose new API capabilities and suggest behavioral rules; both create DRAFT proposals that require human approval before taking effect.

## Install

```bash
pip install toolwright                 # core
pip install "toolwright[playwright]"   # + browser capture
pip install "toolwright[mcp]"          # + MCP server
pip install "toolwright[all]"          # everything
```

`tw` works as shorthand for `toolwright`. Full docs: **[docs/user-guide.md](docs/user-guide.md)**

## License

MIT
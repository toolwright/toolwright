# Toolwright

Give your AI agent safe API access in 60 seconds.

Toolwright compiles any REST API into governed MCP tools — with schema validation, auth isolation, and drift detection and repair built in.

The immune system for agent tools.

```bash
pip install "toolwright[all]"

toolwright create github
export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer ghp_yourToken"
# Paste the MCP config into Claude Desktop, restart — done.
```

Your agent now has governed access to GitHub's API. Your token never enters the LLM context.

For custom APIs, use `mint` to capture from a browser:

```bash
toolwright mint https://app.example.com -a api.example.com
toolwright gate allow --all
toolwright serve
```

## What you get

- **Tools from real API traffic** — Toolwright captures browser traffic and generates complete MCP tool definitions automatically
- **Auth never touches the LLM** — credentials are injected at the proxy layer, invisible to your agent
- **Drift detection** — catches API schema changes before your agent breaks
- **Schema validation** — every tool call validated against inferred schemas
- **Risk classification** — every tool tiered (low/medium/high/critical), nothing runs without explicit approval
- **Continuous health monitoring** — watches for API changes and self-heals before your agent breaks
- **Works with any MCP client** — Claude Desktop, Cursor, or any MCP-compatible platform

## Quickstarts

- **[GitHub API in 60 seconds](docs/quickstarts/github.md)** — `toolwright create github`
- **[Any REST API](docs/quickstarts/any-rest-api.md)** — browser capture for custom APIs

## How it works

```
                    ┌──────────────────────────────────────────────┐
  Browser traffic   │                                              │
  OpenAPI spec   ──>│   mint / capture   ──>   compile   ──>      │
  HAR file          │                                              │
                    │   toolpack (tools + policy + lockfile)        │
                    │                                              │
                    │   serve  ──>  governed MCP server             │
                    │     ├── auth injection (proxy layer)          │
                    │     ├── schema validation                     │
                    │     ├── risk-based approval gates             │
                    │     ├── circuit breakers                      │
                    │     └── drift detection                       │
                    └──────────────────────────────────────────────┘
```

1. **`mint`** opens a browser and captures API traffic. A smart probe detects auth requirements, OpenAPI specs, and GraphQL endpoints before capture starts.
2. **`compile`** (runs inside mint) infers schemas, generates MCP tool definitions, classifies risk tiers, creates tool groups, and builds drift baselines.
3. **`gate allow`** approves tools via a signed lockfile. Nothing executes without explicit approval.
4. **`serve`** runs the MCP server. Auth is injected at the proxy layer. Schema validation, circuit breakers, and behavioral rules enforce governance at runtime.

## Give your agent any API

| You have... | Run |
|------------|-----|
| A web app | `toolwright mint https://app.example.com -a api.example.com` |
| An OpenAPI spec | `toolwright capture import openapi.yaml -a api.example.com` |
| A HAR file | `toolwright capture import traffic.har -a api.example.com` |
| OTEL traces | `toolwright capture import traces.json --input-format otel -a api.example.com` |

All paths produce a toolpack: tool definitions + policy + lockfile + drift baselines.

## Serving options

```bash
toolwright serve                                    # stdio (Claude Desktop)
toolwright serve --http                             # HTTP with web dashboard
toolwright serve --scope repos,issues               # serve specific tool groups
toolwright serve --max-risk low                     # cap risk tier exposure
toolwright serve -H "Notion-Version: 2022-06-28"   # inject custom headers
toolwright serve --watch --auto-heal safe           # continuous drift detection
```

**Tool groups** keep context manageable. Toolwright auto-groups tools by URL path during compilation. Use `--scope` to serve subsets:

```bash
toolwright groups list                    # see available groups
toolwright groups show repos              # inspect a group
toolwright serve --scope repos            # serve just that group
```

## Commands

```bash
# Quick start
toolwright create github                 # create tools from a known API
toolwright mint <url> -a <api-host>      # capture from browser + compile
toolwright gate allow --all              # approve tools
toolwright serve                         # start MCP server

# Operations
toolwright groups list                   # browse tool groups
toolwright recipes list                  # list bundled API recipes
toolwright recipes show shopify          # show recipe details
toolwright auth check                    # verify auth configuration
toolwright drift                         # detect API changes
toolwright config                        # generate MCP client config

# Advanced
toolwright repair plan                   # Terraform-style drift repair
toolwright rules add --kind rate ...     # behavioral constraints
toolwright rules template list           # browse bundled rule templates
toolwright rules template apply crud-safety  # create DRAFT rules from template
toolwright kill <tool> --reason "..."    # circuit breaker kill switch
toolwright serve --watch --auto-heal safe # continuous reconciliation

# All commands
toolwright --help
```

## How is this different from other MCP servers?

Most MCP servers are hand-written wrappers around specific APIs. They break when the API changes. They expose credentials to the LLM. They don't validate inputs or outputs.

Toolwright compiles tools from real traffic, governs them at runtime, and detects drift automatically. Credentials never enter the LLM context. Every tool call is validated against inferred schemas. Circuit breakers prevent cascading failures. Behavioral rules constrain what agents can do.

## Install

```bash
pip install "toolwright[all]"             # MCP server + browser capture + TUI
python -m playwright install chromium     # browser binary for traffic capture
```

Or install components separately:

```bash
pip install toolwright                    # core
pip install "toolwright[mcp]"             # + MCP server
pip install "toolwright[playwright]"      # + browser capture
```

`tw` works as shorthand for `toolwright`.

## Documentation

- [User Guide](docs/user-guide.md) — full reference
- [Architecture](docs/architecture.md) — how it works internally
- [Quickstart: GitHub](docs/quickstarts/github.md)
- [Quickstart: Any REST API](docs/quickstarts/any-rest-api.md)
- [Known Limitations](docs/known-limitations.md)
- [Troubleshooting](docs/troubleshooting.md)

## License

MIT

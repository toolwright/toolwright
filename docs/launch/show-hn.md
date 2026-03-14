# Show HN: Toolwright -- Point at any API, get governed AI tools in 10 seconds

## Post Title

Show HN: Toolwright -- Governed AI tools from any API. MCP, CLI, or REST.

## Post Body

Toolwright is an open-source CLI that turns any API into governed AI tools. Point it at an OpenAPI spec, a URL, a HAR file, or even a running web app, and you get a toolpack: compiled tool definitions with schemas, risk tiers, policies, and an Ed25519-signed lockfile.

Why governance? When Claude or GPT calls your tools, things go wrong: schemas change silently, agents call destructive endpoints, broken APIs waste your token budget. Toolwright treats this like a supply chain problem. Every tool change is gated behind signed approval. Circuit breakers trip on failures. Behavioral rules constrain what agents can do.

The governance engine is transport-agnostic. Same lockfile, same rules, same audit trail -- whether you serve via MCP (for Claude Desktop, Cursor), CLI (JSONL on stdin/stdout, ~30x fewer tokens), or REST. You don't have to pick a side in the MCP debate.

- GitHub: https://github.com/yourusername/toolwright
- PyPI: `pip install toolwright`
- License: MIT
- Python 3.11+

Try it in 60 seconds:
```
pip install toolwright
toolwright create github
export TOOLWRIGHT_AUTH_API_GITHUB_COM="Bearer ghp_yourToken"
toolwright serve
```

## First Comment

Hey HN, creator here. I built Toolwright because I kept hitting the same problems using AI agents with real APIs:

**The problem:** MCP servers are the new dependency you can't audit. When I pointed Claude at a third-party MCP server with 200 tools, I had no way to know what changed since yesterday. A tool could silently gain write permissions, its schema could break, or the upstream API could start returning garbage. There was no lockfile, no approval workflow, no circuit breaker.

**What Toolwright does:**

1. **CONNECT** -- Capture any API into governed tools. `toolwright create github` produces 1062 tools from GitHub's OpenAPI spec. `toolwright wrap npx -y @modelcontextprotocol/server-github` wraps an existing MCP server without recreating its tools.

2. **GOVERN** -- Ed25519-signed lockfile gates every change. New tools, changed schemas, expanded capabilities -- all require explicit approval. Like `package-lock.json` but for AI tool permissions.

3. **CORRECT** -- Behavioral rules constrain invocations at runtime. "Require read before delete." "Rate limit to 10 calls/minute." Six composable rule types.

4. **KILL** -- Three-state circuit breakers (closed/open/half-open). After 5 consecutive failures, agents can't call it. Automatic recovery with proof.

5. **HEAL** -- k8s-style reconciliation loop. Safe drift auto-merges. Risky changes escalate. Terraform-style repair plans.

**The transport-agnostic bit:** The governance engine doesn't care how agents talk to it. MCP is great for Claude Desktop. But if you're building a shell-based agent, the CLI transport serves the same governed tools via JSONL at ~1/30th the token cost. Same lockfile. Same rules. Same audit trail. We're not anti-MCP -- we think governance should work regardless of transport.

**Architecture:** GovernanceRuntime wires all subsystems (manifest, lockfile, policy, audit, decision engine, rules, circuit breakers) into a GovernanceEngine. Transport adapters (MCP, CLI, REST) are thin wrappers. The test suite runs identical governance scenarios across all transports and asserts identical behavior.

**What's next:** REST transport adapter, `toolwright wrap` for CLI tools (govern `gh`, `aws`, any CLI), GitHub Action for CI governance checks.

Alpha quality -- I'm shipping fast and fixing things. Would love feedback on the governance model, the transport-agnostic approach, and what APIs you'd want to try it with.

# Twitter/X Launch Thread

## Tweet 1 (Hook)

I've been building governed AI tools for the past few months.

Today I'm open-sourcing Toolwright -- point at any API, get governed tools in 10 seconds.

MCP, CLI, or REST. Same governance. Same audit trail.

pip install toolwright

Thread:

## Tweet 2 (The Problem)

The problem: MCP servers are the new unaudited dependency.

When Claude calls a tool, you have no lockfile, no approval flow, no circuit breaker.

Schemas change silently. Agents call destructive endpoints. Broken APIs waste your token budget.

## Tweet 3 (The Solution)

Toolwright treats AI tools like a supply chain.

- Ed25519-signed lockfile (like package-lock.json for tool permissions)
- Circuit breakers that trip after 5 failures
- Behavioral rules ("require read before delete")
- Drift detection with auto-healing

## Tweet 4 (Transport-Agnostic)

The governance engine is transport-agnostic.

Same lockfile, same rules, same audit trail:
- MCP for Claude Desktop / Cursor
- CLI transport (JSONL, ~30x fewer tokens)
- REST (coming soon)

You don't have to pick a side in the MCP debate.

## Tweet 5 (Speed)

How fast?

toolwright create github

1062 governed tools from GitHub's OpenAPI spec. Lockfile signed. Risk tiers assigned. Ready to serve.

Full governance lifecycle runs in under 1 second.

## Tweet 6 (Works With Anything)

Works with anything you have:
- OpenAPI specs
- URLs
- HAR files
- Live web apps (browser capture)
- Existing MCP servers (wrap mode)

All paths produce the same governed artifacts.

## Tweet 7 (CTA)

MIT licensed. Python 3.11+.

- GitHub: https://github.com/toolwright/toolwright
- PyPI: pip install toolwright
- Quickstart: 60 seconds from install to governed tools

I'm shipping fast and fixing things. Would love feedback.

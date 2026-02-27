# Toolwright

> Self-expanding, self-repairing, human-correctable tool infrastructure for AI agents.

**Toolwright** is an MCP meta-server that gives AI agents the power to build, govern, repair, and correct their own tools at runtime.

## Installation

```bash
pip install toolwright
```

## The Five Pillars

| Pillar | What It Does |
|--------|-------------|
| **CONNECT** | Discover, compile, and register new API tools at runtime |
| **GOVERN** | Risk-classify, sign, approve, and audit every tool |
| **HEAL** | Diagnose failures and recompile broken tools automatically |
| **KILL** | Circuit-break misbehaving tools with instant kill switches |
| **CORRECT** | Enforce durable behavioral rules that persist across sessions |

## Quick Start

```bash
# Initialize toolwright in your project
toolwright init

# Capture an API and compile governed tools
toolwright mint https://app.example.com -a api.example.com

# Approve tools for use
toolwright gate allow --all

# Start the governed MCP server
toolwright serve --toolpack .toolwright/toolpacks/*/toolpack.yaml
```

## License

MIT

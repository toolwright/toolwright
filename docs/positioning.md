# Toolwright Positioning Source Of Truth

Use this file as the canonical messaging brief for README edits, docs, launch copy, demos, package metadata, and repo/about text.

## Audience

- Primary audience: technical adopters building or operating agents against real APIs
- Buyer pain: agent tool access must be safe, auditable, and resilient before it can be trusted in production
- Internal shorthand: generation is the on-ramp; governance and bounded self-healing are the moat

## Approved Core Phrases

- Category line: `The trusted MCP supply chain for AI tools.`
- Tagline: `The immune system for AI tools.`
- Core subhead: `Capture APIs or wrap existing MCP servers. Keep credentials out of model context, approve changes with signed lockfiles, enforce fail-closed runtime controls, detect drift, verify behavior, and auto-repair safely.`
- Short description: `Trusted MCP supply chain for AI tools with signed approvals, fail-closed runtime, drift detection, verification, and bounded auto-repair.`

## Approved Product Promises

- `Credentials never enter model context`
- `Every tool change is signed and approved before it runs`
- `With watch or verify enabled, upstream API changes are surfaced before your agent breaks`

## Approved Repair Language

- `bounded self-healing`
- `snapshotted repair with operator rollback`
- `human-gated escalation`
- `safe by default`
- `operator-controlled override`

## Banned Phrases

- `API-to-MCP generator` as the category
- `self-evolving tools`
- `fully autonomous repair`
- `agent-led approvals`
- `agents fix production`
- `agents govern themselves`

## GitHub / PyPI / Registry Copy

- GitHub About / PyPI / registry description:
  `Trusted MCP supply chain for AI tools with signed approvals, fail-closed runtime, drift detection, verification, and bounded auto-repair.`
- Repo tagline / talk opener:
  `Toolwright is the trusted MCP supply chain for AI tools.`

## 30-Second Pitch

Toolwright turns API traffic or existing MCP servers into governed tool surfaces for agents. It keeps credentials out of model context, requires signed approval before tool changes can run, and surfaces upstream drift before agents fail in production when watch or verify is enabled. When safe fixes are possible, Toolwright applies bounded self-healing with verification, snapshots, operator rollback, and human-gated escalation for everything riskier.

## One-Paragraph Pitch

Toolwright is the trusted MCP supply chain for AI tools. It captures APIs or wraps existing MCP servers, compiles them into governed tool surfaces, and keeps the runtime safe after it ships. Credentials stay out of model context, every tool change lands behind a signed approval lockfile, runtime enforcement fails closed by default, and watch or verify can surface drift before agents break. Toolwright then verifies behavior and applies bounded self-healing with snapshots, operator rollback, and human-gated escalation, so teams can move from demos to real production trust.

## Launch Post Boilerplate

Toolwright is now positioned for what it actually does best: not just generating MCP tools, but acting as the trusted MCP supply chain for AI tools. You can capture APIs or wrap existing MCP servers, keep credentials out of model context, review and sign tool changes before they run, and surface upstream drift before your agents fail in production when watch or verify is enabled. The runtime stays fail-closed by default, and bounded self-healing handles safe maintenance with snapshots, operator rollback, and escalation when changes need a human. The goal is simple: make APIs agent-usable, then keep them safe and stable.

## Launch Bullets

- `Credentials never enter model context.`
- `Every tool change is signed and approved before it runs.`
- `With watch or verify enabled, upstream API changes are surfaced before your agent breaks.`

## Demo Narration Script

1. `Start with a governed toolpack generated from real API traffic.`
2. `Show that the tool surface exists, but nothing state-changing can run until the lockfile approves it.`
3. `Trigger a high-risk call and show the denial reason clearly: fail-closed, pending approval.`
4. `Approve the tool change through the signed lockfile.`
5. `Run the same call again and show governance still active through confirmation and policy checks.`
6. `Close by positioning drift detection and bounded self-healing as the reason the tool stays trustworthy after launch.`

## Demo Asset Roles

- Hero demo: `demos/outputs/hero.gif` and `demos/outputs/hero.mp4`
- Immune-system proof: `demos/outputs/kill_cycle.gif` and `demos/outputs/kill_cycle.mp4`

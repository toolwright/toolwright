# Your Agent's Tools Are Going to Break. Then What?

*March 2026*

---

Here's a failure mode nobody talks about at MCP demo day.

You build an agent. You give it access to Stripe, GitHub, your internal API. It works great in dev. You ship it. Two weeks later, Stripe changes a response field. Your agent doesn't know. It keeps calling the endpoint, keeps getting back data it doesn't understand, keeps retrying. By the time someone notices, the damage is done -- failed transactions, stale data, a confused agent that's been spinning its wheels for hours.

This isn't hypothetical. Composio's 2025 AI Agent Report found that 40% of multi-agent pilots fail within six months of deployment. Not because the LLM is bad. Not because the prompts are wrong. Because the infrastructure between the agent and the APIs it depends on is brittle, static, and blind.

We've been building walls when we need an immune system.

## The Wall Problem

The MCP ecosystem has exploded. There are 1,400+ servers, the market's growing 230% year-over-year, and every week there's a new tool for scanning, guardrailing, or gatekeeping MCP connections. This is genuinely important work -- tool poisoning attacks have a 72.8% success rate, 8,000+ MCP servers are sitting on the public internet with exposed admin panels, and command injection vulnerabilities are disturbingly common.

But here's what every one of these tools has in common: they're walls. They decide, at the moment a call is made, whether to let it through or block it. Static rules. Human-configured. Binary decisions.

Walls are necessary. They're just not sufficient.

Three things happen in production that walls can't handle:

**1. Silent drift.** APIs change under you. Not dramatically -- a new field here, a renamed parameter there, a path that moves from v1 to v2. Your guardrails don't know. They're still checking the same static rules they checked last week. The tool technically works, but it's returning data your agent can't use correctly. Nobody notices until the agent produces garbage outputs.

**2. Cascading failures.** One endpoint starts returning 500s. Your agent retries. The retry logic compounds. Downstream tools that depend on the first tool's output start failing too. OWASP flagged this exact pattern as ASI08 in their Top 10 for Agentic Applications. A wall can't help here -- by the time the call reaches the guardrail, it looks perfectly valid. The problem isn't the call. It's that the endpoint is dead and nobody told the agent.

**3. No learned boundaries.** Your agent makes a mistake -- it calls a destructive endpoint, hits a rate limit, accesses data it shouldn't. You fix the prompt. The agent makes the same mistake in a different context. You fix the prompt again. This cycle never ends because the correction lives in the prompt, not in the infrastructure. There's no persistent memory. No behavioral constraint that survives across sessions. Every conversation starts from zero.

These aren't edge cases. They're the normal operating conditions for any agent that talks to real APIs in production.

## What an Immune System Looks Like

A biological immune system doesn't just block pathogens at the door. It detects threats in real-time, responds proportionally, heals damaged tissue, and remembers what went wrong so it can respond faster next time.

That's the model I think agent tool infrastructure needs to follow.

**Detection** isn't a one-time scan. It's continuous monitoring -- checking every tool on a schedule calibrated to its risk level. Critical tools get checked every 2 minutes. Low-risk tools every 30 minutes. When an API drifts, you know within the monitoring interval, not when your agent crashes.

**Response** isn't binary allow/deny. It's per-tool circuit breakers that isolate failing tools before the failure cascades. One bad endpoint doesn't take down your whole agent. The breaker trips, the agent gets structured feedback about why the tool is unavailable, and every other tool keeps running. When the API recovers, the breaker probes it and automatically brings it back online.

**Healing** isn't "fix it yourself." It's classified repair proposals -- Terraform-style. Safe patches auto-apply (a new optional field? Just update the schema). Risky changes queue for human review (a path change? You should see this first). Every auto-repair is preceded by a snapshot you can roll back to. The system heals itself for low-risk changes and escalates appropriately for everything else.

**Memory** isn't prompt engineering. It's persistent behavioral rules -- prerequisites ("always read the repo before modifying issues"), prohibitions ("never delete files"), rate limits ("max 5 new issues per session"), parameter constraints ("label colors must be valid hex"). These rules survive across sessions. When an agent violates one, it gets structured feedback: here's what you did, here's what the rule says, here's what to do instead. The agent learns from the infrastructure, not from increasingly fragile system prompts.

And here's the part that I think changes the paradigm: **the agent participates in its own governance**. Through meta-tools, agents can check their own risk summaries, diagnose why a call was blocked, monitor the health of their tools, and even suggest new behavioral rules. These suggestions always start as drafts -- humans have final say. But the agent isn't just a passive subject of rules. It's an active participant in improving them.

## This Is Toolwright

I built Toolwright because I needed this immune system for my own agent work and it didn't exist.

The project has 83 capabilities across five pillars -- but the three that matter most are the ones nobody else is building:

**Heal.** Kubernetes-style continuous reconciliation monitors every tool. When APIs drift, repair proposals are generated, classified by safety, and either auto-applied or queued for review. Snapshots protect every change. You can roll back to any previous state.

**Kill.** Per-tool circuit breakers with a three-state model (closed, open, half-open) prevent cascading failures. When an API starts returning errors, the breaker trips and isolates that specific tool. Manual kill switches let you take down a tool instantly with a reason attached.

**Correct.** Six types of persistent behavioral rules give agents structured boundaries that survive across sessions. Agents can even suggest new rules through MCP meta-tools -- suggestions are always drafts until a human activates them.

The Connect and Govern pillars handle tool creation and approval gates -- compiling MCP tools from OpenAPI specs, HAR files, browser traffic, or OTEL traces, then risk-classifying and cryptographically signing every one. These are the foundation, but they're not what makes Toolwright different. Plenty of tools can generate MCP definitions. Plenty of tools can add guardrails. What nobody else has built is the living runtime that keeps tools working after they're deployed.

## Why I Think This Matters Now

Two things are happening simultaneously.

First, MCP adoption is going vertical. Every serious AI application is adding tool use. The protocol won. But "tool use in production" is about to expose every reliability gap that didn't exist in demo environments.

Second, self-healing is becoming the minimum bar for production AI infrastructure. Composio, Gartner, and the OWASP Agentic Security project are all pointing at the same conclusion: static defenses aren't enough for dynamic systems. If each step in an agent workflow has 95% reliability, a 20-step workflow succeeds only 36% of the time. The math gets worse as agents do more.

The window for establishing the "immune system" category for agent tools is right now. Not in a year when everyone's built their own version. Right now, when the problem is being felt but no standard solution exists.

## Try It

```bash
pip install toolwright
toolwright demo
```

Thirty seconds. Compiles governed tools from bundled traffic, proves fail-closed enforcement, and writes an auditable decision log.

Then, to build tools from your own API:

```bash
toolwright ship
```

It walks you through the full lifecycle -- capture, review, approve, verify, serve.

The code is MIT licensed. The repo is at [github.com/toolwright/toolwright](https://github.com/toolwright/toolwright). I'd genuinely appreciate feedback -- especially from people running agents against real APIs in production.

---

*Toolwright is open-source infrastructure for keeping AI agent tools alive in production. It detects API drift, circuit-breaks failing tools, enforces persistent behavioral rules, and lets agents participate in their own governance.*

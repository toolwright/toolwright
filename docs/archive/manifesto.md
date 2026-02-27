## Toolwright Manifesto

Agents are not coworkers. They are **remote scripts with keys**.

The agent boom is real. The failure mode is also real: we are letting probabilistic text generators silently acquire new capabilities inside prompts, then acting surprised when production explodes.

Toolwright is the line we should have drawn years ago.

It turns “what an agent can do” into an artifact you can diff, approve, enforce, and audit.

### The one sentence

**If it’s not in the lockfile, it’s blocked.**

---

## The world we’re walking into

MCP made tools first-class for models: servers expose tools with schemas so models can call real systems. ([Anthropic][1])
That’s the ignition. The fuel is “parallel agents” and background work. Emdash exists because people want multiple agents running in isolated worktrees, in parallel. ([docs.emdash.sh][2])
The result is obvious: more agents, more actions, more privileges, more surface area, more weird chain reactions.

And the ecosystem is already showing the cracks:

* OpenClaw is exploding because it “does things,” but the same deep access that makes it powerful makes it scary, and security concerns are front and center. ([Tom's Guide][3])
* Even “official” MCP servers have had serious vulnerabilities, and tool chaining can turn small flaws into big incidents. ([TechRadar][4])
  This is not theoretical. This is the new normal.

So no, the question is not “should agents exist.”
The question is: **do you want them to exist without adult supervision.**

---

## The core thesis

### Prompts are not a control plane

A prompt is:

* unreviewable at scale
* unversioned in the way that matters
* easy to drift
* impossible to enforce

If your governance is “read the prompt and trust the model,” you don’t have governance. You have vibes.

### Diffs are a control plane

A diff is:

* reviewable
* composable
* enforceable
* auditable
* the only thing teams actually know how to operate under pressure

Toolwright is built around one conviction:
**you cannot safely ship agent capability growth without a diff.**

---

## The problem Toolwright attacks

### The silent escalation trap

Agents expand their reach in ways humans never see:

* a new endpoint appears
* a scope widens
* a write action sneaks in
* auth flows shift
* retries become floods
* “cleanup” becomes “delete”

You can’t “be careful” your way out of this. The entire point of agents is that they do work when you are not watching.

### The toolchain illusion

“MCP is secure because tools are typed.”

Typed tools are not governance. MCP tools have schemas and names. Great. ([Model Context Protocol][5])
But:

* schemas can still be dangerous
* tool combinations can create exploits
* prompt injection can weaponize “allowed” tools
* implementations can have vulnerabilities ([TechRadar][4])

Typed is not trusted. Typed is merely structured.

---

## The Toolwright philosophy

### 1) Default deny is not optional

If your runtime can execute actions without an approved lockfile by default, you are building a demo, not a system.

### 2) Capability is a supply chain

Infra learned this the hard way. Dependencies became a supply chain, and lockfiles became mandatory.

Agent tools are the new dependencies.

Toolwright treats tools, scopes, and actions as supply-chain artifacts:

* they are minted
* they are reviewed
* they are approved
* they are pinned
* they are monitored for drift

### 3) Autonomous drafting is speed. Autonomous approval is suicide.

Agents can do the paperwork:

* discover candidates
* draft toolpacks
* generate pending lockfile diffs
* tag risk

Humans do one job:

* approve what is allowed

This keeps the speed without the stupidity.

### 4) Receipts beat trust

When agents touch real systems, you want:

* what was called
* why it was allowed
* what changed
* what it did

Toolwright is built to create receipts. Not vibes.

### 5) Agents draft, humans approve

In v1, agent automation may draft captures/toolpacks/pending lockfiles.

It may not approve capability expansion.

Approvals are explicit signer decisions and runtime enforces approved lockfile state by default.

---

## What Toolwright believes about “safety”

Safety is not a feature. It’s an operating model.

A “safe agent” is not an agent that promises to behave. It’s an agent that:

* cannot exceed approved capability
* is forced into least privilege
* is caught when the world changes
* leaves an audit trail

OpenClaw is a great object lesson: huge power, huge risk. ([Tom's Guide][3])
Toolwright is the missing layer that lets you keep the power without rolling dice.

---

## What Toolwright is and is not

### Toolwright is:

* a capability lockfile and approval workflow for agent tools
* an enforcement runtime that blocks unapproved actions
* drift detection for tool semantics and auth flows
* a verification and receipt system for outcomes

### Toolwright is not:

* an agent IDE
* a chat frontend
* a prompt library
* an LLM proxy
* observability that only tells you what went wrong after it goes wrong

---

## Design tenets

### Make dangerous things legible

If an agent can write, delete, transfer, or mutate state, that must surface as:

* a highlighted diff
* a risk tag
* a review gate

### Make the “right thing” the easiest thing

The default workflow should be:

* Mint produces a pending lockfile
* Runtime refuses to run without approved lockfile
* Drift is a one-command check
* Errors are blunt and actionable

### Make it composable with the agent ecosystem

Emdash and similar tools are orchestration cockpits. ([docs.emdash.sh][2])
Toolwright is air-traffic control.

We integrate downward and sideways:

* PR checks
* lockfile diffs in reviews
* CI gates
* MCP tool registries
* policy packs

---

## The Toolwright workflow

### Mint

Mint takes evidence and produces:

* toolpack
* pending lockfile
* risk annotations

### Approve

Approval is a human act:

* narrow scopes
* reject writes
* pin versions
* sign off

### Enforce

Runtime is boring on purpose:

* if not approved, it fails
* no silent escalation
* no “temporary” bypass that becomes permanent

### Drift

Drift exists because the world changes:

* APIs change
* auth changes
* UI flows change
* vendors break contracts

Even official MCP tool implementations have needed serious security patches. ([TechRadar][4])
Assume drift. Detect drift.

### Verify

Verification exists because agents lie accidentally:

* they think they did a thing
* they did not do the thing
* they did a different thing

Receipts close the loop.

---

## Why this becomes a standard layer

The agent boom is pushing toward “tools should be consumable by agents,” not just humans. That increases tool surface area and composability, which increases blast radius.

We already see governments and major orgs deploying MCP servers to expose real datasets to AI tools. ([The Economic Times][6])
This is not hobbyist-only anymore.

As adoption widens, the requirements converge:

* reproducibility
* least privilege
* audit trails
* change control

Lockfiles are how software learned to scale trust.
Toolwright is lockfiles for agents.

---

## The promise

Toolwright is not here to help you ship more code.

It’s here to let you run more agents, more often, with more power, **without turning your job into incident response.**

You get to use the future:

* parallel agents
* background work
* tool-rich automation

And you keep something teams are currently losing:

* control

Sleep is the feature.

---

## The final stance

The old way is prompt soup and prayers.

The new way is:

* capability diffs
* approved-only enforcement
* drift detection
* receipts

Toolwright is the adult supervision layer the agent boom is missing.

[1]: https://www.anthropic.com/news/model-context-protocol?utm_source=chatgpt.com "Introducing the Model Context Protocol"
[2]: https://docs.emdash.sh/?utm_source=chatgpt.com "Emdash Overview"
[3]: https://www.tomsguide.com/ai/openclaw-is-the-viral-ai-assistant-that-lives-on-your-device-what-you-need-to-know?utm_source=chatgpt.com "OpenClaw is the viral AI assistant that lives on your device - what you need to know"
[4]: https://www.techradar.com/pro/security/anthropics-official-git-mcp-server-had-some-worrying-security-flaws-this-is-what-happened-next?utm_source=chatgpt.com "Anthropic's official Git MCP server had some worrying security flaws - this is what happened next"
[5]: https://modelcontextprotocol.io/specification/2025-06-18/server/tools?utm_source=chatgpt.com "Tools"
[6]: https://m.economictimes.com/news/india/mospi-launches-mcp-server-to-link-ai-tools-with-govt-data/articleshow/128005462.cms?utm_source=chatgpt.com "MoSPI launches MCP server to link AI tools with govt data"

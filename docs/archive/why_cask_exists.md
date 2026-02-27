## Why Toolwright Exists

Agent tools are getting dangerously easy.

You can now connect GitHub, Slack, Linear, cloud consoles, internal APIs, and a filesystem to an LLM in minutes. That’s cool. It’s also the point where “AI coding” stops being a toy and starts being a production risk.

Because your agent is not a coworker.
It’s a remote script with keys.

### The industry’s current answer is bad

Most agent runtimes “solve” safety with one of these patterns:

**Level 0: YOLO**
No guardrails. Hope the model behaves.

**Level 1: Click-to-approve**
A popup for every tool call. It feels safe for 10 minutes, then becomes pure muscle memory.

**Level 2: Remember my choice**
A `permissions.json` or “Always allow” toggle that makes the popups go away.

Level 2 is the trap.

It’s “good enough” for demos. It’s also how you end up with a permanent, invisible escalation path sitting on a laptop somewhere, outside review, outside CI, outside audit.

And once the team is tired, they will always choose convenience.

### Permission prompts are not a control plane

A control plane needs to be:

* deterministic
* reviewable
* versioned
* enforceable
* portable

A runtime permission toggle is none of those. It’s an app setting.

It can’t be code reviewed. It can’t be merge gated. It can’t be shared across environments. It can’t survive a framework change. It can’t be audited by a security team without trusting the runtime that issued it.

That’s why “just remember my choice” does not scale past the first incident.

### Toolwright moves policy into an artifact

Toolwright is built around a single pivot:

**Prompts are not a control plane. Lockfiles are.**

We take “what the agent can do” and turn it into a repo artifact:

* structured
* diffable
* review-gated
* enforceable

A capability change becomes a PR diff. The dangerous lines are loud. And your CI can block on it.

This is the difference between “safety UI” and “safety infrastructure.”

### The portability problem is the real wedge

App-level permissions lock you into one runtime.

That’s fine until you:

* switch agent frameworks
* add a CI agent
* run a cron agent
* introduce a second agent environment
* move from local to staging to prod

Then your permission model fragments. Your “safety” becomes a pile of inconsistent runtime settings scattered across tools.

Toolwright is designed for the real world: teams running multiple agents across multiple environments.

**One lockfile. Everywhere.**

### The separation-of-concerns principle

Agent runtimes are incentivized to make the agent succeed. That’s their job.

Governance is the opposite job:

* slow down on risk
* force review
* block escalation
* leave receipts

Those two incentives do not belong in the same place.

Toolwright exists to be the external, deterministic layer that doesn’t care if the demo looks smooth. It cares if the capability surface is correct.

### What Toolwright delivers that runtime permissions cannot

**Synthetic capability diffs**
A computed, high-signal view of what changed: new writes, widened scope, regex introduced, guards removed.

**Merge gates**
Block dangerous capability changes before they ship.

**Approved-only enforcement**
If it’s not in the lockfile, it’s blocked. No “the model thought…”

**Drift detection**
When APIs and auth flows change, you find out before the agent breaks prod.

**Receipts**
Auditable linkage between: approved capability → allowed tool call → observed outcome.

### The adult version of autonomy

Autonomy isn’t the enemy. Unreviewed autonomy is.

Toolwright’s stance is simple:

Autonomous drafting is speed.
Autonomous approval is suicide.

Agents can generate the paperwork. Humans sign the lockfile. Runtime enforces it.

Control-plane introspection exists for operators and CI (`mcp inspect`), not for agent-led privilege escalation.

### The punchline

If you’re relying on popups and “always allow” toggles to control an agent with real access, you’re not doing governance.

You’re doing vibes-based security.

Toolwright exists to replace vibes with a standard: a lockfile, a diff, and a gate.

Sleep is the feature.

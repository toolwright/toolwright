# CLAUDE.md

## 0) Purpose
This repo is worked on by coding agents. This file defines mandatory workflow, quality gates, and documentation rules.

<IMPORTANT>
When analyzing and testing your work, make sure you take a very deep look at the output your code produces independently of any automated tests, and analyze it against the inputs and expectations to see whether anything is being missed, and to analyze the quality of our systems, and to get a good understanding of them.
</IMPORTANT>

<IMPORTANT>
Use any skills and plugins you see fit for a given task. If there's one you think the user should install, ask for their permission to install it and then install it and set it up.
When implementing UIs, use your playwright skill/plugin to control the browser and test it out, or the agent-browser one or browser-use one if the playwright one isn't available.
</IMPORTANT>

<IMPORTANT>
If you ever need anything from the user, like API keys, credentials, or anything else, ask the user for it, but make sure the way you propose it is secure and that the keys/credentials remain local. You never need to see the keys/credentials yourself, we can store them in a secure way locally.
</IMPORTANT>

<IMPORTANT>

## CAPABILITY REGISTRY (./CAPABILITIES.md)

CAPABILITIES.md is the canonical map of what exists today.

Rules:
- Existing-only. No roadmap items.
- Evidence required. Every capability entry must include file paths and entry points (symbol or grep hint).
- Use stable IDs: `CAP-<AREA>-###`.
- A capability is user-visible behavior (UI, API, CLI, job) or a system responsibility with a clear entry point.
- Before implementing anything non-trivial, confirm whether a capability already covers it.
- After behavior changes, update the relevant capability entry and anchors in the same PR.
- If a capabilities file is not yet created, create one, and analyze the project thoroughly to build out the capabilities document comprehensively. Be detailed. 
- If you read the capability registry and realize there are very major gaps and it is not up-to-date, begin a full analysis of the project to get it updated.
- Make sure the capability registry is easy to search through and get the information needed about any capability.
- The capability registry should only include existing capabilities, not planned ones
- If anything in the capability registry is incorrect, make sure it is corrected or removed

</IMPORTANT>

## 1) Documentation rules
- Keep README.md in the project roots up to date.
- If a README.md does not exist in each project root, create it.
- Update diagrams and any referenced docs when changes affect architecture, flows, data models, or APIs.
- If a decision changes public behavior, README and any public docs must reflect it in the same PR.
- When you realize a key insight that should be remembered and reused, create a new skill out of it if it makes sense to do so, especially if it's a task that'll be done relatively frequently.
- Keep all user guide md files up to date.
- Keep the capability registry (./CAPABILITIES.md) up to date, and if it does not exist, create it.
- You have a /tui-studio skill that allows you to create demos. All key workflows should have a gif demo in the readme, use the skill to generate the gifs and keep them up-to-date after every update that affects the workflow, including its inputs, outputs, or actions. Make sure the demos are 1:1 with what the actual inputs and outputs would be. The hero section of the readme should have a side-by-side comparison of the bad workflow that doesn't use our project, and then the good workflow that uses our project. If you use a "prompt identity" (user@host path), make sure it's generic and not platform-specific. Also make sure the path isn't long/distracting, you can just use the basename property for the path and "user" for the username if you use a "prompt identity" for the demos you generate. 
- Any important realization you make about the project should be documented, including risks, necessary additions, points of friction, issues with the user experience, anything that stops the project from being plug-and-play for the user, or anything else that you think is a major detail/issue for the project that we need to remain aware of but aren't addressing at the moment

## 2) Quality gates (mandatory)
Before marking a task done:
- Tests pass
- Lint/typecheck passes (if applicable)
- Manual verification is performed by inspecting real outputs against inputs and expectations
- No unexplained TODOs
- Docs updated (README, diagrams, and any touched docs)

## 3) TDD policy (default rule)
All behavior changes must follow TDD:
1. RED: add a failing test that captures the new behavior or bug
2. GREEN: minimal code to pass the test
3. REFACTOR: improve clarity and structure while keeping tests green

Agents must not write implementation code for behavior changes before a failing test exists and has been run.

### Explicit exceptions (allowed, must be recorded in progress.md)
TDD is not required for:
- docs-only changes
- formatting-only changes
- non-behavioral refactors (pure moves/renames with no semantic change)
- build/CI config changes where tests are not the right primary signal

Even under exceptions:
- add regression tests if the change risks behavior
- still run the full test suite after

## 4) Testing conventions
- Tests live under: ./tests/
- Mirror source structure under tests
- Naming: test_*.py (or repo language equivalent)
- Test command: `python -m pytest tests/ -v`
- Coverage target: not configured (add when pytest/coverage is wired)

## 5) Research rules
- Research is always allowed and encouraged when it reduces risk.
- Any external research that influences decisions must be summarized in findings.md:
  - what was checked
  - date checked
  - conclusion and how it affected the approach

## 6) Subagents
Subagents are allowed.
Rules:
- Subagents do not make final architecture decisions independently.
- Subagent outputs must be written into findings.md with clear recommendations and tradeoffs.

## 7) Git hygiene
- Initialize git if missing.
- Use feature branches.
- Commit in logical chunks with clear messages.
- Do not commit broken tests.
- Keep changes reviewable (avoid mega commits).

## 8) Project-specific values
- Language/framework: Python 3.11+ (Click CLI, Pydantic models)
- Style guide: PEP 8; format/lint via black/ruff
- Dependency manager: pip + pyproject.toml
- Lint/typecheck commands: ruff check, mypy
- Primary architecture docs/diagrams live in: ./CAPABILITIES.md

## 9) Design Principles
- **Safe by default**: All capture/enforcement requires explicit allowlists
- **Redaction on**: Remove sensitive data (cookies, tokens, PII) by default
- **No bypass language**: No features that imply circumventing protections
- **Audit everything**: Every compile, drift, enforce decision is logged
- **Compiler mindset**: We convert behavior into contracts, not scan for vulnerabilities
- **Plug and Play**: Everything should be as close to plug-and-play as possible for the user, any dependencies should be easy to manage. Installation should be easy. Init should be plug-and-play simple and easy, one command preferably. 
- **User Friendly Commands, TUI and experience**: Commands should be intuitive and user-friendly. The help screens should be very helpful. Command names/references should not be contradictory. There should be as little friction as possible with the user experience, the user should need to encounter as little friction as possible and do as little as possible to get their desired result from our projects. Feel free to use the cli-developer skill.

## 10) More guidelines
- Always prefer simplicity over pathological correctness. Follow the principles of YAGNI, KISS, DRY. Never worry about backwards compatibility.
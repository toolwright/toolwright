# Task Plan: Full Project Audit And Stabilization

## Goal
Build a complete understanding of Toolwright's goals, pillars, technology, architecture, and capabilities; review the documentation and runtime shape; validate runtime behavior; and assess whether Toolwright is worth building as an open source project by testing market demand, differentiation, positioning, and strategic direction against the current ecosystem.

## Current Phase
Phase 7

## Phases

### Phase 1: Requirements & Discovery
- [x] Understand user intent
- [x] Identify constraints and requirements
- [x] Document initial repository findings in findings.md
- **Status:** complete

### Phase 2: Repository Inventory
- [x] Inventory documentation, Python modules, configs, tests, and entrypoints
- [x] Map package boundaries and runtime flows
- [x] Record architecture notes and open questions
- **Status:** complete

### Phase 3: Code & Docs Review
- [x] Review every Python file
- [x] Review project documentation and user-facing guidance
- [x] Record maintainability, correctness, UX, and packaging risks
- **Status:** complete

### Phase 4: Validation & Diagnosis
- [x] Run tests, lint, typing, and CLI smoke checks where available
- [x] Reproduce and diagnose failures or broken workflows
- [x] Prioritize fixes that unblock intended usage
- **Status:** complete

### Phase 5: Remediation
- [x] Implement correctness and maintainability fixes
- [x] Improve user-facing setup or CLI ergonomics where needed
- [x] Keep findings and progress logs current
- **Status:** complete

### Phase 6: Re-Verification & Delivery
- [x] Re-run targeted validation
- [x] Complete domain-based CLI regrouping
- [x] Remove the next low-risk UI → CLI boundary leaks (`config`, `init`)
- [x] Remove the remaining direct UI-flow imports of CLI `mint` / `verify`
- [ ] Summarize architecture, capabilities, and project pillars
- [ ] Report remaining gaps and concrete next steps
- **Status:** in_progress

### Phase 7: Market Viability Assessment
- [ ] Re-state Toolwright's product thesis from repo docs and code
- [ ] Research adjacent and competing projects across OSS and commercial markets
- [ ] Assess demand, differentiation, and positioning with source-backed evidence
- [ ] Recommend what to cut, change, add, or emphasize
- **Status:** in_progress

## Key Questions
1. What problem does Toolwright solve, and what are its core product pillars?
2. What are the main runtime entrypoints, architectural layers, and integration points?
3. Which workflows are currently broken, brittle, or confusing for users?
4. Where is the codebase strong, and where is maintainability lagging behind the intended product goals?
5. Is there real demand for governed API-to-MCP tooling and related agent infrastructure?
6. Which projects overlap with Toolwright directly or partially, and how strong are they?
7. Is Toolwright's current framing differentiated enough to win attention as an OSS project?
8. Which parts of the current scope strengthen the thesis, and which parts dilute it?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Use file-based planning for this task | The audit will span many files, commands, and verification steps; persistent notes reduce context loss. |
| Start with inventory before remediation | A full map of the repo is required before making targeted fixes without regressions. |
| Anchor intended behavior in the top-level docs first | The product promise and v1 boundaries need to be clear before judging implementation quality. |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| None yet | 1 | N/A |

## Notes
- Re-read this plan before major decisions.
- Record findings after each exploration pass.
- Avoid destructive git operations because the branch may contain user work.
- Current cleanup direction remains incremental: keep the new domain-based CLI modules lint/type clean, preserve `toolwright/cli/main.py` as a thin entrypoint, and keep peeling boundary leaks off in small slices. The next heavier holdout is extracting the `mint` / `verify` implementations below the new runner seam, not another flow-level import cleanup.
- Keep the market assessment source-backed and separate stable product facts from strategy inferences.

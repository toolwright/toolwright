# README Rewrite Plan — Magic-First Positioning

> This is a draft for the README rewrite. Apply to README.md after all feature branches are integrated.

## Structure

```
1. Tagline: "The immune system for AI tools."
2. Magic moment: One-liner showing create <url> → governed tools
3. Hero GIF: create command in action (record AFTER features land)
4. Install + quickstart (2 lines of bash)
5. Badges
6. ---
7. "What toolwright does" — Five pillars in user journey order:
   - CONNECT → GOVERN → CORRECT → HEAL → KILL
8. "Tools that heal themselves" — the wow section (keep existing)
9. "How fast?" — demo command output (keep existing)
10. "Works with anything you have" — input table (UPDATE with URL)
11. "How the supply chain works" — architecture diagram (keep existing)
12. "Credentials never touch model context" — auth section (keep existing)
13. "Get started in 60 seconds" — quickstart (keep existing)
14. "Already have an MCP server? Wrap it." — wrap section (keep existing)
15. "Serving options" — serve section (keep existing)
16. ---
17. "Roadmap" — NEW section with deferred items:
    - Transport-agnostic governance (CLI + REST adapters)
    - Governance maturity scoring
    - GitHub Action for CI
    - Public toolpack registry
18. Documentation links (keep existing)
19. Install options (keep existing)
20. License
```

## Key Changes from Current README

1. **SWAP** fear intro ("Your MCP tools have no governance...") for magic moment
2. **ADD** URL in the "Works with anything" table
3. **REORDER** pillars: CONNECT → GOVERN → CORRECT → HEAL → KILL (was: ...KILL → HEAL)
4. **ADD** Roadmap section
5. **UPDATE** hero GIF to show new rich output
6. **UPDATE** test badge count after all fixes land

## Draft Hero Section

```markdown
# Toolwright

**The immune system for AI tools.**

Point at any API. Get governed, self-healing AI tools in seconds.

![toolwright create — governed tools in seconds](demos/outputs/hero.gif)

```bash
pip install toolwright
toolwright create https://petstore3.swagger.io/api/v3/openapi.json
```

[![PyPI version](https://img.shields.io/pypi/v/toolwright.svg)](https://pypi.org/project/toolwright/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-XXXX%20passing-brightgreen.svg)]()
```

## Notes
- Record hero GIF AFTER rich output feature lands
- Test badge count: update after all branches integrated
- The "Works with anything" table needs a new row for URL
- The quickstart section should mention auto-detect Claude Desktop if that feature ships

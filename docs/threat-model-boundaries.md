# Threat Model Boundaries (v1)

This document states what v1 is designed to defend and what it does not claim.

## Defended by design

- Unapproved capability expansion at runtime.
- Silent lockfile bypass in normal safe mode.
- Unsafe egress targets via scheme, redirect, and DNS/IP validation.
- Confirmation token replay/mismatch attacks.
- Secret leakage through default artifact/report/MCP surfaces (redaction pipeline).

## Partially addressed

- Non-deterministic UI behavior that reduces provenance confidence.
- Stateful GET edge cases discovered by heuristic detection and overrides.

## Explicitly out of scope

- Bypassing MFA, passkeys, or anti-bot systems.
- Discovering hidden APIs with unrestricted autonomous browsing.
- Formal verification/proof of correctness.
- Legal/compliance certification guarantees.

## Security posture summary

Toolwright is a capability governance layer with fail-closed runtime behavior, explicit approvals, and auditable decision traces.

# Evidence and Redaction Spec (v1)

This document defines mandatory redaction behavior for capture, runtime, reports, and portable bundle exports.

## Non-negotiable invariants

1. Redact before disk write.
2. Redact before report emission.
3. Redact before MCP output exposure.
4. Never store raw auth headers, cookies, or full sensitive bodies by default.

## Storage policy

Default storage behavior:

- request/response headers: allowlisted safe subset only
- body storage: sanitized excerpts plus digests
- excerpt max length: `4096` characters
- truncated bodies are marked and digest-linked

## Redaction targets

- Authorization tokens
- Cookie values
- API keys/secrets
- common PII fields (email, phone, SSN-like values, card-like values)
- query/body key patterns defined by policy redaction rules

## Evidence references

Verification and runtime reports should reference evidence by ID/URI, not inline raw payload dumps.

## Release gate

Synthetic secret/PII leak tests are hard gates:

- inject representative secrets in headers/body/query
- verify they never appear unredacted in artifacts, logs, or reports

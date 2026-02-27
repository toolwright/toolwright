# OTEL Capture Input

Toolwright supports OpenTelemetry trace exports as a capture input.

This is intentionally an **adapter** into the existing capture pipeline:

- OTEL spans -> `HttpExchange`
- existing redaction -> existing storage -> existing compile/enforce
- no new runtime privileges, no autonomous execution paths

## Supported input

- File import via `toolwright capture import ... --input-format otel`
- JSON exports containing `resourceSpans` / `scopeSpans` / `spans`
- NDJSON exports (one JSON object per line)

Live OTLP collector ingestion is not part of this release.

## Usage

```bash
# Import OTEL trace export into captures/
toolwright capture import traces.json --input-format otel -a api.example.com

# Continue normal workflow
toolwright compile --capture-path .toolwright/captures/<capture-id>
toolwright diff --toolpack .toolwright/toolpacks/<id>/toolpack.yaml --format github-md
```

## Attribute mapping

HTTP spans are detected from semantic attributes and mapped with compatibility for both modern and legacy names:

- Method: `http.request.method` or `http.method`
- URL: `url.full` or `http.url` (or rebuilt from host/path attributes)
- Status: `http.response.status_code` or `http.status_code`
- Headers: `http.request.header.*`, `http.response.header.*`
- Bodies (if present): `http.request.body`, `http.response.body`

Resource attributes like `service.name` are preserved in exchange notes.

## Filtering behavior

The OTEL adapter preserves the same anti-noise posture as other capture adapters:

- host allowlist enforcement (`--allowed-hosts`)
- static asset filtering (`.js`, `.css`, images, fonts, etc.)
- blocked path filtering via capture path blocklist
- redaction enabled by default

## Notes

- OTEL instrumentation often omits request/response bodies. Toolwright still compiles useful tools from method/path/status metadata.
- Importing both client and server spans can increase duplicates/noise depending on instrumentation. Keep allowlists tight and review diffs before approval.

# E2E Real Ecommerce Site Testing — Findings

**Date**: 2026-02-12
**Toolwright Version**: 0.2.0b1
**Capture Mode**: Headless Playwright with scripted URL navigation

## Summary

### Before static asset filter fix

| Site | Exchanges | Endpoints | Flow Edges | Scope Drafts | Quality |
|------|-----------|-----------|------------|--------------|---------|
| Amazon | 45 | 10 | 0 | 10 | Fair — mostly telemetry, 1 real API |
| eBay | 71 | 22 | 1 | 22 | Fair — tag-manager static JS leaks through |
| StockX | 0 | 0 | 0 | 0 | Blocked — bot protection prevents headless capture |
| Walmart | 120 | 116 | 114 | 116 | Poor — 114 static JS bundle paths not filtered |
| TCGPlayer | 25 | 5 | 1 | 5 | Good — clean API endpoints, proper deduplication |
| Target | 169 | 17 | 73 | 17 | Excellent — real REST APIs, correct risk tiers |

### After static asset filter fix

| Site | Endpoints (before) | Endpoints (after) | Improvement |
|------|-------------------|-------------------|-------------|
| Amazon | 10 | 10 | No change (no static JS) |
| eBay | 22 | 13 | -9 (tag-manager JS filtered) |
| Walmart | 116 | 3 | -113 (Next.js bundle JS filtered) |
| TCGPlayer | 5 | 5 | No change (clean API) |
| Target | 17 | 17 | No change (clean REST) |

## Quality Issues Discovered

### Issue 1: Static Assets Leaking Through as "Endpoints" (Critical)

**Affected sites**: Walmart (114 static JS files), eBay (10 tag-manager JS files)

**Root cause**: The aggregator does not filter out requests for static file types (`.js`, `.css`, `.png`, `.jpg`, `.woff2`, etc.). When a CDN/proxy path like `/dfwrs/{uuid}/.../_next/static/chunks/foo.js` passes through the allowed host filter, each unique filename becomes a separate "endpoint".

**Impact**: Walmart generated 116 tools when it should have ~2 (GraphQL + telemetry). eBay generated 10 `tag-manager` tools that are just JS file downloads.

**Fix**: Add static asset extension filtering in the aggregator. Paths ending in `.js`, `.css`, `.map`, `.png`, `.jpg`, `.gif`, `.svg`, `.woff`, `.woff2`, `.ttf`, `.ico` should be excluded from endpoint aggregation by default.

### Issue 2: Path Normalizer Doesn't Recognize Short UUIDs (Medium)

**Affected sites**: Amazon (`3d0839e4-71d8`), Walmart

**Root cause**: The UUID regex requires the full RFC 4122 format (8-4-4-4-12). Many real-world systems use shortened UUID formats (e.g., `3d0839e4-71d8` from the first two sections).

**Impact**: Short UUID path segments like `3d0839e4-71d8` are treated as literal path components instead of being normalized to `{uuid}`.

**Fix**: Add a "short hex" pattern to the normalizer for hex strings of 8+ chars with dashes (e.g., `^[0-9a-f]{6,}-[0-9a-f]{2,}$`).

### Issue 3: Overly Long Tool Names (Medium)

**Affected sites**: Amazon

**Root cause**: When multiple product IDs are concatenated in a single path segment (e.g., `/products/B09B2SRGX,B0DLLSCVZW,...`), the entire comma-separated list becomes part of the tool name.

**Impact**: Tool name `get_marketplaces_atvpdkikx0der_products_b09b2srgxhb0dllscvzwb0fmjfzvch...` is unusable.

**Fix**: Truncate tool names at a reasonable length (e.g., 64 chars). Detect comma-separated lists in path segments and normalize them to `{ids}`.

### Issue 4: Bot Protection Blocks Headless Capture (Expected)

**Affected sites**: StockX (0 exchanges)

**Root cause**: StockX uses aggressive bot detection (likely Cloudflare or Akamai) that blocks headless Chrome. No API traffic is captured because the browser never loads the application code.

**Impact**: Cannot capture StockX without authenticated session or anti-detection configuration.

**Status**: Known limitation. Document in user guide. Recommend:
1. Use `--no-headless` for interactive capture
2. Use `--load-storage-state` with pre-authenticated session
3. Import HAR files from manual browser sessions

### Issue 5: Telemetry/Analytics Endpoints Dominate Results (Low)

**Affected sites**: Amazon (7/10 telemetry POSTs), Target (events + telemetry ~5/17)

**Root cause**: Modern ecommerce sites fire dozens of analytics/telemetry requests per page load. These are legitimate first-party XHR calls that pass the host filter.

**Impact**: Telemetry endpoints like `create_events_comamazoncsmnexusclientprod` clutter the tool surface. They're correctly captured but not useful for agent tools.

**Potential fix**: Add optional `--exclude-telemetry` flag or telemetry path pattern list (e.g., paths containing `/events/`, `/telemetry/`, `/tracking/`, `/beacon/`, `/analytics/`, `/batch/`).

### Issue 6: Graph QL Single-Endpoint Merging (Low)

**Affected sites**: Walmart (1 GraphQL endpoint)

**Root cause**: GraphQL uses a single endpoint for all queries/mutations. Different operations are distinguished by the request body, not the path.

**Impact**: All GraphQL operations merge into one tool. Cannot differentiate between "get products" and "add to cart" GraphQL mutations.

**Status**: Known limitation. Document. Future: parse GraphQL operation names from request bodies.

## What Works Well

1. **Path normalization**: Correctly normalizes numeric IDs, UUIDs, and tokens in Target and eBay paths
2. **Scope inference**: Risk tiers are correctly assigned (cart=safe, event creation=medium, telemetry=medium)
3. **Flow detection**: Target generated 73 flow edges connecting related API endpoints
4. **Aggregation**: TCGPlayer correctly deduplicated 25 requests into 5 unique endpoints
5. **Domain tagging**: Commerce, auth, and user tags applied correctly
6. **Host filtering**: First-party-only scope works — no third-party CDN/analytics leaks (when hosts are properly configured)

## Recommendations

### Short-term (pre-v1.0)
1. **Static asset filter** — Filter `.js`, `.css`, `.map`, image, and font extensions from endpoint aggregation
2. **Telemetry path blocklist** — Optional exclusion of common telemetry patterns
3. **Tool name length cap** — Truncate at 64 chars, normalize comma-separated IDs

### Medium-term
4. **Short UUID recognition** — Add hex-dash pattern to path normalizer
5. **GraphQL operation extraction** — Parse operation names from request bodies
6. **Bot detection guidance** — Document workarounds in user guide

### Long-term
7. **Content-type filtering** — Only aggregate `application/json` responses as API endpoints
8. **Sampling quality score** — Report how many unique endpoints were discovered vs total requests

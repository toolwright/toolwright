# Toolwright Architecture Specification (Historical)

> This file is a historical reference. The canonical vNext product spec is `SPEC_VIEWPOINTS.md`.
>
> Current CLI truth should always be validated via command help (`python -m toolwright --help`).
> Naming note: current shipped command `toolwright plan` is the diff-style report surface; vNext docs use `diff` terminology.
> Naming note: current shipped `toolwright mcp meta` corresponds to the vNext control-plane framing.

**Version:** 1.0.0
**Status:** Historical Reference
**Last Updated:** 2026-02-08

Toolwright is an "action surface compiler" that transforms observed web/API traffic into safe, versioned, agent-ready tools with drift detection and enforcement guardrails.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Core Module Structure](#2-core-module-structure)
3. [Data Models](#3-data-models)
4. [Scope DSL Specification](#4-scope-dsl-specification)
5. [Policy DSL Specification](#5-policy-dsl-specification)
6. [CLI Command Specifications](#6-cli-command-specifications)
7. [Storage Format Specifications](#7-storage-format-specifications)
8. [Key Interfaces](#8-key-interfaces)
9. [Extension Points](#9-extension-points)
10. [Non-Negotiable Defaults](#10-non-negotiable-defaults)
11. [Implementation Priority](#11-implementation-priority)

---

## 1. System Overview

### 1.1 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                 Toolwright                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐     ┌──────────────────────────────────────────────────┐  │
│  │     CLI      │     │                  CORE ENGINE                     │  │
│  │              │     │                                                  │  │
│  │  - capture   │────▶│  ┌──────────┐  ┌───────────┐  ┌───────────────┐  │  │
│  │  - compile   │     │  │ Capture  │─▶│ Normalize │─▶│    Compile    │  │  │
│  │  - drift     │     │  └──────────┘  └───────────┘  └───────────────┘  │  │
│  │  - serve     │     │       │              │               │           │  │
│  │  - enforce   │     │       ▼              ▼               ▼           │  │
│  └──────────────┘     │  ┌──────────┐  ┌───────────┐  ┌───────────────┐  │  │
│                       │  │  Scope   │  │   Drift   │  │   Enforce     │  │  │
│                       │  │  Engine  │  │   Engine  │  │   (Gateway)   │  │  │
│                       │  └──────────┘  └───────────┘  └───────────────┘  │  │
│                       │                      │               │           │  │
│                       │                      ▼               ▼           │  │
│                       │               ┌──────────────────────────┐       │  │
│                       │               │      Audit Logger        │       │  │
│                       │               └──────────────────────────┘       │  │
│                       └──────────────────────────────────────────────────┘  │
│                                              │                              │
│                       ┌──────────────────────▼───────────────────────────┐  │
│                       │                  DATA LAYER                      │  │
│                       │                                                  │  │
│                       │  ┌───────────┐  ┌───────────┐  ┌───────────────┐ │  │
│                       │  │ Captures  │  │ Artifacts │  │  Audit Logs   │ │  │
│                       │  │  (HAR)    │  │ (JSON/    │  │   (JSONL)     │ │  │
│                       │  │           │  │  YAML)    │  │               │ │  │
│                       │  └───────────┘  └───────────┘  └───────────────┘ │  │
│                       └──────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Data Flow Diagram

```
                                    USER WORKFLOW
                                         │
          ┌──────────────────────────────┼──────────────────────────────┐
          │                              │                              │
          ▼                              ▼                              ▼
    ┌──────────┐                  ┌──────────┐                   ┌──────────┐
    │   HAR    │                  │Playwright│                   │  Proxy   │
    │  Import  │                  │ Capture  │                   │ (future) │
    └────┬─────┘                  └────┬─────┘                   └────┬─────┘
         │                             │                              │
         └─────────────────────────────┼──────────────────────────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │   RAW TRAFFIC   │
                              │   HttpExchange  │
                              └────────┬────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │    NORMALIZE    │
                              │                 │
                              │ • Path template │
                              │ • Schema infer  │
                              │ • Auth detect   │
                              │ • Redaction     │
                              └────────┬────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │   SCOPE FILTER  │
                              │                 │
                              │ • first_party   │
                              │ • auth_surface  │
                              │ • state_change  │
                              └────────┬────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
                    ▼                  ▼                  ▼
           ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
           │   CONTRACT    │  │     TOOL      │  │    POLICY     │
           │   (OpenAPI)   │  │   MANIFEST    │  │    (YAML)     │
           └───────────────┘  └───────────────┘  └───────────────┘
                    │                  │                  │
                    └──────────────────┼──────────────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │  DRIFT ENGINE   │──────▶ Drift Report
                              └─────────────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │    ENFORCER     │──────▶ Runtime Gate
                              │                 │
                              │ • Allowlist     │
                              │ • Budget        │
                              │ • Confirm       │
                              └─────────────────┘
```

### 1.3 Artifact Flow

```
Capture Session
      │
      ▼
┌───────────────────────────────────────────────────────────────────┐
│                        COMPILE PIPELINE                            │
├───────────────────────────────────────────────────────────────────┤
│                                                                    │
│   Input: CaptureSession + Scope                                   │
│                                                                    │
│   ┌─────────────────────────────────────────────────────────────┐ │
│   │                    ARTIFACT OUTPUTS                          │ │
│   ├─────────────────────────────────────────────────────────────┤ │
│   │                                                              │ │
│   │  1. CONTRACT (OpenAPI 3.1)                                   │ │
│   │     └─ contract.yaml                                         │ │
│   │                                                              │ │
│   │  2. TOOL MANIFEST (JSON)                                     │ │
│   │     └─ tools.json                                            │ │
│   │                                                              │ │
│   │  3. POLICY (YAML)                                            │ │
│   │     └─ policy.yaml                                           │ │
│   │                                                              │ │
│   │  4. BASELINE SNAPSHOT (JSON)                                 │ │
│   │     └─ baseline.json                                         │ │
│   │                                                              │ │
│   └─────────────────────────────────────────────────────────────┘ │
│                                                                    │
└───────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Module Structure

```
toolwright/
├── __init__.py
├── __main__.py                 # Entry point: python -m toolwright
│
├── cli/                        # Click CLI commands
│   ├── __init__.py
│   ├── main.py                 # CLI group and common options
│   ├── capture.py              # toolwright capture
│   ├── compile.py              # toolwright compile
│   ├── drift.py                # toolwright drift
│   ├── serve.py                # toolwright serve
│   └── enforce.py              # toolwright enforce
│
├── core/
│   ├── __init__.py
│   │
│   ├── capture/                # Traffic capture adapters
│   │   ├── __init__.py
│   │   ├── base.py             # CaptureAdapter protocol
│   │   ├── har_parser.py       # HAR file import
│   │   ├── playwright.py       # Playwright capture adapter
│   │   └── redactor.py         # Sensitive data redaction
│   │
│   ├── normalize/              # Traffic normalization
│   │   ├── __init__.py
│   │   ├── path_normalizer.py  # Path templating (/users/{id})
│   │   ├── schema_inferrer.py  # JSON schema inference
│   │   ├── auth_analyzer.py    # Auth pattern detection
│   │   └── aggregator.py       # Endpoint deduplication
│   │
│   ├── scope/                  # Scope engine
│   │   ├── __init__.py
│   │   ├── engine.py           # Scope evaluation
│   │   ├── builtins.py         # 5 built-in scopes
│   │   ├── parser.py           # YAML DSL parser
│   │   └── filters.py          # Filter implementations
│   │
│   ├── compile/                # Artifact generators
│   │   ├── __init__.py
│   │   ├── contract.py         # OpenAPI generator
│   │   ├── tools.py            # Tool manifest generator
│   │   ├── policy.py           # Policy generator
│   │   └── baseline.py         # Baseline snapshot generator
│   │
│   ├── drift/                  # Drift detection
│   │   ├── __init__.py
│   │   ├── engine.py           # Diff algorithm
│   │   ├── classifier.py       # Drift classification
│   │   └── reporter.py         # Report generation
│   │
│   ├── enforce/                # Runtime enforcement
│   │   ├── __init__.py
│   │   ├── gate.py             # Policy evaluation gate
│   │   ├── budgets.py          # Rate limiting & budgets
│   │   └── confirmation.py     # Human confirmation workflow
│   │
│   └── audit/                  # Audit logging
│       ├── __init__.py
│       └── logger.py           # JSONL audit logger
│
├── models/                     # Pydantic data models
│   ├── __init__.py
│   ├── capture.py              # HttpExchange, CaptureSession
│   ├── endpoint.py             # Endpoint, Parameter
│   ├── action.py               # Action, ToolManifest
│   ├── policy.py               # PolicyRule, Policy
│   ├── drift.py                # DriftItem, DriftReport
│   └── scope.py                # Scope, ScopeRule
│
├── storage/                    # Persistence layer
│   ├── __init__.py
│   ├── filesystem.py           # Local file storage
│   └── formats.py              # Serialization helpers
│
└── utils/                      # Utilities
    ├── __init__.py
    ├── hashing.py              # Stable ID generation
    ├── patterns.py             # Regex patterns (PII, tokens)
    └── security.py             # Security helpers
```

---

## 3. Data Models

All models use Pydantic v2 for validation and serialization.

### 3.1 Capture Models

```python
# models/capture.py

from enum import Enum
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field
import uuid


class HTTPMethod(str, Enum):
    """HTTP methods."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"
    HEAD = "HEAD"


class CaptureSource(str, Enum):
    """Source of captured traffic."""
    HAR = "har"
    PLAYWRIGHT = "playwright"
    PROXY = "proxy"
    MANUAL = "manual"


class HttpExchange(BaseModel):
    """A single HTTP request/response pair."""

    # Identity
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Request
    url: str
    method: HTTPMethod
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_body: Optional[str] = None
    request_body_json: Optional[dict[str, Any]] = None  # Parsed if JSON

    # Response
    response_status: Optional[int] = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    response_body: Optional[str] = None
    response_body_json: Optional[dict[str, Any]] = None  # Parsed if JSON

    # Metadata
    timestamp: Optional[datetime] = None
    duration_ms: Optional[float] = None
    source: CaptureSource = CaptureSource.MANUAL

    # Redaction tracking
    redacted_fields: list[str] = Field(default_factory=list)

    # Additional context (from HAR, Playwright, etc.)
    notes: dict[str, Any] = Field(default_factory=dict)


class CaptureSession(BaseModel):
    """A collection of captured HTTP exchanges."""

    # Identity
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Metadata
    name: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    source: CaptureSource = CaptureSource.HAR
    source_file: Optional[str] = None  # Original HAR path

    # Allowed hosts (required for capture)
    allowed_hosts: list[str] = Field(default_factory=list)

    # Exchanges
    exchanges: list[HttpExchange] = Field(default_factory=list)

    # Statistics
    total_requests: int = 0
    filtered_requests: int = 0
    redacted_count: int = 0

    # Warnings/errors during import
    warnings: list[str] = Field(default_factory=list)
```

### 3.2 Endpoint Models

```python
# models/endpoint.py

from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


class AuthType(str, Enum):
    """Detected authentication type."""
    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"
    COOKIE = "cookie"
    BASIC = "basic"
    OAUTH2 = "oauth2"
    UNKNOWN = "unknown"


class ParameterLocation(str, Enum):
    """Where a parameter appears."""
    PATH = "path"
    QUERY = "query"
    HEADER = "header"
    BODY = "body"
    COOKIE = "cookie"


class Parameter(BaseModel):
    """An API parameter."""

    name: str
    location: ParameterLocation
    param_type: str = "string"  # JSON Schema type
    required: bool = False
    default: Optional[Any] = None
    example: Optional[Any] = None
    description: Optional[str] = None

    # Inferred schema (for complex types)
    schema: Optional[dict[str, Any]] = None

    # For path parameters, the regex pattern
    pattern: Optional[str] = None


class Endpoint(BaseModel):
    """A normalized API endpoint."""

    # Identity - stable across captures
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    stable_id: Optional[str] = None  # Hash of method + normalized_path + host

    # Core properties
    method: str  # HTTPMethod value
    path: str  # Normalized path (e.g., /api/users/{id})
    host: str

    # Full URL for reference
    url: Optional[str] = None

    # Parameters
    parameters: list[Parameter] = Field(default_factory=list)

    # Request details
    request_content_type: Optional[str] = None
    request_body_schema: Optional[dict[str, Any]] = None
    request_examples: list[dict[str, Any]] = Field(default_factory=list)

    # Response details
    response_status_codes: list[int] = Field(default_factory=list)
    response_content_type: Optional[str] = None
    response_body_schema: Optional[dict[str, Any]] = None
    response_examples: list[dict[str, Any]] = Field(default_factory=list)

    # Auth detection
    auth_type: AuthType = AuthType.UNKNOWN
    auth_header: Optional[str] = None

    # Classification
    is_first_party: bool = True
    is_state_changing: bool = False
    is_auth_related: bool = False
    has_pii: bool = False

    # Risk assessment
    risk_tier: str = "low"  # low, medium, high, critical

    # Observation metadata
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    observation_count: int = 1

    # Confidence in inferences
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

    # Raw exchange references
    exchange_ids: list[str] = Field(default_factory=list)
```

### 3.3 Action & Tool Manifest Models

```python
# models/action.py

from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field


class RiskTier(str, Enum):
    """Risk classification for actions."""
    SAFE = "safe"           # Read-only, no sensitive data
    LOW = "low"             # Read-only with potentially sensitive data
    MEDIUM = "medium"       # State-changing, non-destructive
    HIGH = "high"           # State-changing, destructive potential
    CRITICAL = "critical"   # Auth, payment, admin operations


class ConfirmationMode(str, Enum):
    """When confirmation is required."""
    NEVER = "never"
    ALWAYS = "always"
    ON_RISK = "on_risk"     # Based on risk tier
    ON_BUDGET = "on_budget" # When budget is exceeded


class Action(BaseModel):
    """An agent-callable action derived from an endpoint."""

    # Identity
    id: str
    name: str  # Human-friendly name (e.g., "get_user", "create_order")

    # Description for LLMs
    description: str

    # Mapping to endpoint
    endpoint_id: str
    method: str
    path: str
    host: str

    # Input schema (JSON Schema)
    input_schema: dict[str, Any]

    # Output schema (JSON Schema)
    output_schema: Optional[dict[str, Any]] = None

    # Risk and safety
    risk_tier: RiskTier = RiskTier.LOW
    confirmation_required: ConfirmationMode = ConfirmationMode.ON_RISK

    # Rate limiting
    rate_limit_per_minute: Optional[int] = None

    # Tags for filtering
    tags: list[str] = Field(default_factory=list)

    # Scope membership
    scopes: list[str] = Field(default_factory=list)


class ToolManifest(BaseModel):
    """Complete tool manifest for agent consumption."""

    # Metadata
    version: str = "1.0.0"
    name: str
    description: Optional[str] = None
    generated_at: str

    # Source capture info
    capture_id: str
    scope: str

    # Allowed hosts
    allowed_hosts: list[str]

    # Actions
    actions: list[Action]

    # Global defaults
    default_rate_limit: Optional[int] = None
    default_confirmation: ConfirmationMode = ConfirmationMode.ON_RISK
```

### 3.4 Policy Models

```python
# models/policy.py

from enum import Enum
from typing import Optional, Any, Union
from pydantic import BaseModel, Field


class RuleType(str, Enum):
    """Types of policy rules."""
    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"
    REDACT = "redact"
    BUDGET = "budget"
    AUDIT = "audit"


class MatchCondition(BaseModel):
    """Condition for matching requests."""

    # Host matching
    hosts: Optional[list[str]] = None
    host_pattern: Optional[str] = None  # Regex

    # Path matching
    paths: Optional[list[str]] = None
    path_pattern: Optional[str] = None  # Regex

    # Method matching
    methods: Optional[list[str]] = None

    # Header matching
    headers: Optional[dict[str, str]] = None

    # Risk tier matching
    risk_tiers: Optional[list[str]] = None

    # Scope matching
    scopes: Optional[list[str]] = None


class PolicyRule(BaseModel):
    """A single policy rule."""

    id: str
    name: str
    description: Optional[str] = None

    # Rule type
    type: RuleType

    # When this rule applies
    match: MatchCondition

    # Priority (higher = evaluated first)
    priority: int = 0

    # Rule-specific settings
    settings: dict[str, Any] = Field(default_factory=dict)
    # For BUDGET: {"per_minute": 10, "per_hour": 100}
    # For REDACT: {"fields": ["authorization", "cookie"]}
    # For CONFIRM: {"message": "This will delete data. Proceed?"}


class Policy(BaseModel):
    """Complete policy configuration."""

    # Metadata
    version: str = "1.0.0"
    name: str
    description: Optional[str] = None

    # Default behavior (deny by default for safety)
    default_action: RuleType = RuleType.DENY

    # Rules (evaluated in priority order)
    rules: list[PolicyRule] = Field(default_factory=list)

    # Global settings
    global_rate_limit: Optional[int] = None
    audit_all: bool = True

    # Redaction defaults
    redact_headers: list[str] = Field(
        default_factory=lambda: [
            "authorization",
            "cookie",
            "set-cookie",
            "x-api-key",
        ]
    )
    redact_patterns: list[str] = Field(
        default_factory=lambda: [
            r"bearer\s+[a-zA-Z0-9\-_.]+",
            r"api[_-]?key[=:]\s*[a-zA-Z0-9]+",
        ]
    )
```

### 3.5 Drift Models

```python
# models/drift.py

from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime


class DriftType(str, Enum):
    """Classification of drift."""
    BREAKING = "breaking"       # Response schema change, removed endpoint
    AUTH = "auth"               # Auth mechanism changed
    RISK = "risk"               # New state-changing endpoint
    ADDITIVE = "additive"       # New read-only endpoint
    SCHEMA = "schema"           # Schema change (non-breaking)
    PARAMETER = "parameter"     # Parameter added/removed/changed
    UNKNOWN = "unknown"         # Unclassified (default to block)


class DriftSeverity(str, Enum):
    """Severity of drift."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class DriftItem(BaseModel):
    """A single detected drift."""

    id: str
    type: DriftType
    severity: DriftSeverity

    # What changed
    endpoint_id: Optional[str] = None
    path: Optional[str] = None
    method: Optional[str] = None

    # Description
    title: str
    description: str

    # Before/after for comparison
    before: Optional[Any] = None
    after: Optional[Any] = None

    # Recommendation
    recommendation: Optional[str] = None


class DriftReport(BaseModel):
    """Complete drift report."""

    # Metadata
    id: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    # Comparison info
    from_capture_id: str
    to_capture_id: str
    from_timestamp: Optional[datetime] = None
    to_timestamp: Optional[datetime] = None

    # Summary counts
    total_drifts: int = 0
    breaking_count: int = 0
    auth_count: int = 0
    risk_count: int = 0
    additive_count: int = 0

    # Drifts
    drifts: list[DriftItem] = Field(default_factory=list)

    # Overall assessment
    has_breaking_changes: bool = False
    requires_review: bool = False

    # Exit code for CI
    exit_code: int = 0  # 0 = ok, 1 = warnings, 2 = breaking
```

### 3.6 Scope Models

```python
# models/scope.py

from enum import Enum
from typing import Optional, Any, Union
from pydantic import BaseModel, Field


class ScopeType(str, Enum):
    """Types of built-in scopes."""
    FIRST_PARTY_ONLY = "first_party_only"
    AUTH_SURFACE = "auth_surface"
    STATE_CHANGING = "state_changing"
    PII_SURFACE = "pii_surface"
    AGENT_SAFE_READONLY = "agent_safe_readonly"
    CUSTOM = "custom"


class FilterOperator(str, Enum):
    """Operators for filter conditions."""
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    MATCHES = "matches"  # Regex
    IN = "in"
    NOT_IN = "not_in"


class ScopeFilter(BaseModel):
    """A single filter condition."""

    field: str  # e.g., "host", "method", "path", "auth_type"
    operator: FilterOperator
    value: Union[str, list[str]]


class ScopeRule(BaseModel):
    """A rule within a scope (AND of filters)."""

    name: Optional[str] = None
    description: Optional[str] = None

    # Filters (all must match = AND)
    filters: list[ScopeFilter] = Field(default_factory=list)

    # Action when matched
    include: bool = True  # True = include, False = exclude


class Scope(BaseModel):
    """A scope definition for filtering endpoints."""

    # Identity
    name: str
    type: ScopeType = ScopeType.CUSTOM
    description: Optional[str] = None

    # For FIRST_PARTY_ONLY scope
    first_party_hosts: list[str] = Field(default_factory=list)

    # Rules (evaluated in order, first match wins)
    rules: list[ScopeRule] = Field(default_factory=list)

    # Risk settings for this scope
    default_risk_tier: str = "medium"
    confirmation_required: bool = False

    # Rate limits for this scope
    rate_limit_per_minute: Optional[int] = None
```

---

## 4. Scope DSL Specification

### 4.1 YAML Format

```yaml
# scope.yaml
name: my_custom_scope
description: "Custom scope for checkout flow"

# First-party hosts (used by first_party_only)
first_party_hosts:
- api.example.com
- checkout.example.com

# Rules (evaluated in order)
rules:
# Include all checkout endpoints
- name: checkout_endpoints
  include: true
  filters:
  - field: path
    operator: contains
    value: "/checkout"
  - field: method
    operator: in
    value: ["GET", "POST"]

# Exclude analytics
- name: no_analytics
  include: false
  filters:
  - field: path
    operator: matches
    value: ".*/analytics/.*"

# Include auth-related by pattern
- name: auth_endpoints
  include: true
  filters:
  - field: path
    operator: matches
    value: ".*/(login|logout|token|refresh|auth).*"

# Scope-wide settings
default_risk_tier: medium
confirmation_required: true
rate_limit_per_minute: 30
```

### 4.2 Built-in Scopes

#### 4.2.1 `first_party_only`

Includes only requests to configured first-party domains. All third-party (analytics, CDN, ads) are excluded.

```yaml
# Built-in: first_party_only
name: first_party_only
description: "Only first-party API requests"
type: first_party_only

rules:
- name: first_party_check
  include: true
  filters:
  - field: is_first_party
    operator: equals
    value: true

default_risk_tier: low
confirmation_required: false
```

**Matching Logic:**
- Compares request host against `first_party_hosts` list
- Supports wildcard matching: `*.example.com`
- Subdomains must be explicitly listed or use wildcard

#### 4.2.2 `auth_surface`

Endpoints involved in authentication flows.

```yaml
# Built-in: auth_surface
name: auth_surface
description: "Authentication and authorization endpoints"
type: auth_surface

rules:
# Path-based detection
- name: auth_paths
  include: true
  filters:
  - field: path
    operator: matches
    value: ".*/(login|logout|signin|signout|auth|oauth|token|refresh|session|register|signup|password|reset|verify|confirm|activate|2fa|mfa|otp).*"

# Has auth headers
- name: has_auth
  include: true
  filters:
  - field: is_auth_related
    operator: equals
    value: true

# Sets cookies
- name: sets_cookies
  include: true
  filters:
  - field: response_headers
    operator: contains
    value: "set-cookie"

default_risk_tier: critical
confirmation_required: true
```

**Matching Logic:**
- Path contains auth-related keywords
- Request uses auth headers (Authorization, X-API-Key)
- Response sets session cookies
- OAuth flow patterns detected

#### 4.2.3 `state_changing`

Non-GET methods that modify server state.

```yaml
# Built-in: state_changing
name: state_changing
description: "State-changing operations"
type: state_changing

rules:
- name: non_get_methods
  include: true
  filters:
  - field: method
    operator: in
    value: ["POST", "PUT", "PATCH", "DELETE"]

# Exclude safe POSTs (search, query)
- name: exclude_safe_posts
  include: false
  filters:
  - field: method
    operator: equals
    value: "POST"
  - field: path
    operator: matches
    value: ".*/search|.*/query|.*/graphql.*"

default_risk_tier: high
confirmation_required: true
rate_limit_per_minute: 10
```

**Matching Logic:**
- HTTP method is POST, PUT, PATCH, or DELETE
- Excludes GraphQL queries (POST but read-only)
- Excludes search endpoints

#### 4.2.4 `pii_surface`

Endpoints handling personally identifiable information.

```yaml
# Built-in: pii_surface
name: pii_surface
description: "Endpoints with PII data"
type: pii_surface

rules:
# User/profile endpoints
- name: user_endpoints
  include: true
  filters:
  - field: path
    operator: matches
    value: ".*/(user|profile|account|customer|member).*"

# Contains PII fields in request/response
- name: has_pii
  include: true
  filters:
  - field: has_pii
    operator: equals
    value: true

default_risk_tier: high
confirmation_required: true
```

**PII Detection Patterns:**
- Field names: `email`, `phone`, `ssn`, `address`, `dob`, `name`, `credit_card`
- Regex patterns for SSN, phone, email in values
- Path segments: `/users/`, `/profile/`, `/account/`

#### 4.2.5 `agent_safe_readonly`

Strict read-only subset safe for autonomous agent use.

```yaml
# Built-in: agent_safe_readonly
name: agent_safe_readonly
description: "Safe read-only endpoints for agents"
type: agent_safe_readonly

rules:
# Only GET requests
- name: get_only
  include: true
  filters:
  - field: method
    operator: equals
    value: "GET"

# First-party only
- name: first_party
  include: true
  filters:
  - field: is_first_party
    operator: equals
    value: true

# Exclude auth endpoints
- name: no_auth
  include: false
  filters:
  - field: is_auth_related
    operator: equals
    value: true

# Exclude PII
- name: no_pii
  include: false
  filters:
  - field: has_pii
    operator: equals
    value: true

# Exclude admin
- name: no_admin
  include: false
  filters:
  - field: path
    operator: matches
    value: ".*/admin.*"

default_risk_tier: safe
confirmation_required: false
rate_limit_per_minute: 60
```

**Matching Logic:**
- Only GET methods
- First-party hosts only
- Excludes auth endpoints
- Excludes PII endpoints
- Excludes admin paths
- Tight rate limits

### 4.3 Recommended Workflow Scopes (Examples)

Built-in scopes are intentionally **risk-oriented**. In real deployments you will usually add **workflow/domain scopes**
to produce smaller, more useful tool surfaces (e.g., search only, catalog only, checkout only).

#### 4.3.1 `search_readonly` (example)

A safe scope for search and query endpoints, including explicitly allowed "read-only POST" patterns such as GraphQL queries
or structured search endpoints.

```yaml
name: search_readonly
description: "Search/query endpoints safe for agents"
first_party_hosts:
- api.example.com

rules:
# Include GET search endpoints
- name: search_get
  include: true
  filters:
  - field: path
    operator: matches
    value: ".*/(search|query).*"
  - field: method
    operator: equals
    value: "GET"

# Include read-only POST (policy-gated) for GraphQL/search
- name: search_post_readonly
  include: true
  filters:
  - field: path
    operator: matches
    value: ".*/(graphql|search|query).*"
  - field: method
    operator: equals
    value: "POST"
  - field: content_type
    operator: matches
    value: "application/json.*"

# Exclude auth and PII
- name: no_auth
  include: false
  filters:
  - field: is_auth_related
    operator: equals
    value: true
- name: no_pii
  include: false
  filters:
  - field: has_pii
    operator: equals
    value: true

default_risk_tier: safe
confirmation_required: false
rate_limit_per_minute: 60
```

#### 4.3.2 `catalog_readonly` (example)

A safe scope for product/catalog browsing endpoints.

```yaml
name: catalog_readonly
description: "Product/catalog endpoints safe for agents"
first_party_hosts:
- api.example.com

rules:
- name: catalog_get
  include: true
  filters:
  - field: path
    operator: matches
    value: ".*/(products|product|catalog|items).*"
  - field: method
    operator: equals
    value: "GET"

# Exclude auth and PII
- name: no_auth
  include: false
  filters:
  - field: is_auth_related
    operator: equals
    value: true
- name: no_pii
  include: false
  filters:
  - field: has_pii
    operator: equals
    value: true

default_risk_tier: safe
confirmation_required: false
rate_limit_per_minute: 60
```

### 4.4 Scope Drafts and Expansion Bundles

To ensure human oversight, Toolwright treats initial scope analysis as a **draft**. This draft is stored in a separate **Draft Expansion Bundle** and is not part of the primary lockfile until a human approves it.

#### 4.4.1 `ScopeDraft` Model

A `ScopeDraft` contains the proposed scope classifications for an endpoint, along with the evidence and reasoning trace that led to the suggestion.

```python
# models/scope.py (extended)

class ScopePointer(BaseModel):
    """Reference to a scope with confidence."""
    scope_name: str
    confidence: float = Field(ge=0.0, le=1.0)

class RiskSignal(BaseModel):
    """Evidence used for scope inference."""
    source: str  # e.g., "http_method", "path_keyword", "response_field"
    pattern: str # e.g., "POST", "admin", "credit_card"
    description: str

class ScopeDraft(BaseModel):
    """A proposed scope classification for an endpoint."""
    endpoint_id: str
    suggested_scopes: list[ScopePointer]
    risk_signals: list[RiskSignal]
    reasoning_trace: list[str] # Human-readable trace of inference steps
```

#### 4.4.2 Draft Expansion Bundle

This is a temporary artifact generated during compilation that contains all scope drafts. It is physically separate from the main toolpack artifacts and is intended for review.

**Structure:**
```
.toolwright/drafts/draft_<timestamp>_<random8>/
├── manifest.json
└── scope_drafts.json
```

- `manifest.json`: The full, un-scoped tool manifest.
- `scope_drafts.json`: A list of `ScopeDraft` objects, one for each endpoint.

This bundle allows a human or an automated reviewer to inspect the proposed classifications and their justifications before merging them into the official scope definitions and lockfile.

### 4.5 Verification Contracts

To support UI-level verification, Toolwright will introduce a `VerificationContract`. This contract uses human-friendly selectors, inspired by Testing Library, to define assertions about UI state.

```yaml
# verification.yaml
version: "1.0"
contracts:
  - id: search_results_visible
    description: "Search results container should be visible after search"
    selectors:
      - type: ByRole
        value: "region"
        attributes: { name: "Search Results" }
    assertions:
      - type: isVisible

  - id: user_name_matches_api
    description: "Logged-in user name in UI matches API response"
    selectors:
      - type: ByLabelText
        value: "Welcome, "
    assertions:
      - type: hasText
        # Reference to a value from the capture's response data
        value: "{{ captures.user_login.response.body.user.name }}"
```

**Selector Types:**
- `ByRole`: Selects elements by their ARIA role.
- `ByLabelText`: Selects form elements by their `aria-label` or `<label>`.
- `ByText`: Selects elements containing specific text content.
- `ByTestId`: Selects elements with a `data-testid` attribute.

This approach makes verification contracts more robust and less coupled to brittle DOM structures like CSS selectors or XPaths.

---

## 5. Policy DSL Specification
### 5.1 YAML Format

```yaml
# policy.yaml
version: "1.0.0"
name: production_policy
description: "Production enforcement policy"

# Default action when no rules match
default_action: deny

# Global settings
global_rate_limit: 100  # requests per minute
audit_all: true

# Headers to always redact
redact_headers:
  - authorization
  - cookie
  - set-cookie
  - x-api-key
  - x-auth-token

# Patterns to redact from bodies
redact_patterns:
  - "bearer\\s+[a-zA-Z0-9\\-_.]+"
  - "password[\"']?\\s*[=:]\\s*[\"']?[^\"'\\s]+"

# Rules (evaluated by priority, highest first)
rules:
  # Allow first-party GET requests
  - id: allow_first_party_get
    name: "Allow first-party reads"
    type: allow
    priority: 100
    match:
      hosts:
        - api.example.com
        - "*.example.com"
      methods: [GET, HEAD, OPTIONS]

  # Require confirmation for state changes
  - id: confirm_state_changes
    name: "Confirm mutations"
    type: confirm
    priority: 90
    match:
      methods: [POST, PUT, PATCH, DELETE]
    settings:
      message: "This action will modify data. Proceed?"

  # Budget for expensive operations
  - id: budget_writes
    name: "Budget write operations"
    type: budget
    priority: 80
    match:
      methods: [POST, PUT, PATCH]
    settings:
      per_minute: 10
      per_hour: 100
      per_day: 1000

  # Deny admin endpoints
  - id: deny_admin
    name: "Block admin access"
    type: deny
    priority: 200
    match:
      path_pattern: ".*/admin.*"

  # Audit all auth operations
  - id: audit_auth
    name: "Audit auth"
    type: audit
    priority: 50
    match:
      path_pattern: ".*/(login|logout|auth|token).*"
    settings:
      level: detailed
      include_body: false
```

### 5.2 Rule Types

| Type | Description | Settings |
|------|-------------|----------|
| `allow` | Permit the request | None |
| `deny` | Block the request | `message`: reason |
| `confirm` | Require human confirmation | `message`: prompt |
| `redact` | Redact specific fields | `fields`: list, `patterns`: list |
| `budget` | Apply rate limiting | `per_minute`, `per_hour`, `per_day` |
| `audit` | Log with extra detail | `level`, `include_body` |

### 5.3 Match Conditions

| Field | Description | Example |
|-------|-------------|---------|
| `hosts` | Exact host match (supports wildcards) | `["api.example.com", "*.cdn.com"]` |
| `host_pattern` | Regex for host | `".*\\.example\\.com"` |
| `paths` | Exact path match | `["/api/users", "/api/orders"]` |
| `path_pattern` | Regex for path | `".*/v[0-9]+/.*"` |
| `methods` | HTTP methods | `["GET", "POST"]` |
| `headers` | Required headers | `{"x-api-version": "2"}` |
| `risk_tiers` | Risk classification | `["high", "critical"]` |
| `scopes` | Scope membership | `["auth_surface"]` |

### 5.4 Evaluation Order

1. Rules sorted by priority (highest first)
2. First matching rule determines action
3. If no rule matches, `default_action` applies
4. Multiple rule types can apply (e.g., allow + audit + budget)

---

## 6. CLI Command Specifications

### 6.1 `toolwright capture`

Import traffic from HAR files or run Playwright capture.

```bash
# Import from HAR file
toolwright capture import path/to/traffic.har \
  --allowed-hosts api.example.com \
  --allowed-hosts "*.example.com" \
  --name "checkout-flow-capture" \
  --output ./captures/

# Capture with Playwright
toolwright capture record https://example.com \
  --allowed-hosts api.example.com \
  --headless \
  --duration 30

# Scripted Playwright capture
toolwright capture record https://example.com \
  --allowed-hosts api.example.com \
  --script ./scripts/capture_flow.py

# Deterministic playbook capture
toolwright capture record https://example.com \
  --allowed-hosts api.example.com \
  --playbook ./flows/search.yaml
```

**Options:**

| Option | Required | Description |
|--------|----------|-------------|
| `--allowed-hosts` | Yes | Hosts to include (repeatable) |
| `--name` | No | Name for the capture session |
| `--output` | No | Output directory (default: `./.toolwright/captures/`) |
| `--redact/--no-redact` | No | Enable redaction (default: on) |
| `--headless/--no-headless` | No | Run browser headless in `record` mode |
| `--script` | No | Python file exporting `async def run(page, context)` |
| `--playbook` | No | YAML playbook for deterministic capture flows *(planned — not yet implemented)* |
| `--load-storage-state` | No | Load Playwright storage state before capture |
| `--save-storage-state` | No | Save Playwright storage state after capture |
| `--duration` | No | Capture window in seconds for non-interactive runs |

**Output:**
- Creates `captures/<capture_id>/` directory
- `session.json`: CaptureSession metadata
- `exchanges.json`: Normalized HttpExchange list
- `raw.har`: Original HAR file (if imported)

### 6.2 `toolwright mint`

Capture traffic, compile artifacts, and create a first-class toolpack.

```bash
toolwright mint https://app.example.com \
  --allowed-hosts api.example.com \
  --scope agent_safe_readonly \
  --headless \
  --duration 30

toolwright mint https://app.example.com \
  --allowed-hosts api.example.com \
  --playbook ./flows/search.yaml \
  --verify-ui
```

**Options:**

| Option | Required | Description |
|--------|----------|-------------|
| `start_url` | Yes | Initial URL to open in Playwright |
| `--allowed-hosts/-a` | Yes | Hosts to include (repeatable) |
| `--scope/-s` | No | Compile scope (default: `agent_safe_readonly`) |
| `--headless/--no-headless` | No | Browser mode (default: headless) |
| `--script` | No | Scripted capture file (`async run(page, context)`) |
| `--playbook` | No | YAML playbook for deterministic capture flows *(planned — not yet implemented)* |
| `--duration` | No | Capture window in seconds (default: 30) |
| `--verify-ui` | No | Run verification after capture *(planned — not yet implemented)* |
| `--evidence` | No | Evidence detail level (`full`/`summary`) *(planned — not yet implemented)* |
| `--evidence-redact` | No | Evidence redaction level (`strict`/`off`) *(planned — not yet implemented)* |
| `--load-storage-state` | No | Load Playwright storage state before capture |
| `--save-storage-state` | No | Save Playwright storage state after capture |
| `--output` | No | Root output dir (default: `./.toolwright`) |
| `--print-mcp-config` | No | Print Claude Desktop MCP config snippet |
| `--runtime` | No | Runtime profile to emit (`local`/`container`) |
| `--build` | No | Build container image after emitting runtime files |
| `--tag` | No | Container image tag for `--runtime=container` |
| `--runtime-version-pin` | No | Explicit requirement string for `requirements.lock` |

**Output:**
- Creates `.toolwright/toolpacks/<toolpack_id>/toolpack.yaml`
- Copies compiled artifacts under `.toolwright/toolpacks/<toolpack_id>/artifact/`
- Creates pending lockfile at `.toolwright/toolpacks/<toolpack_id>/lockfile/toolwright.lock.pending.yaml`
- Writes verification evidence summary at `.toolwright/toolpacks/<toolpack_id>/evidence_summary.json` when `--verify-ui` is used
- Emits container runtime files (`Dockerfile`, `entrypoint.sh`, `toolwright.run`, `requirements.lock`) when `--runtime=container`
- After approvals succeed, materializes baseline snapshots under `.toolwright/toolpacks/<toolpack_id>/.toolwright/approvals/`

### 6.3 `toolwright verify` *(planned — not yet implemented)*

Capture UI evidence with a playbook and rank candidate API matches.

```bash
toolwright verify https://app.example.com \
  --allowed-hosts api.example.com \
  --playbook ./flows/search.yaml
```

**Options:**

| Option | Required | Description |
|--------|----------|-------------|
| `start_url` | Yes | Initial URL to open in Playwright |
| `--allowed-hosts/-a` | Yes | Hosts to include (repeatable) |
| `--playbook` | Yes | YAML playbook for deterministic verification capture |
| `--headless/--no-headless` | No | Browser mode (default: headless) |
| `--output` | No | Report output dir (default: `./.toolwright/reports`) |
| `--evidence` | No | Evidence detail level (`full`/`summary`) |
| `--evidence-redact` | No | Evidence redaction level (`strict`/`off`) |
| `--load-storage-state` | No | Load Playwright storage state before capture |
| `--save-storage-state` | No | Save Playwright storage state after capture |

### 6.3 `toolwright compile`

Generate artifacts from a capture session.

```bash
toolwright compile \
  --capture abc123 \
  --scope first_party_only \
  --output ./artifacts/
```

**Options:**

| Option | Required | Description |
|--------|----------|-------------|
| `--capture` | Yes | Capture session ID |
| `--scope` | No | Scope to apply (default: `first_party_only`) |
| `--scope-file` | No | Path to custom scope YAML |
| `--output` | No | Output directory (default: `./.toolwright/artifacts/`) |
| `--format` | No | Output format: `yaml`, `json` (default: both) |

**Output:**
- `contract.yaml` / `contract.json`: OpenAPI 3.1 specification
- `tools.json`: Tool manifest for agents
- `policy.yaml`: Default policy
- `baseline.json`: Snapshot for drift detection

### 6.4 `toolwright drift`

Compare captures or detect drift from baseline.

```bash
# Compare two captures
toolwright drift \
  --from capture-abc123 \
  --to capture-def456 \
  --output ./reports/

# Compare against baseline
toolwright drift \
  --baseline ./artifacts/baseline.json \
  --capture capture-xyz789
```

**Options:**

| Option | Required | Description |
|--------|----------|-------------|
| `--from` | Yes* | Source capture ID |
| `--to` | Yes* | Target capture ID |
| `--baseline` | Yes* | Baseline file path |
| `--capture` | Yes* | Capture to compare against baseline |
| `--output` | No | Output directory |
| `--format` | No | Report format: `json`, `markdown`, `both` |

*Either `--from/--to` OR `--baseline/--capture` required.

**Output:**
- `drift.json`: Structured drift report
- `drift.md`: Human-readable summary

**Exit Codes:**
- `0`: No drift or additive only
- `1`: Warning-level drift (review recommended)
- `2`: Breaking or critical drift (block in CI)

### 6.5 `toolwright serve`

Local dashboard for browsing artifacts.

```bash
toolwright serve \
  --port 8080 \
  --artifacts ./artifacts/
```

**Options:**

| Option | Required | Description |
|--------|----------|-------------|
| `--port` | No | Port to serve on (default: 8080) |
| `--artifacts` | No | Artifacts directory (default: `./.toolwright/artifacts/`) |
| `--host` | No | Host to bind (default: localhost) |

### 6.6 `toolwright enforce`

Run as a gateway for tool calls.

```bash
toolwright enforce \
  --tools ./artifacts/tools.json \
  --policy ./artifacts/policy.yaml \
  --port 8081
```

**Options:**

| Option | Required | Description |
|--------|----------|-------------|
| `--tools` | Yes | Tool manifest path |
| `--policy` | Yes | Policy file path |
| `--port` | No | Port for gateway (default: 8081) |
| `--audit-log` | No | Path for audit log (default: `./.toolwright/audit.jsonl`) |
| `--dry-run` | No | Evaluate but don't execute |

### 6.7 `toolwright mcp serve`

Expose compiled tools over MCP stdio transport.

```bash
# Explicit artifacts
toolwright mcp serve --tools ./artifacts/tools.json --policy ./artifacts/policy.yaml

# Toolpack-resolved artifacts
toolwright mcp serve --toolpack ./.toolwright/toolpacks/<toolpack_id>/toolpack.yaml
```

**Options (selected):**

| Option | Required | Description |
|--------|----------|-------------|
| `--tools` | Conditionally | Path to tools manifest (required unless `--toolpack`) |
| `--toolpack` | Conditionally | Path to toolpack.yaml (required unless `--tools`) |
| `--toolsets` | No | Toolsets artifact (explicit path override) |
| `--toolset` | No | Named toolset to expose (defaults to `readonly` when toolsets exist) |
| `--policy` | No | Policy artifact (explicit path override) |
| `--lockfile` | No | Approval lockfile (explicit path override) |

When `--toolpack` is provided, paths in `toolpack.yaml` are resolved first, and explicit flags override those values.

### 6.8 `toolwright config`

Emit an MCP client config snippet for a toolpack.

```bash
toolwright config --toolpack ./.toolwright/toolpacks/<toolpack_id>/toolpack.yaml
```

**Options (selected):**

| Option | Required | Description |
|--------|----------|-------------|
| `--toolpack` | Yes | Path to toolpack.yaml |
| `--format` | No | Output format (`json`/`yaml`) |

### 6.9 `toolwright doctor`

Validate toolpack readiness and runtime dependencies.

```bash
toolwright doctor --toolpack ./.toolwright/toolpacks/<toolpack_id>/toolpack.yaml --runtime local
```

**Options (selected):**

| Option | Required | Description |
|--------|----------|-------------|
| `--toolpack` | Yes | Path to toolpack.yaml |
| `--runtime` | No | Runtime mode (`auto`/`local`/`container`) |

### 6.10 `toolwright run`

Run a toolpack locally or in a container. Stdout is reserved for MCP protocol output.

```bash
toolwright run --toolpack ./.toolwright/toolpacks/<toolpack_id>/toolpack.yaml
toolwright run --toolpack ./.toolwright/toolpacks/<toolpack_id>/toolpack.yaml --runtime container
```

**Options (selected):**

| Option | Required | Description |
|--------|----------|-------------|
| `--toolpack` | Yes | Path to toolpack.yaml |
| `--runtime` | No | Runtime mode (`auto`/`local`/`container`) |
| `--print-config-and-exit` | No | Emit MCP client config snippet to stdout and exit |
| `--toolset` | No | Named toolset to expose |
| `--lockfile` | No | Lockfile path override |
| `--base-url` | No | Base URL for upstream requests |
| `--auth` | No | Authorization header value |
| `--audit-log` | No | Audit log path |
| `--dry-run` | No | Evaluate policy without upstream execution |
| `--confirm-store` | No | Confirmation store path |
| `--allow-private-cidr` | No | Allow private CIDR targets (repeatable) |
| `--allow-redirects` | No | Allow redirects (re-validated per hop) |

### 6.11 `toolwright plan`

Generate deterministic capability diffs for review.

```bash
toolwright plan --toolpack ./.toolwright/toolpacks/<toolpack_id>/toolpack.yaml
```

**Options (selected):**

| Option | Required | Description |
|--------|----------|-------------|
| `--toolpack` | Yes | Path to toolpack.yaml |
| `--baseline` | No | Baseline snapshot path override |
| `--output` | No | Output directory for plan artifacts |
| `--format` | No | Output format (`json`/`markdown`/`both`) |

### 6.12 `toolwright bundle`

Create a deterministic zip bundle (toolpack + plan + client config + RUN.md).

```bash
toolwright bundle --toolpack ./.toolwright/toolpacks/<toolpack_id>/toolpack.yaml --out ./toolpack_bundle.zip
```

**Options (selected):**

| Option | Required | Description |
|--------|----------|-------------|
| `--toolpack` | Yes | Path to toolpack.yaml |
| `--out` | Yes | Output zip path |

---

## 7. Storage Format Specifications

### 7.1 Directory Structure

```
project/
├── .toolwright/
│   ├── config.yaml              # Project configuration
│   │
│   ├── captures/
│   │   ├── cap_20240204_abc123/
│   │   │   ├── session.json     # CaptureSession metadata
│   │   │   ├── exchanges.json   # HttpExchange list
│   │   │   └── raw.har          # Original HAR (if imported)
│   │   └── cap_20240205_def456/
│   │       └── ...
│   │
│   ├── artifacts/
│   │   ├── art_20240204_xyz789/
│   │   │   ├── contract.yaml    # OpenAPI spec
│   │   │   ├── contract.json    # OpenAPI spec (JSON)
│   │   │   ├── tools.json       # Tool manifest
│   │   │   ├── toolsets.yaml    # Named toolset subsets
│   │   │   ├── policy.yaml      # Policy config
│   │   │   └── baseline.json    # Drift baseline
│   │   └── ...
│   │
│   ├── toolpacks/
│   │   ├── tp_a1b2c3d4e5f6/
│   │   │   ├── toolpack.yaml
│   │   │   ├── Dockerfile          # optional container runtime
│   │   │   ├── entrypoint.sh       # optional container runtime
│   │   │   ├── toolwright.run         # optional container runtime
│   │   │   ├── requirements.lock   # optional container runtime
│   │   │   ├── artifact/
│   │   │   │   ├── tools.json
│   │   │   │   ├── toolsets.yaml
│   │   │   │   ├── policy.yaml
│   │   │   │   └── baseline.json
│   │   │   ├── lockfile/
│   │   │   │   ├── toolwright.lock.pending.yaml
│   │   │   │   └── toolwright.lock.yaml (optional)
│   │   │   └── .toolwright/
│   │   │       └── approvals/
│   │   │           └── appr_<digestprefix>/
│   │   │               ├── digests.json
│   │   │               └── artifacts/
│   │   └── ...
│   │
│   ├── scopes/
│   │   ├── custom_scope.yaml    # Custom scope definitions
│   │   └── ...
│   │
│   ├── reports/
│   │   ├── drift_20240205.json  # Drift reports
│   │   ├── drift_20240205.md
│   │   └── ...
│   │
│   └── audit.jsonl              # Audit log
```

### 7.2 ID Generation

#### Capture IDs
```
cap_<YYYYMMDD>_<random8>
Example: cap_20240204_a1b2c3d4
```

#### Artifact IDs
```
art_<YYYYMMDD>_<random8>
Example: art_20240204_x1y2z3w4
```

#### Toolpack IDs
```
tp_<hash12>  # deterministic mode
tp_<YYYYMMDD>_<random8>  # volatile mode
```

#### Stable Endpoint IDs
Deterministic hash for tracking endpoints across captures:

```python
import hashlib

def stable_endpoint_id(method: str, path: str, host: str) -> str:
    """Generate stable ID from method, normalized path, and host."""
    canonical = f"{method.upper()}:{host}:{path}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
```

Example: `GET:api.example.com:/users/{id}` → `a1b2c3d4e5f67890`

### 7.3 Toolpack Metadata (`toolpack.yaml`)

```yaml
version: "1.0.0"
schema_version: "1.0"
toolpack_id: tp_a1b2c3d4e5f6
created_at: "1970-01-01T00:00:00+00:00"
capture_id: cap_20240204_abc123
artifact_id: art_20240204_xyz789
scope: agent_safe_readonly
allowed_hosts:
  - api.example.com
origin:
  start_url: https://app.example.com
  name: Checkout Flow
paths:
  tools: artifact/tools.json
  toolsets: artifact/toolsets.yaml
  policy: artifact/policy.yaml
  baseline: artifact/baseline.json
  lockfiles:
    pending: lockfile/toolwright.lock.pending.yaml
runtime:
  mode: local
  container:
    image: "toolwright-toolpack:tp_a1b2c3d4e5f6"
    base_image: "python:3.11-slim"
    dockerfile: "Dockerfile"
    entrypoint: "entrypoint.sh"
    run: "toolwright.run"
    requirements: "requirements.lock"
    env_allowlist:
      - MCPMINT_TOOLPACK
      - MCPMINT_TOOLSET
      - MCPMINT_LOCKFILE
      - MCPMINT_BASE_URL
      - MCPMINT_AUTH_HEADER
      - MCPMINT_AUDIT_LOG
      - MCPMINT_DRY_RUN
      - MCPMINT_CONFIRM_STORE
      - MCPMINT_ALLOW_PRIVATE_CIDR
      - MCPMINT_ALLOW_REDIRECTS
    healthcheck:
      cmd: ["toolwright", "doctor", "--runtime", "local", "--toolpack", "/toolpack/toolpack.yaml"]
      interval_s: 10
      timeout_s: 5
      retries: 3
```

**Lockfile snapshot metadata (toolwright.lock.yaml):**

- `baseline_snapshot_dir`: `.toolwright/approvals/appr_<digestprefix>/artifacts`
- `baseline_snapshot_digest`: sha256 of canonical `digests.json`
- `baseline_snapshot_id`: `appr_<first12_of_digest>` (optional, derived)

Snapshots are materialized after approvals succeed and validated by `toolwright approve check`/CI.

### 7.4 Audit Log Format (JSONL)

Each line is a JSON object:

```json
{
  "timestamp": "2024-02-04T12:00:00.000Z",
  "event_type": "enforce_decision",
  "action_id": "get_user",
  "endpoint_id": "a1b2c3d4e5f67890",
  "method": "GET",
  "path": "/api/users/123",
  "host": "api.example.com",
  "decision": "allow",
  "rules_matched": ["allow_first_party_get"],
  "confirmation_required": false,
  "budget_remaining": 95,
  "latency_ms": 12,
  "caller_context": {
    "agent_id": "agent-001",
    "session_id": "sess-xyz"
  }
}
```

**Event Types:**
- `capture_started`
- `capture_completed`
- `compile_started`
- `compile_completed`
- `drift_detected`
- `enforce_decision`
- `confirmation_requested`
- `confirmation_granted`
- `confirmation_denied`
- `budget_exceeded`
- `request_blocked`

---

## 8. Key Interfaces

### 8.1 CaptureAdapter Protocol

```python
from typing import Protocol, Union
from pathlib import Path

class CaptureAdapter(Protocol):
    """Protocol for traffic capture adapters."""

    async def capture(self, source: Union[str, Path, dict]) -> CaptureSession:
        """Capture traffic and return a session."""
        ...

    def get_stats(self) -> dict[str, int]:
        """Return capture statistics."""
        ...

    def get_warnings(self) -> list[str]:
        """Return any warnings from capture."""
        ...
```

### 8.2 PathNormalizer Protocol

```python
from typing import Protocol

class PathNormalizer(Protocol):
    """Protocol for path normalization."""

    def normalize(self, path: str) -> str:
        """Normalize a URL path to a template.

        Example: /users/123/orders/456 -> /users/{id}/orders/{id}
        """
        ...

    def extract_parameters(self, template: str, path: str) -> dict[str, str]:
        """Extract parameter values from a path given a template."""
        ...
```

### 8.3 SchemaInferrer Protocol

```python
from typing import Protocol, Any

class SchemaInferrer(Protocol):
    """Protocol for JSON schema inference."""

    def infer(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        """Infer JSON Schema from sample data."""
        ...

    def merge(self, schemas: list[dict[str, Any]]) -> dict[str, Any]:
        """Merge multiple schemas into one."""
        ...
```

### 8.4 ScopeEngine Protocol

```python
from typing import Protocol

class ScopeEngine(Protocol):
    """Protocol for scope evaluation."""

    def load_scope(self, name: str) -> Scope:
        """Load a scope by name (built-in or custom)."""
        ...

    def filter_endpoints(
        self,
        endpoints: list[Endpoint],
        scope: Scope
    ) -> list[Endpoint]:
        """Filter endpoints by scope rules."""
        ...

    def classify_endpoint(self, endpoint: Endpoint, scope: Scope) -> dict:
        """Return classification info for endpoint in scope."""
        ...
```

### 8.5 ContractCompiler Protocol

```python
from typing import Protocol

class ContractCompiler(Protocol):
    """Protocol for contract generation."""

    def compile(
        self,
        endpoints: list[Endpoint],
        scope: Scope,
        capture: CaptureSession
    ) -> dict:
        """Compile endpoints to OpenAPI spec."""
        ...

    def to_yaml(self, contract: dict) -> str:
        """Serialize contract to YAML."""
        ...

    def to_json(self, contract: dict) -> str:
        """Serialize contract to JSON."""
        ...
```

### 8.6 ToolManifestGenerator Protocol

```python
from typing import Protocol

class ToolManifestGenerator(Protocol):
    """Protocol for tool manifest generation."""

    def generate(
        self,
        endpoints: list[Endpoint],
        scope: Scope,
        capture: CaptureSession
    ) -> ToolManifest:
        """Generate tool manifest from endpoints."""
        ...

    def action_from_endpoint(self, endpoint: Endpoint) -> Action:
        """Create an Action from an Endpoint."""
        ...
```

### 8.7 DriftEngine Protocol

```python
from typing import Protocol

class DriftEngine(Protocol):
    """Protocol for drift detection."""

    def compare(
        self,
        from_endpoints: list[Endpoint],
        to_endpoints: list[Endpoint]
    ) -> DriftReport:
        """Compare two sets of endpoints for drift."""
        ...

    def compare_to_baseline(
        self,
        baseline: dict,
        endpoints: list[Endpoint]
    ) -> DriftReport:
        """Compare endpoints against a baseline snapshot."""
        ...

    def classify(self, drift_item: DriftItem) -> DriftType:
        """Classify a drift item."""
        ...
```

### 8.8 Enforcer Protocol

```python
from typing import Protocol

class Enforcer(Protocol):
    """Protocol for runtime enforcement."""

    def evaluate(
        self,
        action: Action,
        request: dict,
        policy: Policy
    ) -> EnforceDecision:
        """Evaluate a request against policy."""
        ...

    def check_budget(self, action: Action) -> bool:
        """Check if action is within budget."""
        ...

    def request_confirmation(self, action: Action, message: str) -> str:
        """Request human confirmation, return confirmation token."""
        ...

    def execute(
        self,
        action: Action,
        request: dict,
        confirmation_token: str | None = None
    ) -> dict:
        """Execute action if permitted."""
        ...
```

---

## 9. Extension Points

### 9.1 Custom Capture Adapters

Register custom adapters for new traffic sources:

```python
from toolwright.core.capture.base import CaptureAdapter

class MyProxyAdapter(CaptureAdapter):
    """Adapter for custom proxy format."""

    async def capture(self, source):
        # Parse proprietary format
        # Return CaptureSession
        ...

# Register
from toolwright.core.capture import register_adapter
register_adapter("myproxy", MyProxyAdapter)
```

### 9.2 Custom Scope Providers

Define scopes programmatically:

```python
from toolwright.core.scope import ScopeProvider

class DynamicScopeProvider(ScopeProvider):
    """Load scopes from external source."""

    def get_scope(self, name: str) -> Scope:
        # Fetch from database, API, etc.
        ...

# Register
from toolwright.core.scope import register_provider
register_provider("dynamic", DynamicScopeProvider())
```

### 9.3 Custom Drift Classifiers

Add domain-specific drift classification:

```python
from toolwright.core.drift import DriftClassifier

class PaymentDriftClassifier(DriftClassifier):
    """Extra rules for payment endpoints."""

    def classify(self, drift_item: DriftItem) -> DriftType:
        if "/payment" in drift_item.path:
            # Any payment drift is critical
            return DriftType.BREAKING
        return super().classify(drift_item)

# Register
from toolwright.core.drift import register_classifier
register_classifier("payment", PaymentDriftClassifier())
```

### 9.4 Audit Log Backends

Send audit events to external systems:

```python
from toolwright.core.audit import AuditBackend

class DatadogAuditBackend(AuditBackend):
    """Send audit events to Datadog."""

    def log(self, event: dict):
        # Send to Datadog
        ...

# Register
from toolwright.core.audit import register_backend
register_backend("datadog", DatadogAuditBackend())
```

### 9.5 Custom Redactors

Add domain-specific redaction:

```python
from toolwright.core.capture.redactor import Redactor

class HealthcareRedactor(Redactor):
    """HIPAA-compliant redaction."""

    PII_PATTERNS = [
        r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
        r"\bMRN:\s*\d+\b",         # Medical record number
    ]

    def redact(self, value: str) -> str:
        # Apply healthcare-specific patterns
        ...

# Register
from toolwright.core.capture import register_redactor
register_redactor("healthcare", HealthcareRedactor())
```

---

## 10. Non-Negotiable Defaults

These safety defaults are built into Toolwright's core and **cannot be bypassed accidentally**. Any attempt to disable them requires explicit, documented override.

| Default | Behavior | Override |
|---------|----------|----------|
| **Allowlist Required** | Capture/enforcement requires explicit `--allowed-hosts` | Cannot be disabled |
| **First-Party Only** | Third-party requests excluded unless explicitly included | `--include-third-party` flag |
| **Redaction On** | Cookies, tokens, auth headers redacted before storage | `--no-redact` flag (logged) |
| **State-Changing Confirmation** | POST/PUT/PATCH/DELETE require human confirmation by default | Policy rule with `type: allow` |
| **Audit Logging Always On** | Every compile, drift, enforce decision logged | Cannot be disabled |
| **Deny by Default** | Enforcer blocks unknown requests | Policy `default_action: allow` |
| **No Credentials in Logs** | Audit logs never contain raw credentials | Cannot be disabled |
| **Stable IDs Required** | All endpoints must have deterministic stable_id | Cannot be disabled |
| **Rate Limits Enforced** | Budget rules are enforced, not advisory | Policy rule removal |
| **No Silent Failures** | Enforcement failures are loud and logged | Cannot be disabled |

### Override Requirements

When an override is used, Toolwright:

1. Logs a warning to stderr
2. Records the override in the audit log
3. Adds a warning to generated artifacts
4. Sets a flag in the CaptureSession/Policy for downstream visibility

Example audit log entry for override:

```json
{
  "timestamp": "2024-02-04T12:00:00.000Z",
  "event_type": "safety_override",
  "override": "redaction_disabled",
  "command": "toolwright capture import foo.har --no-redact",
  "user": "developer@example.com"
}
```

---

## 11. Implementation Priority

### Phase 1: Foundation (Week 1-2)

**Goal:** Parse HAR, normalize endpoints, generate basic contracts.

| Component | Files | Priority |
|-----------|-------|----------|
| Data Models | `models/*.py` | P0 |
| HAR Parser | `core/capture/har_parser.py` | P0 |
| Redactor | `core/capture/redactor.py` | P0 |
| Path Normalizer | `core/normalize/path_normalizer.py` | P0 |
| Aggregator | `core/normalize/aggregator.py` | P0 |
| CLI: capture | `cli/capture.py` | P0 |
| Storage | `storage/filesystem.py` | P0 |

**Deliverable:** `toolwright capture import` works end-to-end.

### Phase 2: Scopes & Compile (Week 2-3)

**Goal:** Apply scopes, generate OpenAPI and tool manifests.

| Component | Files | Priority |
|-----------|-------|----------|
| Scope Engine | `core/scope/engine.py` | P0 |
| 5 Built-in Scopes | `core/scope/builtins.py` | P0 |
| Scope DSL Parser | `core/scope/parser.py` | P1 |
| Contract Compiler | `core/compile/contract.py` | P0 |
| Tool Generator | `core/compile/tools.py` | P0 |
| CLI: compile | `cli/compile.py` | P0 |

**Deliverable:** `toolwright compile` produces contract + tools.

### Phase 3: Drift Detection (Week 3-4)

**Goal:** Detect and classify drift between captures.

| Component | Files | Priority |
|-----------|-------|----------|
| Diff Engine | `core/drift/engine.py` | P0 |
| Classifier | `core/drift/classifier.py` | P0 |
| Reporter | `core/drift/reporter.py` | P0 |
| Baseline Generator | `core/compile/baseline.py` | P0 |
| CLI: drift | `cli/drift.py` | P0 |

**Deliverable:** `toolwright drift` with CI exit codes.

### Phase 4: Policy & Enforce (Week 4-6)

**Goal:** Enforce policies at runtime.

| Component | Files | Priority |
|-----------|-------|----------|
| Policy Parser | `core/scope/parser.py` (extend) | P0 |
| Policy Generator | `core/compile/policy.py` | P0 |
| Enforcement Gate | `core/enforce/gate.py` | P0 |
| Budget Manager | `core/enforce/budgets.py` | P1 |
| Confirmation Flow | `core/enforce/confirmation.py` | P1 |
| Audit Logger | `core/audit/logger.py` | P0 |
| CLI: enforce | `cli/enforce.py` | P0 |

**Deliverable:** `toolwright enforce` blocks unauthorized requests.

### Phase 5: Polish (Week 6+)

| Component | Files | Priority |
|-----------|-------|----------|
| Dashboard UI | `cli/serve.py` | P2 |
| Schema Inference | `core/normalize/schema_inferrer.py` | P1 |
| Auth Analyzer | `core/normalize/auth_analyzer.py` | P1 |
| Custom Scope DSL | `core/scope/parser.py` | P1 |
| Playwright Adapter | `core/capture/playwright.py` | P2 |
| Extension APIs | Various | P2 |

### Phase 6: Mint Loop + Toolpacks

**Goal:** One command from traffic capture to MCP-ready, safe toolpack.

| Component | Files | Priority |
|-----------|-------|----------|
| CLI: mint orchestrator | `cli/main.py`, `cli/mint.py` | P0 |
| Toolpack schema + resolver | `core/toolpack.py` | P0 |
| Playwright scripted capture hook | `core/capture/playwright_capture.py` | P0 |
| MCP serve toolpack support | `cli/mcp.py` | P0 |
| Pending lockfile creation in mint | `cli/approve.py`, `cli/mint.py` | P0 |

**Deliverable:** `toolwright mint <start_url> -a <host>` creates a usable toolpack and `toolwright run --toolpack ...` works without manual artifact path lookup.

---

## Appendix A: OpenAPI Contract Example

```yaml
openapi: "3.1.0"
info:
  title: "Example API"
  version: "1.0.0"
  description: "Generated by Toolwright"
  x-toolwright:
    capture_id: "cap_20240204_abc123"
    scope: "first_party_only"
    generated_at: "2024-02-04T12:00:00Z"

servers:
  - url: "https://api.example.com"

paths:
  /api/users/{id}:
    get:
      operationId: get_user
      summary: "Get user by ID"
      x-toolwright:
        stable_id: "a1b2c3d4e5f67890"
        risk_tier: "low"
        observation_count: 15
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            pattern: "^[0-9a-f-]{36}$"
      responses:
        "200":
          description: "User found"
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                  name:
                    type: string
                  email:
                    type: string
                    x-pii: true
```

## Appendix B: Tool Manifest Example

```json
{
  "version": "1.0.0",
  "name": "example-api-tools",
  "generated_at": "2024-02-04T12:00:00Z",
  "capture_id": "cap_20240204_abc123",
  "scope": "agent_safe_readonly",
  "allowed_hosts": ["api.example.com"],
  "default_rate_limit": 60,
  "default_confirmation": "on_risk",
  "actions": [
    {
      "id": "get_user",
      "name": "get_user",
      "description": "Retrieve a user by their unique identifier",
      "endpoint_id": "a1b2c3d4e5f67890",
      "method": "GET",
      "path": "/api/users/{id}",
      "host": "api.example.com",
      "input_schema": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "User ID (UUID format)"
          }
        },
        "required": ["id"]
      },
      "output_schema": {
        "type": "object",
        "properties": {
          "id": {"type": "string"},
          "name": {"type": "string"},
          "email": {"type": "string"}
        }
      },
      "risk_tier": "low",
      "confirmation_required": "never",
      "rate_limit_per_minute": 60,
      "tags": ["user", "read"],
      "scopes": ["agent_safe_readonly", "first_party_only"]
    }
  ]
}
```

## Appendix C: Drift Report Example

```json
{
  "id": "drift_20240205_xyz",
  "generated_at": "2024-02-05T12:00:00Z",
  "from_capture_id": "cap_20240204_abc123",
  "to_capture_id": "cap_20240205_def456",
  "total_drifts": 3,
  "breaking_count": 1,
  "auth_count": 0,
  "risk_count": 1,
  "additive_count": 1,
  "has_breaking_changes": true,
  "requires_review": true,
  "exit_code": 2,
  "drifts": [
    {
      "id": "d1",
      "type": "breaking",
      "severity": "critical",
      "endpoint_id": "a1b2c3d4e5f67890",
      "path": "/api/users/{id}",
      "method": "GET",
      "title": "Response schema changed",
      "description": "Field 'email' removed from response",
      "before": {"type": "object", "properties": {"email": {"type": "string"}}},
      "after": {"type": "object", "properties": {}},
      "recommendation": "Update consumers to handle missing email field"
    },
    {
      "id": "d2",
      "type": "risk",
      "severity": "warning",
      "endpoint_id": "b2c3d4e5f6789012",
      "path": "/api/orders",
      "method": "DELETE",
      "title": "New state-changing endpoint",
      "description": "DELETE /api/orders endpoint added",
      "recommendation": "Review and add to policy before enabling"
    },
    {
      "id": "d3",
      "type": "additive",
      "severity": "info",
      "endpoint_id": "c3d4e5f67890123",
      "path": "/api/products/{id}/reviews",
      "method": "GET",
      "title": "New read-only endpoint",
      "description": "GET /api/products/{id}/reviews endpoint added"
    }
  ]
}
```

---

*End of Specification*

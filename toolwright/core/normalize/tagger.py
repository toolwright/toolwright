"""Auto-tagging engine for endpoint classification.

Classifies endpoints using three signal sources:
1. Path segments (e.g., /orders/ -> commerce)
2. Response/request schema fields (e.g., {price, quantity} -> commerce)
3. HTTP semantics (e.g., DELETE -> destructive, GET collection -> listing)
"""

from __future__ import annotations

from typing import Any

from toolwright.models.endpoint import Endpoint

# Domain -> path segment patterns
_PATH_DOMAIN_MAP: dict[str, set[str]] = {
    "commerce": {
        "orders", "order", "products", "product", "cart", "carts",
        "checkout", "payments", "payment", "invoices", "invoice",
        "subscriptions", "subscription", "pricing", "catalog",
        "inventory", "sku", "shipping", "refund", "refunds",
    },
    "users": {
        "users", "user", "profile", "profiles", "account", "accounts",
        "customer", "customers", "member", "members", "person", "people",
        "contact", "contacts", "patient", "patients",
    },
    "auth": {
        "auth", "login", "logout", "signin", "signout", "oauth",
        "token", "tokens", "session", "sessions", "register",
        "signup", "password", "reset", "verify", "confirm",
        "2fa", "mfa", "otp", "sso", "saml", "oidc",
    },
    "admin": {
        "admin", "settings", "config", "configuration", "management",
        "dashboard", "console",
    },
    "search": {
        "search", "query", "graphql", "filter", "lookup",
    },
    "content": {
        "posts", "post", "articles", "article", "pages", "page",
        "comments", "comment", "media", "files", "file",
        "documents", "document", "uploads", "upload",
    },
    "notifications": {
        "notifications", "notification", "alerts", "alert",
        "messages", "message", "email", "emails", "sms",
    },
}

# Domain -> response/request field patterns
_FIELD_DOMAIN_MAP: dict[str, set[str]] = {
    "commerce": {
        "price", "quantity", "sku", "subtotal", "tax",
        "discount", "currency", "amount", "cost", "unit_price",
        "line_items", "cart_id", "order_id", "product_id",
        "shipping_address", "billing_address", "payment_method",
    },
    "users": {
        "email", "phone", "first_name", "last_name",
        "full_name", "username", "avatar", "bio", "date_of_birth",
        "address", "role", "permissions",
    },
    "auth": {
        "token", "access_token", "refresh_token", "session_id",
        "expires_at", "expires_in", "scope", "grant_type",
        "client_id", "client_secret", "id_token",
    },
}

# Fields that are too ambiguous to trigger a domain tag on their own.
# They only count if a strong field from the same domain is also present.
_AMBIGUOUS_FIELDS: dict[str, set[str]] = {
    "users": {"name"},
}

# Path segments to skip when extracting domain signals
_SKIP_SEGMENTS = {"api", "v1", "v2", "v3", "v4", "rest", "public", "private"}


class AutoTagger:
    """Classify endpoints with semantic tags using heuristic signals."""

    def classify(self, endpoint: Endpoint) -> list[str]:
        """Produce a deduplicated list of semantic tags for an endpoint.

        Merges existing endpoint tags with newly inferred tags.
        """
        tags: list[str] = list(endpoint.tags)

        # 1. Path segment signals
        tags.extend(self._tags_from_path(endpoint.path))

        # 2. Response/request field signals
        tags.extend(self._tags_from_fields(endpoint.response_body_schema))
        tags.extend(self._tags_from_fields(endpoint.request_body_schema))

        # 3. HTTP semantic signals
        tags.extend(self._tags_from_http_semantics(endpoint.method, endpoint.path))

        # Deduplicate preserving order
        seen: set[str] = set()
        result: list[str] = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                result.append(tag)

        return result

    def enrich_endpoints(self, endpoints: list[Endpoint]) -> None:
        """Enrich endpoint tags in place with auto-classified tags."""
        for ep in endpoints:
            ep.tags = self.classify(ep)

    def _tags_from_path(self, path: str) -> list[str]:
        """Extract domain tags from path segments."""
        tags: list[str] = []
        segments = [
            s.lower()
            for s in path.strip("/").split("/")
            if s and not s.startswith("{") and s.lower() not in _SKIP_SEGMENTS
        ]

        for segment in segments:
            for domain, patterns in _PATH_DOMAIN_MAP.items():
                if segment in patterns:
                    tags.append(domain)

        return tags

    def _tags_from_fields(self, schema: dict[str, Any] | None) -> list[str]:
        """Extract domain tags from schema field names.

        For domains with ambiguous fields (e.g., 'name' for users),
        the ambiguous field alone is not enough -- at least one strong
        (non-ambiguous) field must also be present.
        """
        if not schema or not isinstance(schema, dict):
            return []

        field_names = self._collect_field_names(schema)
        tags: list[str] = []

        for domain, patterns in _FIELD_DOMAIN_MAP.items():
            strong_matches = field_names & patterns
            if strong_matches:
                tags.append(domain)
                continue

            # Check ambiguous fields: only count if a strong field is present
            ambiguous = _AMBIGUOUS_FIELDS.get(domain, set())
            if ambiguous and (field_names & ambiguous):
                # Ambiguous field found but no strong field -> skip
                pass

        return tags

    def _collect_field_names(
        self, schema: dict[str, Any], depth: int = 0
    ) -> set[str]:
        """Recursively collect all field names from a JSON Schema."""
        if depth > 10:
            return set()

        names: set[str] = set()
        props = schema.get("properties", {})
        for key, value in props.items():
            names.add(key.lower())
            if isinstance(value, dict):
                # Recurse into nested objects
                names |= self._collect_field_names(value, depth + 1)
                # Recurse into array items
                items = value.get("items", {})
                if isinstance(items, dict):
                    names |= self._collect_field_names(items, depth + 1)

        return names

    def _tags_from_http_semantics(self, method: str, path: str) -> list[str]:
        """Extract tags from HTTP method and path structure."""
        tags: list[str] = []
        method_upper = method.upper()

        # DELETE -> destructive
        if method_upper == "DELETE":
            tags.append("destructive")

        # GET on a collection (path doesn't end with {param}) -> listing
        if method_upper == "GET" and not path.rstrip("/").endswith("}"):
            tags.append("listing")

        # POST with search/query/graphql in path -> search
        if method_upper == "POST":
            lower_path = path.lower()
            if any(kw in lower_path for kw in ("/search", "/query", "/graphql")):
                tags.append("search")

        return tags

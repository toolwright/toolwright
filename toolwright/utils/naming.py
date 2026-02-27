"""Tool naming utilities using verb_noun pattern."""

from __future__ import annotations

import re

# Method to verb mapping
METHOD_VERBS = {
    "GET": "get",
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
    "HEAD": "check",
    "OPTIONS": "options",
}

# Special path patterns that override the default verb
VERB_OVERRIDES = {
    # GET overrides
    ("GET", r".*/list$"): "list",
    ("GET", r".*/search.*"): "search",
    ("GET", r".*/query.*"): "query",
    ("GET", r".*/find.*"): "find",
    ("GET", r".*/count$"): "count",
    ("GET", r".*/exists$"): "check",
    # POST overrides (read-only POST patterns)
    ("POST", r".*/search.*"): "search",
    ("POST", r".*/query.*"): "query",
    ("POST", r".*/graphql.*"): "query",
    ("POST", r".*/login.*"): "login",
    ("POST", r".*/logout.*"): "logout",
    ("POST", r".*/register.*"): "register",
    ("POST", r".*/signup.*"): "signup",
    ("POST", r".*/signin.*"): "signin",
    ("POST", r".*/refresh.*"): "refresh",
    ("POST", r".*/verify.*"): "verify",
    ("POST", r".*/validate.*"): "validate",
    ("POST", r".*/upload.*"): "upload",
    ("POST", r".*/import.*"): "import",
    ("POST", r".*/export.*"): "export",
    # DELETE overrides
    ("DELETE", r".*/logout.*"): "logout",
}

# Words to strip from path segments
STRIP_WORDS = {"api", "v1", "v2", "v3", "v4", "rest", "public", "private", "internal"}

# Placeholder patterns
PLACEHOLDER_PATTERN = re.compile(r"\{[^}]+\}")
UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
ID_PATTERN = re.compile(r"^\d+$")


def generate_tool_name(method: str, path: str) -> str:
    """Generate a human-friendly tool name using verb_noun pattern.

    Examples:
        GET /users/{id} -> get_user
        GET /users -> list_users
        POST /users -> create_user
        DELETE /users/{id} -> delete_user
        GET /products/{id}/reviews -> get_product_reviews
        POST /search/products -> search_products

    Args:
        method: HTTP method
        path: URL path (may contain placeholders like {id})

    Returns:
        Tool name in verb_noun format
    """
    method = method.upper()

    # Get base verb from method
    verb = METHOD_VERBS.get(method, "call")

    # Check for verb overrides based on path patterns
    for (m, pattern), override_verb in VERB_OVERRIDES.items():
        if m == method and re.match(pattern, path, re.I):
            verb = override_verb
            break

    # Extract noun from path
    noun = _extract_noun(path, method, verb)

    if not noun:
        return verb

    return f"{verb}_{noun}"


def _extract_noun(path: str, method: str, verb: str) -> str:
    """Extract the noun portion from a path.

    Args:
        path: URL path
        method: HTTP method (affects singularization)
        verb: The verb that will be used (to avoid duplication)

    Returns:
        Noun string (e.g., "user", "product_reviews")
    """
    # Remove leading/trailing slashes and split
    path = path.strip("/")
    segments = path.split("/")

    # Filter out:
    # - Empty segments
    # - Version segments (v1, v2, api, etc.)
    # - ID placeholders ({id}, {userId}, etc.)
    # - Actual IDs (UUIDs, numeric IDs)
    # - Segments that match the verb (to avoid "search_search")
    meaningful_segments = []
    for segment in segments:
        segment_lower = segment.lower()

        # Skip common prefixes
        if segment_lower in STRIP_WORDS:
            continue

        # Skip placeholders
        if PLACEHOLDER_PATTERN.match(segment):
            continue

        # Skip UUIDs
        if UUID_PATTERN.match(segment):
            continue

        # Skip numeric IDs
        if ID_PATTERN.match(segment):
            continue

        # Skip segments that match the verb (avoid "search_search", "query_graphql")
        if segment_lower == verb:
            continue

        # Skip "graphql" when verb is "query" (special case)
        if segment_lower == "graphql" and verb == "query":
            continue

        meaningful_segments.append(segment)

    if not meaningful_segments:
        return ""

    # For GET with trailing placeholder (e.g., /users/{id}), singularize last segment
    # For GET without placeholder (e.g., /users), keep as is (list operation)
    # For POST/PUT/DELETE, singularize UNLESS it's a read-only POST (search, query, etc.)
    read_only_verbs = {"search", "query", "list", "find", "count", "check"}
    should_singularize = method in ("POST", "PUT", "PATCH", "DELETE") and verb not in read_only_verbs

    # Check if original path ends with a placeholder
    if method == "GET" and segments and PLACEHOLDER_PATTERN.match(segments[-1]):
        should_singularize = True

    # For nested resources like /products/{id}/reviews, singularize the middle segment
    # but keep the last segment as-is (unless should_singularize is True)
    result_segments = []
    for i, segment in enumerate(meaningful_segments):
        is_last = i == len(meaningful_segments) - 1
        is_followed_by_placeholder = False

        # Check if this segment is followed by a placeholder in original path
        seg_idx = segments.index(segment) if segment in segments else -1
        if seg_idx >= 0 and seg_idx + 1 < len(segments):
            next_seg = segments[seg_idx + 1]
            is_followed_by_placeholder = PLACEHOLDER_PATTERN.match(next_seg) is not None

        # Singularize if:
        # 1. It's the last segment and should_singularize is True
        # 2. It's a middle segment followed by a placeholder (e.g., "products" in /products/{id}/reviews)
        if (is_last and should_singularize) or (not is_last and is_followed_by_placeholder):
            segment = _singularize(segment)

        result_segments.append(_to_snake_case(segment))

    return "_".join(result_segments)


def _singularize(word: str) -> str:
    """Simple singularization.

    This is intentionally simple. For more complex cases, users can override tool_id.
    """
    word_lower = word.lower()

    # Irregular plurals
    irregulars = {
        "people": "person",
        "children": "child",
        "men": "man",
        "women": "woman",
        "feet": "foot",
        "teeth": "tooth",
        "geese": "goose",
        "mice": "mouse",
        "indices": "index",
        "vertices": "vertex",
        "matrices": "matrix",
    }

    if word_lower in irregulars:
        return irregulars[word_lower]

    # Common patterns
    if word_lower.endswith("ies") and len(word_lower) > 3:
        return word[:-3] + "y"
    if word_lower.endswith("es") and len(word_lower) > 3 and (
        word_lower[-3] in "sxz" or word_lower[-4:-2] in ("ch", "sh")
    ):
        # Words ending in -ses, -xes, -zes, -ches, -shes
        return word[:-2]
    if word_lower.endswith("s") and not word_lower.endswith("ss"):
        return word[:-1]

    return word


def _to_snake_case(text: str) -> str:
    """Convert text to snake_case."""
    # Handle camelCase and PascalCase
    text = re.sub(r"([a-z])([A-Z])", r"\1_\2", text)
    # Handle kebab-case
    text = text.replace("-", "_")
    # Lowercase and clean up
    text = text.lower()
    # Remove non-alphanumeric except underscore
    text = re.sub(r"[^a-z0-9_]", "", text)
    # Collapse multiple underscores
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def resolve_collision(base_name: str, existing_names: set[str], host: str) -> str:
    """Resolve a name collision by adding qualifiers.

    Strategy from STRATEGY.md:
    1. Namespace by host first: get_user__api_example_com
    2. If still collides, add counter: get_user__api_example_com__2

    Args:
        base_name: The desired tool name
        existing_names: Set of already-used names
        host: The host this tool belongs to

    Returns:
        A unique tool name
    """
    if base_name not in existing_names:
        return base_name

    # Try with host suffix
    host_suffix = _to_snake_case(host.replace(".", "_"))
    namespaced = f"{base_name}__{host_suffix}"

    if namespaced not in existing_names:
        return namespaced

    # Add counter
    counter = 2
    while f"{namespaced}__{counter}" in existing_names:
        counter += 1

    return f"{namespaced}__{counter}"

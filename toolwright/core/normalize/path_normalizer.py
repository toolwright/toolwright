"""Path normalization for converting concrete paths to templates."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


class PathNormalizer:
    """Normalize URL paths to templates with placeholders."""

    # UUID pattern
    UUID_PATTERN = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        re.IGNORECASE,
    )

    # Numeric ID pattern (avoid matching version segments like v1, v2)
    NUMERIC_ID_PATTERN = re.compile(r"^(?!v\d+$)\d+$")

    # MongoDB ObjectId pattern (24 hex chars)
    OBJECTID_PATTERN = re.compile(r"^[0-9a-f]{24}$", re.IGNORECASE)

    # Prefixed ID pattern: short alpha prefix + separator + alphanumeric suffix
    # Matches: usr_123, prod_001, cus_test123abc, pi_abc123, ord-abc123, item_7f3a
    # Also matches: U12345678 (single uppercase letter + digits, like Slack IDs)
    PREFIXED_ID_PATTERN = re.compile(
        # Require at least one digit in the suffix so stable snake_case route
        # keys like `content_types` don't get normalized as IDs.
        r"^(?:[a-zA-Z]{1,10}[_-][a-zA-Z0-9]*\d[a-zA-Z0-9]*|[A-Z][0-9]{4,})$"
    )

    # Base64-like tokens (long alphanumeric strings, typically > 20 chars)
    TOKEN_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{20,}$")

    # Email-like pattern
    EMAIL_PATTERN = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

    _PLACEHOLDER_RE = re.compile(r"\{([^}]+)\}")

    def __init__(
        self,
        uuid_placeholder: str = "{uuid}",
        id_placeholder: str = "{id}",
        token_placeholder: str = "{token}",
        email_placeholder: str = "{email}",
        slug_placeholder: str = "{slug}",
    ) -> None:
        """Initialize normalizer with placeholder formats.

        Args:
            uuid_placeholder: Placeholder for UUIDs
            id_placeholder: Placeholder for numeric IDs
            token_placeholder: Placeholder for tokens
            email_placeholder: Placeholder for emails
            slug_placeholder: Placeholder for variable slugs
        """
        self.uuid_placeholder = uuid_placeholder
        self.id_placeholder = id_placeholder
        self.token_placeholder = token_placeholder
        self.email_placeholder = email_placeholder
        self.slug_placeholder = slug_placeholder

    def normalize(self, path: str) -> str:
        """Normalize a URL path to a template.

        Args:
            path: Raw URL path (e.g., /users/123/orders/abc-def-123)

        Returns:
            Normalized path template (e.g., /users/{id}/orders/{uuid})
        """
        if not path:
            return "/"

        # Handle query strings - normalize path only
        if "?" in path:
            path = path.split("?")[0]

        # Split into segments
        segments = path.split("/")
        normalized_segments: list[str] = []

        for segment in segments:
            if not segment:
                normalized_segments.append(segment)
                continue

            normalized = self._normalize_segment(segment)
            normalized_segments.append(normalized)

        return "/".join(normalized_segments) or "/"

    def normalize_url(self, url: str) -> tuple[str, str, str]:
        """Normalize a full URL and extract components.

        Args:
            url: Full URL

        Returns:
            Tuple of (host, normalized_path, normalized_full_path_with_method)
        """
        parsed = urlparse(url)
        host = parsed.netloc
        path = self.normalize(parsed.path)

        return host, path, f"{host}{path}"

    def _normalize_segment(self, segment: str) -> str:
        """Normalize a single path segment.

        Args:
            segment: A path segment

        Returns:
            Normalized segment (placeholder or original)
        """
        # Check patterns in order of specificity

        # UUID (most specific)
        if self.UUID_PATTERN.match(segment):
            return self.uuid_placeholder

        # MongoDB ObjectId
        if self.OBJECTID_PATTERN.match(segment):
            return self.id_placeholder

        # Numeric ID
        if self.NUMERIC_ID_PATTERN.match(segment):
            return self.id_placeholder

        # Prefixed ID (usr_123, cus_abc, pi_xyz, U12345678)
        if self.PREFIXED_ID_PATTERN.match(segment):
            return self.id_placeholder

        # Email
        if self.EMAIL_PATTERN.match(segment):
            return self.email_placeholder

        # Long token-like strings
        if self.TOKEN_PATTERN.match(segment):
            return self.token_placeholder

        # Long slug-like json files (e.g., product listings) from a single observation
        if self._is_slug_json_file(segment):
            # Preserve the `.json` suffix so the resulting template remains a valid route.
            return f"{self.slug_placeholder}.json"

        # Keep the original segment
        return segment

    @staticmethod
    def _is_slug_json_file(segment: str) -> bool:
        """Heuristic for dynamic listing-like JSON paths (single-observation safe)."""
        if not segment or not segment.lower().endswith(".json"):
            return False

        stem = segment[:-5]  # trim ".json"
        if len(stem) < 16:
            return False

        parts = [p for p in stem.split("-") if p]
        if len(parts) < 3:
            return False

        if not all(re.fullmatch(r"[A-Za-z0-9]+", part) is not None for part in parts):
            return False

        # Stable route keys (search, index, manifest) should stay concrete.
        return stem.lower() not in {"search", "index", "manifest"}

    def extract_parameters(
        self, template: str, path: str
    ) -> dict[str, str] | None:
        """Extract parameter values from a path given a template.

        Args:
            template: Path template (e.g., /users/{id})
            path: Actual path (e.g., /users/123)

        Returns:
            Dict of parameter names to values, or None if no match
        """
        template_segments = template.split("/")
        path_segments = path.split("/")

        if len(template_segments) != len(path_segments):
            return None

        params: dict[str, str] = {}

        for template_seg, path_seg in zip(template_segments, path_segments, strict=False):
            if not template_seg:
                if template_seg != path_seg:
                    return None
                continue

            placeholders = list(self._PLACEHOLDER_RE.finditer(template_seg))
            if not placeholders:
                if template_seg != path_seg:
                    return None
                continue

            # Support placeholders embedded within a segment (e.g., `{slug}.json`).
            pattern = []
            cursor = 0
            for match in placeholders:
                literal = template_seg[cursor:match.start()]
                pattern.append(re.escape(literal))
                name = match.group(1)
                pattern.append(rf"(?P<{name}>[^/]+)")
                cursor = match.end()
            pattern.append(re.escape(template_seg[cursor:]))

            segment_re = re.compile("^" + "".join(pattern) + "$")
            matched = segment_re.match(path_seg)
            if not matched:
                return None

            for name, value in matched.groupdict().items():
                params[name] = value

        return params

    def matches_template(self, template: str, path: str) -> bool:
        """Check if a path matches a template.

        Args:
            template: Path template
            path: Actual path

        Returns:
            True if path matches template
        """
        return self.extract_parameters(template, path) is not None


class VarianceNormalizer:
    """Detect variable path segments by analyzing variance across samples."""

    def __init__(self, base_normalizer: PathNormalizer | None = None) -> None:
        """Initialize with optional base normalizer.

        Args:
            base_normalizer: PathNormalizer for initial normalization
        """
        self.normalizer = base_normalizer or PathNormalizer()
        self.templates: list[dict[str, Any]] = []

    def learn_from_paths(self, paths: list[str], method: str) -> None:
        """Learn path patterns from a set of paths.

        Args:
            paths: List of paths for the same method
            method: HTTP method
        """
        for path in paths:
            normalized = self.normalizer.normalize(path)
            segments = self._split_segments(normalized)

            template = self._find_matching_template(method, segments)
            if template is None:
                self.templates.append(
                    {
                        "method": method,
                        "length": len(segments),
                        "segments": list(segments),
                        "fixed": [True] * len(segments),
                    }
                )
            else:
                # Update template - mark varying segments
                for i, seg in enumerate(segments):
                    if template["fixed"][i] and template["segments"][i] != seg:
                        template["segments"][i] = "{slug}"
                        template["fixed"][i] = False

    def normalize_path(self, path: str, method: str) -> str:
        """Normalize a path using learned templates.

        Args:
            path: Path to normalize
            method: HTTP method

        Returns:
            Normalized path
        """
        normalized = self.normalizer.normalize(path)
        segments = self._split_segments(normalized)

        template = self._select_template(method, segments)
        if template is None:
            return "/" + "/".join(segments) if segments else "/"

        return "/" + "/".join(template["segments"]) if template["segments"] else "/"

    def _split_segments(self, path: str) -> list[str]:
        """Split path into non-empty segments."""
        return [s for s in path.split("/") if s]

    def _find_matching_template(
        self, method: str, segments: list[str]
    ) -> dict[str, Any] | None:
        """Find a template that matches the given segments."""
        exact_match: dict[str, Any] | None = None
        best_compatible: dict[str, Any] | None = None
        best_compatible_score = -1

        for template in self.templates:
            if template["method"] != method or template["length"] != len(segments):
                continue

            if self._segments_match(template, segments):
                exact_match = template
                break

            if not self._segments_compatible_for_variance(template, segments):
                continue

            # Prefer the most specific compatible template to reduce accidental merges.
            score = sum(
                1
                for i, is_fixed in enumerate(template["fixed"])
                if is_fixed and i < len(template["segments"]) and template["segments"][i] == segments[i]
            )
            if score > best_compatible_score:
                best_compatible = template
                best_compatible_score = score

        return exact_match or best_compatible

    def _select_template(
        self, method: str, segments: list[str]
    ) -> dict[str, Any] | None:
        """Select the best matching template for segments."""
        candidates = [
            t
            for t in self.templates
            if t["method"] == method
            and t["length"] == len(segments)
            and self._segments_match(t, segments)
        ]

        if not candidates:
            return None

        # Prefer template with most fixed segments
        return max(candidates, key=lambda t: sum(1 for f in t["fixed"] if f))

    def _segments_match(self, template: dict[str, Any], segments: list[str]) -> bool:
        """Check if segments match a template."""
        for i, segment in enumerate(segments):
            if i >= len(template["fixed"]):
                return False
            if template["fixed"][i] and template["segments"][i] != segment:
                return False
        return True

    def _segments_compatible_for_variance(
        self,
        template: dict[str, Any],
        segments: list[str],
    ) -> bool:
        """Return True when a path is close enough to update an existing template.

        Compatibility is conservative by design:
        - method/length must already match (enforced by caller)
        - existing variable segments always match
        - fixed mismatches are allowed only for slug-like segment pairs
        """
        mismatches = 0

        for i, segment in enumerate(segments):
            if i >= len(template["fixed"]):
                return False

            if not template["fixed"][i]:
                # Existing variable placeholder segment.
                continue

            template_segment = template["segments"][i]
            if template_segment == segment:
                continue

            if not self._is_slug_like_pair(template_segment, segment):
                return False

            mismatches += 1

        return mismatches > 0

    @staticmethod
    def _is_slug_like_pair(left: str, right: str) -> bool:
        """Check whether two differing segments look like variable slugs/files."""
        return VarianceNormalizer._is_slug_like(left) and VarianceNormalizer._is_slug_like(right)

    @staticmethod
    def _is_slug_like(value: str) -> bool:
        """Heuristic for user/content slugs (intentionally conservative)."""
        if not value:
            return False

        # Existing placeholders are always variable.
        if value.startswith("{") and value.endswith("}"):
            return True

        stem = value
        has_extension = "." in value
        if has_extension:
            stem = value.rsplit(".", 1)[0]

        # Require at least three slug tokens to avoid merging stable resource roots.
        parts = [p for p in re.split(r"[-_]", stem) if p]
        if len(parts) < 3:
            return False

        if not all(re.fullmatch(r"[A-Za-z0-9]+", part) is not None for part in parts):
            return False

        has_hyphen = "-" in stem
        has_underscore = "_" in stem
        has_digit = any(any(ch.isdigit() for ch in part) for part in parts)

        # API route keys commonly use underscored words (e.g., iron_footer_next).
        # Treat underscore-only alphabetic segments as stable unless there is
        # additional variability evidence (extension or digits).
        if has_underscore and not has_hyphen and not has_extension and not has_digit:
            return False

        # Three plain words without numbers/extensions are often static route names.
        return not (len(parts) == 3 and not has_extension and not has_digit)

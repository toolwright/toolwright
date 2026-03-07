"""Probe template model for drift probing of traffic-captured tools.

A probe template is a sanitized request that can be replayed to check
whether an API endpoint's response shape has changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProbeTemplate:
    """Sanitized request template for drift probing.

    Derived from the original captured request at compile time.
    Auth headers and ephemeral query params are stripped.
    """

    method: str
    path: str
    query_params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "path": self.path,
            "query_params": self.query_params,
            "headers": self.headers,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProbeTemplate:
        return cls(
            method=data["method"],
            path=data["path"],
            query_params=data.get("query_params", {}),
            headers=data.get("headers", {}),
        )

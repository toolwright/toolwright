"""Shared risk-tier path keyword patterns.

Used by both the endpoint aggregator (normalize pipeline) and scope inference
engine to ensure consistent risk classification across the pipeline.
"""

from __future__ import annotations

import re

CRITICAL_PATH_KEYWORDS = re.compile(
    r"(admin|payment|payments|refund|refunds|billing|checkout|settle|payout)",
    re.IGNORECASE,
)
HIGH_RISK_PATH_KEYWORDS = re.compile(
    r"(delete|destroy|remove|purge|revoke|suspend|deactivate|terminate)",
    re.IGNORECASE,
)

"""Toolwright: Self-expanding, self-repairing, human-correctable tool infrastructure for AI agents."""

import sys

if sys.version_info < (3, 11):
    raise RuntimeError(
        f"Toolwright requires Python 3.11+. You are running "
        f"Python {sys.version_info.major}.{sys.version_info.minor}. "
        f"See https://www.python.org/downloads/"
    )

__version__ = "1.0.0a1"

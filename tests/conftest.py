"""Shared test setup for the RedHood Systems suite.

Ensures the repo root is importable and provides a feedparser stub when the
real package can't be installed (its sgmllib3k build dependency fails in some
sandboxes). The stub is only used as a fallback — none of the tests exercise
feedparser itself; it's just a transitive import of redhood_aggregator.
"""

import os
import sys
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    import feedparser  # noqa: F401
except ImportError:
    sys.modules['feedparser'] = types.ModuleType('feedparser')

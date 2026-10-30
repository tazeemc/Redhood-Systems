"""Shared test setup for the RedHood Systems suite.

Ensures the repo root is importable and provides a feedparser stub when the
real package can't be installed (its sgmllib3k build dependency fails in some
sandboxes). The stub is only used as a fallback — none of the tests exercise
feedparser itself; it's just a transitive import of redhood_aggregator.
"""

import os
import sys
import types

import pytest

# The aggregator publishes to GitHub Pages whenever GITHUB_TOKEN is set, and
# redhood_aggregator's load_dotenv() would import it from .env at import time.
# load_dotenv() never overrides an existing variable, so blanking it here keeps
# every test run (full pipeline tests included) off the live site.
os.environ['GITHUB_TOKEN'] = ''
os.environ['REDHOOD_NO_PUBLISH'] = '1'

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    import feedparser  # noqa: F401
except ImportError:
    _stub = types.ModuleType('feedparser')
    _stub.parse = lambda *a, **k: None      # monkeypatched by the RSS tests
    sys.modules['feedparser'] = _stub


@pytest.fixture(autouse=True)
def _never_publish(monkeypatch):
    """Belt and braces: no test may reach GitHub Pages, whatever it sets up."""
    monkeypatch.setenv('GITHUB_TOKEN', '')
    monkeypatch.setenv('REDHOOD_NO_PUBLISH', '1')

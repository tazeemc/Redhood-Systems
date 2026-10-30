"""End-to-end (network-free) run of the aggregator with the history layer:
regime persisted per run, continuation flags, history block in the prompt,
scoring + forward returns after the run, timeline page regenerated."""

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

np = pytest.importorskip("numpy")

import redhood_aggregator as agg_mod  # noqa: E402
import redhood_timeline as tl  # noqa: E402
import score_narratives as sn  # noqa: E402
from models import init_schema  # noqa: E402
from redhood_aggregator import FeedItem, NarrativeExtractor, RedHoodAggregator  # noqa: E402
from redhood_regime_detector import RegimeDetector, calibrate  # noqa: E402


class _FakeMessages:
    def __init__(self):
        self.prompts = []

    def create(self, **kwargs):
        prompt = kwargs['messages'][0]['content']
        self.prompts.append(prompt)
        if 'stress-testing trade ideas' in prompt:
            text = json.dumps({'stress_tests': [
                {'narrative_title': 'Defense Primes Procurement Surge', 'bear_case': 'crowded',
                 'disconfirming_signals': ['ceasefire'], 'conviction_adjustment': 'Quarter Size — crowded'},
                {'narrative_title': 'AI Capex Acceleration', 'bear_case': 'capex digestion',
                 'disconfirming_signals': ['guidance cut'], 'conviction_adjustment': 'Half Size — fine'}]})
        else:
            text = json.dumps({'narratives': [
                {'title': 'Defense Primes Procurement Surge', 'entropy_risk': 7,
                 'hypothesis': 'Long LMT, RTX basket with 6-month horizon', 'rationale': 'see feed 1',
                 'catalysts': ['NATO summit'], 'supporting_feed_indices': [1], 'continues_prior': True},
                {'title': 'AI Capex Acceleration', 'entropy_risk': 5,
                 'hypothesis': 'Long NVDA shares with 8% trailing stop', 'rationale': 'see feed 2',
                 'catalysts': ['earnings'], 'supporting_feed_indices': [2], 'continues_prior': False}]})
        return type('R', (), {'content': [type('C', (), {'text': text})()]})()


def _feeds():
    now = datetime.now()
    return [FeedItem('twitter', '@a', f'headline {i}', now - timedelta(minutes=i), url=f'https://x.com/a/{i}')
            for i in range(3)]


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    db = str(tmp_path / 'p.db')
    init_schema(db)
    # one earlier run so the prompt has history and continuation flags fire
    conn = sqlite3.connect(db)
    earlier = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)).isoformat()
    rid = conn.execute("INSERT INTO runs (run_at, hours_back, feeds_collected, narratives_extracted) VALUES (?, 5, 10, 1)",
                       (earlier,)).lastrowid
    conn.execute("INSERT INTO narratives (id, run_id, title, entropy_risk, hypothesis, rationale, catalysts, created_at) "
                 "VALUES ('old1', ?, 'Defense Primes Procurement Surge', 6, 'Long LMT, NOC', 'r', '[]', ?)", (rid, earlier))
    conn.commit()
    conn.close()

    monkeypatch.setattr(agg_mod, 'DB_PATH', db)
    monkeypatch.setattr(sn, 'DB_PATH', db)
    monkeypatch.setattr(tl, 'DOCS_DIR', str(tmp_path / 'docs'))
    monkeypatch.setenv('REDHOOD_NO_PRICE_REFRESH', '1')

    a = RedHoodAggregator.__new__(RedHoodAggregator)
    a.config = agg_mod.Config()
    a.config.OUTPUT_DIR = str(tmp_path / 'data')
    import os
    os.makedirs(a.config.OUTPUT_DIR, exist_ok=True)
    a.rss_scraper = type('S', (), {'fetch': lambda self, *_a, **_k: []})()
    a.twitter_scraper = type('S', (), {'fetch': lambda self, *_a, **_k: _feeds()})()
    a.telegram_scraper = type('S', (), {'fetch': lambda self, *_a, **_k: []})()
    extractor = NarrativeExtractor.__new__(NarrativeExtractor)
    extractor.model = 'test'
    extractor.client = type('Client', (), {})()
    extractor.client.messages = _FakeMessages()
    a.ai_engine = extractor
    monkeypatch.setattr(a, '_fetch_ticker_prices', lambda: '', raising=False)

    cal = calibrate(60, 0.15, sims=400, seed=2, use_file=False)
    rng = np.random.default_rng(0)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.10 / math.sqrt(252), 150)))
    det = RegimeDetector(base_temp=0.15, calibration=cal)

    def fake_regime():
        return det.update(prices)
    monkeypatch.setattr(a, '_compute_regime', fake_regime, raising=False)
    return a, db, extractor.client.messages


def test_run_persists_regime_history_flags_and_prompt(pipeline):
    a, db, messages = pipeline
    results = a.run(hours_back=1)
    assert len(results['narratives']) == 2
    assert results['regime']['label'] in {'TRENDING', 'CHOPPY', 'CRISIS', 'TRANSITION'}

    # the extraction prompt carried the history block and the regime block
    first_prompt = messages.prompts[0]
    assert 'HISTORICAL CONTEXT' in first_prompt and 'Defense Primes Procurement Surge' in first_prompt
    assert 'CURRENT MARKET REGIME' in first_prompt and 'Occupation entropy' in first_prompt

    conn = sqlite3.connect(db)
    # regime persisted for the run
    reg = conn.execute("SELECT label, detector_version, temperature, kl_threshold FROM regime_history").fetchall()
    assert len(reg) == 1 and reg[0][1] == 'v2' and reg[0][3] > 0
    # continuation flag computed from the earlier narrative
    pm = dict(conn.execute("SELECT title, prior_mentions FROM narratives WHERE id != 'old1'").fetchall())
    assert pm['Defense Primes Procurement Surge'] == 1
    assert pm['AI Capex Acceleration'] == 0
    # scoring ran after the run: grades + grader long tickers
    assert conn.execute("SELECT COUNT(*) FROM narrative_grades").fetchone()[0] == 2
    longs = {r[0] for r in conn.execute("SELECT ticker FROM narrative_tickers WHERE is_long_equity = 1")}
    assert {'LMT', 'RTX', 'NVDA'} <= longs
    conn.close()

    # report carries the continuation tag and the v2 regime panel
    html = open(results_html_path(a), encoding='utf-8').read()
    assert 'seen 1&times; in the last 30 days' in html
    assert 'detector v2' in html


def results_html_path(a):
    import glob
    import os
    files = sorted(glob.glob(os.path.join(a.config.OUTPUT_DIR, 'redhood_reads_*.html')))
    assert files
    return files[-1]

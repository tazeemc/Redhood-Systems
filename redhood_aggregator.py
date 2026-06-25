"""
RedHood Systems - Feed Aggregator & AI Analysis Tool
======================================================

A production-ready prototype for aggregating market intelligence from multiple sources
and extracting actionable narratives using Claude AI.

Author: Tazeem Chowdhury
Created: February 15, 2026
GitHub: https://github.com/tazeemc/Redhood-Systems

Key Features:
- Multi-source scraping (X/Twitter, Substack RSS)
- AI-powered narrative extraction using Claude API
- Entropy risk scoring (market uncertainty quantification)
- Trade hypothesis generation
- Exportable insights (JSON, CSV)

Dependencies:
    pip install anthropic feedparser pandas python-dotenv --break-system-packages
"""

import os
import json
import time
import base64
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Any
import sqlite3
import feedparser
from anthropic import Anthropic
from dotenv import load_dotenv
from accounts_db import get_active_handles, init_db
from models import DB_PATH, init_schema
from ticker_extraction import (
    extract_tickers,
    entropy_band as _entropy_band,
    conviction_size as _conviction_size,
    catalyst_count as _catalyst_count,
)

try:
    from redhood_regime_detector import RegimeDetector
    _REGIME_AVAILABLE = True
except ImportError:
    _REGIME_AVAILABLE = False

load_dotenv()  # loads .env from project root if present

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Centralized configuration for API keys and feed sources"""

    # API Keys (set via environment variables)
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')

    # Feed Sources (customize these!)
    TWITTER_ACCOUNTS = [
        'unusual_whales',
        'FirstSquawk',
        'AutismCapital',
        'Mayhem4Markets',
        'BasedBiohacker',
        'financialjuice',
    ]

    # Nitter instances to try in order (free, no API key required)
    NITTER_INSTANCES = [
        'nitter.poast.org',
        'nitter.privacydev.net',
        'nitter.net',
    ]

    SUBSTACK_FEEDS = [
        'https://arbitrageandy.substack.com/feed',
        'https://doomberg.substack.com/feed',
        'https://noahpinion.substack.com/feed'
    ]

    # AI Configuration
    CLAUDE_MODEL = 'claude-opus-4-8'
    MAX_FEEDS_TO_PROCESS = 50  # Limit for cost control

    # Output
    OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')


# ============================================================================
# DATA MODELS
# ============================================================================

class FeedItem:
    """Represents a single feed item from any source"""

    def __init__(self, source: str, author: str, content: str,
                 timestamp: datetime, url: str = None, metadata: dict = None):
        self.id = f"{source}_{author}_{int(timestamp.timestamp())}"
        self.source = source
        self.author = author
        self.content = content
        self.timestamp = timestamp
        self.url = url
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'source': self.source,
            'author': self.author,
            'content': self.content,
            'timestamp': self.timestamp.isoformat(),
            'url': self.url,
            'metadata': self.metadata
        }

    def __repr__(self):
        return f"FeedItem({self.source}, {self.author}, {self.timestamp})"


class Narrative:
    """Represents an AI-extracted market narrative"""

    def __init__(self, title: str, entropy_risk: int, hypothesis: str,
                 rationale: str, catalysts: list[str], supporting_feeds: list[str],
                 bear_case: str = '', disconfirming_signals: list[str] = None,
                 conviction_adjustment: str = ''):
        self.id = f"narrative_{int(time.time())}_{id(self)}"
        self.date = datetime.now()
        self.title = title
        self.entropy_risk = entropy_risk  # 1-10 scale
        self.hypothesis = hypothesis
        self.rationale = rationale
        self.catalysts = catalysts
        self.supporting_feeds = supporting_feeds
        self.bear_case = bear_case
        self.disconfirming_signals = disconfirming_signals or []
        self.conviction_adjustment = conviction_adjustment

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'title': self.title,
            'entropy_risk': self.entropy_risk,
            'hypothesis': self.hypothesis,
            'rationale': self.rationale,
            'catalysts': self.catalysts,
            'supporting_feeds': self.supporting_feeds,
            'bear_case': self.bear_case,
            'disconfirming_signals': self.disconfirming_signals,
            'conviction_adjustment': self.conviction_adjustment,
        }


# ============================================================================
# FEED SCRAPERS
# ============================================================================

class RSSFeedScraper:
    """Scraper for Substack and other RSS feeds"""

    @staticmethod
    def fetch(feed_urls: list[str], hours_back: float = 24) -> list[FeedItem]:
        """Fetch recent posts from RSS feeds"""
        items = []
        cutoff_time = datetime.now() - timedelta(hours=hours_back)

        for feed_url in feed_urls:
            try:
                feed = feedparser.parse(feed_url)
                source_name = feed.feed.get('title', 'Unknown RSS')

                for entry in feed.entries[:10]:  # Limit to 10 most recent
                    pub_date = datetime(*entry.published_parsed[:6])

                    if pub_date < cutoff_time:
                        continue

                    item = FeedItem(
                        source='rss',
                        author=source_name,
                        content=entry.get('summary', entry.get('title', '')),
                        timestamp=pub_date,
                        url=entry.get('link'),
                        metadata={'feed_url': feed_url}
                    )
                    items.append(item)

            except Exception as e:
                print(f"Error fetching RSS {feed_url}: {e}")

        return items


class NitterScraper:
    """Scraper for X/Twitter via Nitter RSS (no API key required)"""

    def __init__(self, instances: list[str]):
        self.instances = instances

    def _rss_url(self, instance: str, account: str) -> str:
        return f"https://{instance}/{account}/rss"

    def fetch(self, accounts: list[str], hours_back: float = 24) -> list[FeedItem]:
        """Fetch recent tweets via Nitter RSS, trying each instance per account."""
        items = []
        cutoff_time = datetime.now() - timedelta(hours=hours_back)

        for account in accounts:
            fetched = False
            for instance in self.instances:
                url = self._rss_url(instance, account)
                try:
                    feed = feedparser.parse(url)
                    if feed.bozo and not feed.entries:
                        continue
                    for entry in feed.entries[:20]:
                        if not entry.get('published_parsed'):
                            continue
                        pub_date = datetime(*entry.published_parsed[:6])
                        if pub_date < cutoff_time:
                            continue
                        # Nitter links point back to nitter; rewrite to x.com
                        link = entry.get('link', '')
                        link = link.replace(f'https://{instance}', 'https://x.com')
                        item = FeedItem(
                            source='twitter',
                            author=f"@{account}",
                            content=entry.get('summary', entry.get('title', '')),
                            timestamp=pub_date,
                            url=link,
                            metadata={'nitter_instance': instance}
                        )
                        items.append(item)
                    fetched = True
                    break
                except Exception as e:
                    print(f"   Nitter instance {instance} failed for @{account}: {e}")

            if not fetched:
                print(f"⚠️  Could not fetch @{account} from any Nitter instance")

        return items


# ============================================================================
# AI ANALYSIS ENGINE
# ============================================================================

class NarrativeExtractor:
    """Uses Claude AI to extract market narratives from feeds"""

    def __init__(self, api_key: str):
        self.client = Anthropic(api_key=api_key)
        self.model = Config.CLAUDE_MODEL

    def extract_narratives(self, feeds: list[FeedItem], max_feeds: int = 50, regime_context: str = '') -> list[Narrative]:
        """
        Process feeds through Claude to extract top narratives

        Args:
            feeds: List of FeedItem objects
            max_feeds: Maximum number of feeds to process (cost control)
            regime_context: Optional thermodynamic regime string to include in prompt

        Returns:
            List of Narrative objects
        """

        # Limit feeds for cost control
        feeds_to_process = feeds[:max_feeds]

        # Format feeds for prompt
        feeds_text = self._format_feeds_for_prompt(feeds_to_process)

        # Build prompt
        prompt = self._build_extraction_prompt(feeds_text, regime_context)

        # Call Claude API
        try:
            print(f"🤖 Analyzing {len(feeds_to_process)} feeds with Claude...")

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            # Parse response
            response_text = response.content[0].text
            narratives = self._parse_claude_response(response_text, feeds_to_process)

            print(f"✅ Extracted {len(narratives)} narratives")

            # Second pass: adversarial stress-test
            if narratives:
                print("🔴 Running adversarial stress-test...")
                narratives = self._stress_test_narratives(narratives)

            return narratives

        except Exception as e:
            print(f"❌ Error calling Claude API: {e}")
            return []

    def _format_feeds_for_prompt(self, feeds: list[FeedItem]) -> str:
        """Format feeds into readable text for Claude"""

        formatted = []
        for i, feed in enumerate(feeds, 1):
            formatted.append(
                f"[{i}] {feed.source.upper()} | {feed.author} | "
                f"{feed.timestamp.strftime('%Y-%m-%d %H:%M')}\n"
                f"{feed.content[:300]}...\n"
            )

        return "\n".join(formatted)

    def _build_extraction_prompt(self, feeds_text: str, regime_context: str = '') -> str:
        """Build the prompt for Claude"""
        regime_section = (
            f'\nCURRENT MARKET REGIME (thermodynamic): {regime_context}\n'
            'Calibrate entropy risk scoring and position sizing recommendations to this regime.\n'
            'In CRISIS regime, flag all hypotheses as high-risk. In TRENDING, amplify high-conviction ideas.\n'
        ) if regime_context else ''

        return f"""You are a portfolio manager with a physics PhD analyzing market intelligence feeds.
{regime_section}
Your task: Extract the top 5 market narratives from these feeds and generate actionable trade hypotheses.

FEEDS:
{feeds_text}

ANALYSIS FRAMEWORK:
1. Identify the 5 most significant narratives (themes repeated across multiple sources)
2. If any feeds reference Canada — trade policy, tariffs, CAD/USD, Canadian equities, energy, housing, or Canada-US geopolitics — dedicate one narrative specifically to that Canadian angle. If no Canadian content is present, use your best judgement on the 5th narrative.
3. Score "entropy risk" for each narrative (1-10 scale):
   - Low (1-3): Stable consensus, low uncertainty
   - Medium (4-7): Mixed signals, moderate debate
   - High (8-10): Conflicting information, high volatility potential
4. Generate a trade hypothesis for each narrative with:
   - Entry logic (why this trade, why now?)
   - Risk parameters (position size, stop loss)
   - Expected catalysts (upcoming events that could move the market)
5. Use physics analogies where helpful (entropy, momentum, phase transitions, etc.)

OUTPUT FORMAT (strict JSON):
{{
  "narratives": [
    {{
      "title": "Narrative title (5-8 words)",
      "entropy_risk": 1-10,
      "hypothesis": "Specific trade idea (e.g., 'Long QQQ calls, short XLE')",
      "rationale": "Why this trade makes sense given the narrative (2-3 sentences)",
      "catalysts": ["Upcoming event 1", "Data release 2"],
      "supporting_feed_indices": [1, 3, 5]
    }}
  ]
}}

IMPORTANT:
- Return ONLY valid JSON, no markdown formatting
- Include exactly 5 narratives
- Be specific with trade ideas (not just "buy tech")
- Entropy scoring should reflect information quality/consensus level"""

    def _build_adversarial_prompt(self, narratives: list['Narrative']) -> str:
        """Build the adversarial stress-test prompt from extracted narratives"""
        narr_text = ''
        for i, n in enumerate(narratives, 1):
            narr_text += (
                f"NARRATIVE {i}: {n.title}\n"
                f"Hypothesis: {n.hypothesis}\n"
                f"Rationale: {n.rationale}\n"
                f"Catalysts: {', '.join(n.catalysts)}\n"
                f"Entropy Risk: {n.entropy_risk}/10\n\n"
            )

        return f"""You are a skeptical short-seller and risk manager stress-testing trade ideas.

For each narrative below, produce the strongest case AGAINST the trade. Your job is honest pushback, not validation.

NARRATIVES TO STRESS-TEST:
{narr_text}
For each narrative produce:
1. bear_case: The single most compelling reason this trade fails (2-3 sentences). Be specific — cite crowded positioning, structural headwinds, or catalysts that could invalidate the thesis.
2. disconfirming_signals: 2-3 concrete data points or events that would signal the narrative is breaking down.
3. conviction_adjustment: One of "Full Size", "Half Size", "Quarter Size", or "Pass" — followed by a one-sentence rationale weighing bear-case severity against the original thesis.

OUTPUT FORMAT (strict JSON):
{{
  "stress_tests": [
    {{
      "narrative_title": "exact title from above",
      "bear_case": "...",
      "disconfirming_signals": ["signal 1", "signal 2"],
      "conviction_adjustment": "Half Size — because..."
    }}
  ]
}}

IMPORTANT:
- Return ONLY valid JSON, no markdown formatting
- Match narrative_title exactly to the titles provided above
- conviction_adjustment must start with one of: Full Size / Half Size / Quarter Size / Pass"""

    def _stress_test_narratives(self, narratives: list['Narrative']) -> list['Narrative']:
        """Second Claude pass: adversarial stress-test of each narrative."""
        prompt = self._build_adversarial_prompt(narratives)
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )
            response_text = response.content[0].text

            if response_text.strip().startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]

            data = json.loads(response_text.strip())
            stress_map = {
                s['narrative_title']: s
                for s in data.get('stress_tests', [])
            }

            for narrative in narratives:
                st = stress_map.get(narrative.title, {})
                narrative.bear_case = st.get('bear_case', '')
                narrative.disconfirming_signals = st.get('disconfirming_signals', [])
                narrative.conviction_adjustment = st.get('conviction_adjustment', '')

            print("🔴 Adversarial stress-test complete")
        except Exception as e:
            print(f"⚠️  Stress-test pass failed: {e}")

        return narratives

    def _parse_claude_response(self, response_text: str, feeds: list[FeedItem]) -> list[Narrative]:
        """Parse Claude's JSON response into Narrative objects"""

        try:
            # Remove markdown code blocks if present
            if response_text.strip().startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]

            data = json.loads(response_text.strip())
            narratives = []

            for n in data.get('narratives', []):
                # Map feed indices to feed IDs
                supporting_feeds = [
                    feeds[i-1].id for i in n.get('supporting_feed_indices', [])
                    if 0 < i <= len(feeds)
                ]

                narrative = Narrative(
                    title=n['title'],
                    entropy_risk=n['entropy_risk'],
                    hypothesis=n['hypothesis'],
                    rationale=n['rationale'],
                    catalysts=n.get('catalysts', []),
                    supporting_feeds=supporting_feeds
                )
                narratives.append(narrative)

            return narratives

        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse Claude response as JSON: {e}")
            print(f"Response was: {response_text[:500]}...")
            return []
        except Exception as e:
            print(f"❌ Error parsing response: {e}")
            return []


# ============================================================================
# GITHUB PAGES PUBLISHER
# ============================================================================

class GitHubPagesPublisher:
    """Publishes RedHood Reads HTML reports to GitHub Pages via the Contents API."""

    OWNER     = "tazeemc"
    REPO      = "Redhood-Systems"
    BRANCH    = "main"
    DOCS_PATH = "docs"
    BASE_URL  = "https://tazeemc.github.io/Redhood-Systems"

    def __init__(self, token: str):
        self._headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "RedHood-Systems",
        }

    def _get_sha(self, path: str):
        """Return current blob SHA for a file (needed to update existing files)."""
        url = (f"https://api.github.com/repos/{self.OWNER}/{self.REPO}"
               f"/contents/{path}?ref={self.BRANCH}")
        req = urllib.request.Request(url, headers=self._headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read()).get("sha")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def _put_file(self, path: str, content: str, message: str, sha=None):
        """Create or update a file via the GitHub Contents API."""
        url = (f"https://api.github.com/repos/{self.OWNER}/{self.REPO}"
               f"/contents/{path}")
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode(),
            "branch": self.BRANCH,
        }
        if sha:
            body["sha"] = sha
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={**self._headers, "Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

    def publish(self, html_path: str) -> str:
        """
        Push html_path to docs/ on GitHub Pages.

        Publishes two files:
          - docs/redhood_reads_TIMESTAMP.html  (permanent archive URL)
          - docs/latest.html                   (stable link, always current)

        Returns the permanent archive URL.
        """
        filename = os.path.basename(html_path)
        with open(html_path, encoding="utf-8") as f:
            html = f.read()
        ts  = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
        msg = f"Auto-publish RedHood Reads {ts}"

        archive_path = f"{self.DOCS_PATH}/{filename}"
        self._put_file(archive_path, html, msg, self._get_sha(archive_path))

        latest_path = f"{self.DOCS_PATH}/latest.html"
        self._put_file(latest_path, html, f"Update latest {ts}", self._get_sha(latest_path))

        return f"{self.BASE_URL}/{filename}"


# ============================================================================
# MAIN AGGREGATOR
# ============================================================================

class RedHoodAggregator:
    """Main orchestrator for feed aggregation and analysis"""

    def __init__(self):
        self.config = Config()
        init_schema()  # ensure all tables exist (runs, feeds, narratives, etc.)
        init_db()      # seed default twitter accounts if not present

        # Initialize scrapers
        self.rss_scraper = RSSFeedScraper()
        self.twitter_scraper = NitterScraper(self.config.NITTER_INSTANCES)

        # Initialize AI engine
        self.ai_engine = NarrativeExtractor(self.config.ANTHROPIC_API_KEY)

        # Ensure output directory exists
        os.makedirs(self.config.OUTPUT_DIR, exist_ok=True)

    def _compute_regime(self):
        """Fetch 3-month SPY closes from Yahoo Finance and compute regime state."""
        try:
            import pandas as pd
            url = ('https://query1.finance.yahoo.com/v8/finance/chart/'
                   'SPY?interval=1d&range=3mo')
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            closes = data['chart']['result'][0]['indicators']['quote'][0]['close']
            prices = pd.Series([c for c in closes if c is not None])
            if len(prices) < 25:
                return None
            detector = RegimeDetector(base_temp=0.15, base_entropy=2.5, window=20)
            return detector.update(prices)
        except Exception as e:
            print(f"   ⚠️  Regime detection failed: {e}")
            return None

    def run(self, hours_back: float = 24, trading_json: str = None) -> dict[str, Any]:
        """
        Run full aggregation and analysis pipeline

        Returns:
            Dictionary with feeds and narratives
        """

        print("=" * 60)
        print("🔥 REDHOOD SYSTEMS - Feed Aggregator")
        print("=" * 60)
        print(f"📅 Fetching feeds from last {hours_back} hours...\n")

        # Fetch from all sources
        all_feeds = []

        print("📰 Fetching RSS feeds...")
        rss_feeds = self.rss_scraper.fetch(self.config.SUBSTACK_FEEDS, hours_back)
        all_feeds.extend(rss_feeds)
        print(f"   ✅ Found {len(rss_feeds)} RSS items\n")

        print("🐦 Fetching Twitter feeds...")
        accounts = get_active_handles() or self.config.TWITTER_ACCOUNTS
        print(f"   📋 Active accounts from DB: {', '.join('@' + a for a in accounts)}")
        twitter_feeds = self.twitter_scraper.fetch(accounts, hours_back)
        all_feeds.extend(twitter_feeds)
        print(f"   ✅ Found {len(twitter_feeds)} tweets\n")

        print(f"📊 Total feeds collected: {len(all_feeds)}\n")

        if not all_feeds:
            print("⚠️  No feeds found. Check your API keys and feed URLs.")
            return {'feeds': [], 'narratives': []}

        # Sort by timestamp (most recent first)
        all_feeds.sort(key=lambda x: x.timestamp, reverse=True)

        # Thermodynamic regime detection
        regime_state = None
        regime_context = ''
        if _REGIME_AVAILABLE:
            print("🌡️  Computing thermodynamic regime (SPY)...")
            regime_state = self._compute_regime()
            if regime_state:
                label = regime_state.label.value
                print(f"   Regime: {label} | T={regime_state.temperature:.1%} | "
                      f"S={regime_state.entropy:.3f} | Mult={regime_state.signal_multiplier:.2f}×"
                      + (" | ⚠ REGIME DRIFT" if regime_state.warning else ""))
                regime_context = (
                    f"Regime={label} | Temperature={regime_state.temperature:.1%} (base 15%) | "
                    f"Entropy={regime_state.entropy:.3f} (base 2.5) | "
                    f"Signal Multiplier={regime_state.signal_multiplier:.2f}× | "
                    f"KL Divergence={regime_state.kl_divergence:.4f}"
                    + (" | ⚠ REGIME DRIFT ALERT" if regime_state.warning else "")
                )
            print()

        # Extract narratives using AI
        print("🧠 AI Analysis Phase...\n")
        narratives = self.ai_engine.extract_narratives(
            all_feeds,
            max_feeds=self.config.MAX_FEEDS_TO_PROCESS,
            regime_context=regime_context,
        )

        # Save results
        results = {
            'timestamp': datetime.now().isoformat(),
            'feeds': [f.to_dict() for f in all_feeds],
            'narratives': [n.to_dict() for n in narratives]
        }

        json_path, html_path = self._save_results(results, narratives, hours_back, trading_json, regime_state)
        self._persist_to_db(hours_back, all_feeds, narratives, json_path, html_path)

        github_token = os.getenv("GITHUB_TOKEN")
        if github_token:
            try:
                pub_url = GitHubPagesPublisher(github_token).publish(html_path)
                print(f"\n🌐 [GitHub Pages] Published:  {pub_url}")
                print(f"🌐 [GitHub Pages] Latest URL: {GitHubPagesPublisher.BASE_URL}/latest.html")
            except Exception as e:
                print(f"\n⚠️  [GitHub Pages] Publish failed: {e}")

        # Reload trading data for terminal display
        trading_data_for_print = []
        if trading_json and os.path.exists(trading_json):
            try:
                with open(trading_json, encoding='utf-8-sig') as f:
                    raw = json.load(f)
                trading_data_for_print = raw if isinstance(raw, list) else [raw]
            except Exception:
                pass
        self._print_summary(narratives, trading_data_for_print)

        return results

    def _save_results(self, results: dict[str, Any],
                      narratives: list[Narrative], hours_back: float,
                      trading_json: str = None, regime_state=None):
        """Save results to JSON and HTML report. Returns (json_path, html_path)."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        json_path = os.path.join(self.config.OUTPUT_DIR,
                                 f'redhood_insights_{timestamp}.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        print(f"\n💾 Results saved to: {json_path}")

        # Load trading data if provided
        trading_data = []
        if trading_json and os.path.exists(trading_json):
            try:
                with open(trading_json, encoding='utf-8-sig') as f:
                    raw = json.load(f)
                trading_data = raw if isinstance(raw, list) else [raw]
            except Exception as e:
                print(f"⚠️  Could not load trading JSON: {e}")

        html_path = os.path.join(self.config.OUTPUT_DIR,
                                 f'redhood_reads_{timestamp}.html')
        self._save_html_report(results, narratives, html_path, timestamp,
                               hours_back, trading_data, regime_state)
        print(f"📰 Report saved to:   {html_path}")

        return json_path, html_path

    @staticmethod
    def _fetch_ticker_prices() -> str:
        """Fetch live prices from Yahoo Finance and return ticker tape HTML (doubled for loop)."""
        TICKERS = [
            ('BTC/USD',  'BTC-USD',   '{:,.0f}',  '$'),
            ('S&P 500',  '^GSPC',     '{:,.0f}',  ''),
            ('WTI',      'CL=F',      '{:.2f}',   '$'),
            ('GOLD',     'GC=F',      '{:,.0f}',  '$'),
            ('VIX',      '^VIX',      '{:.2f}',   ''),
            ('10YR UST', '^TNX',      '{:.3f}',   ''),
            ('USD/CAD',  'USDCAD=X',  '{:.4f}',   ''),
        ]
        items = []
        for label, symbol, fmt, prefix in TICKERS:
            try:
                url = (f'https://query1.finance.yahoo.com/v8/finance/chart/'
                       f'{urllib.request.quote(symbol)}?interval=1d&range=2d')
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                meta = data['chart']['result'][0]['meta']
                price = meta.get('regularMarketPrice') or meta.get('previousClose', 0)
                prev  = meta.get('previousClose') or price
                chg   = ((price - prev) / prev * 100) if prev else 0
                val_str = prefix + fmt.format(price)
                chg_str = f'{chg:+.2f}%'
                css = 'up' if chg >= 0 else 'down'
                items.append(
                    f'<span class="tick-item">'
                    f'<span class="tick-sym">{label}</span>'
                    f'<span class="tick-val {css}">{val_str}</span>'
                    f'<span class="tick-chg {css}">{chg_str}</span>'
                    f'</span>'
                )
            except Exception:
                items.append(
                    f'<span class="tick-item">'
                    f'<span class="tick-sym">{label}</span>'
                    f'<span class="tick-val">—</span>'
                    f'</span>'
                )
        tape = '\n    '.join(items)
        return tape + '\n    ' + tape  # duplicate for seamless loop

    def _save_html_report(self, results: dict[str, Any], narratives: list[Narrative],
                          filepath: str, timestamp: str, hours_back: float,
                          trading_data: list = None, regime_state=None):
        """Generate styled RedHood Reads HTML report from run data."""
        import html as H

        dt = datetime.strptime(timestamp, '%Y%m%d_%H%M%S')
        run_date_full = dt.strftime('%A, %d %B %Y')
        week_num = dt.isocalendar()[1]
        run_time_short = dt.strftime('%Y-%m-%d %H:%M')

        twitter_feeds = [f for f in results['feeds']
                         if f['source'] == 'twitter' and f.get('url')]
        feed_count = len(twitter_feeds)
        window_label = (f"{int(hours_back * 60)}m window"
                        if hours_back < 1 else f"{hours_back:.1f}h window")

        narrs = list(narratives[:5]) + [None] * max(0, 5 - len(narratives))
        top = narrs[0]

        def ecolor(s):
            return '#C1121F' if s >= 8 else '#B8975A' if s >= 5 else '#4CAF50'

        def elabel(s):
            return 'HIGH' if s >= 8 else 'MEDIUM' if s >= 5 else 'LOW'

        def dclass(s):
            return 'dn' if s >= 8 else 'neutral' if s >= 5 else 'up'

        def sparkline(entropy):
            if entropy >= 8:
                bars = [(20,'lo'),(45,'lo'),(30,'lo'),(80,'hi'),(55,'mid-hi'),(90,'hi'),(100,'hi')]
            elif entropy >= 5:
                bars = [(60,'mid-hi'),(45,'lo'),(70,'mid-hi'),(55,'mid-hi'),(80,'hi'),(65,'mid-hi'),(75,'hi')]
            else:
                bars = [(90,'hi'),(80,'hi'),(70,'hi'),(60,'mid-hi'),(50,'mid-hi'),(40,'lo'),(35,'lo')]
            return ('<div class="sparkline">'
                    + ''.join(f'<div class="bar {c}" style="height:{h}%"></div>' for h, c in bars)
                    + '</div>')

        col_tags = ['Intelligence', 'Market Signal', 'Macro View', 'Geopolitical', 'Canada / FX']

        def grid_col(narr, idx):
            if narr is None:
                return '<div class="grid-col"><div class="col-tag">—</div></div>'
            tag = H.escape(f'{col_tags[idx]} · Risk {narr.entropy_risk}/10')
            title = H.escape(narr.title)
            body = H.escape(narr.hypothesis[:240] + ('…' if len(narr.hypothesis) > 240 else ''))
            bear = H.escape(narr.bear_case[:200] + ('…' if len(narr.bear_case) > 200 else '')) if narr.bear_case else ''
            conviction = H.escape(narr.conviction_adjustment) if narr.conviction_adjustment else ''
            bear_html = (
                f'<div class="bear-label">Bear Case</div>'
                f'<div class="bear-body">{bear}</div>'
                f'<div class="conviction-tag">{conviction}</div>'
            ) if bear else ''
            return (f'<div class="grid-col">'
                    f'<div class="col-tag">{tag}</div>'
                    f'<div class="col-title">{title}</div>'
                    f'<div class="col-body">{body}</div>'
                    f'{sparkline(narr.entropy_risk)}'
                    f'{bear_html}</div>')

        # Metrics: feeds + 3 narrative entropy scores + narrative count
        metric_blocks = []
        metric_blocks.append(
            f'<div class="metric"><div class="metric-label">Feeds Collected</div>'
            f'<div class="metric-val">{feed_count}</div>'
            f'<div class="metric-delta neutral">{window_label}</div></div>'
        )
        for narr in narrs:
            if narr is None:
                metric_blocks.append('<div class="metric"><div class="metric-label">—</div></div>')
            else:
                short = H.escape(narr.title[:26] + ('…' if len(narr.title) > 26 else ''))
                metric_blocks.append(
                    f'<div class="metric"><div class="metric-label">{short}</div>'
                    f'<div class="metric-val" style="color:{ecolor(narr.entropy_risk)}">'
                    f'{narr.entropy_risk}/10</div>'
                    f'<div class="metric-delta {dclass(narr.entropy_risk)}">'
                    f'{elabel(narr.entropy_risk)} entropy</div></div>'
                )
        metric_blocks.append(
            f'<div class="metric"><div class="metric-label">Narratives</div>'
            f'<div class="metric-val">{len(narratives)}</div>'
            f'<div class="metric-delta neutral">Extracted</div></div>'
        )
        metrics_html = '\n'.join(metric_blocks[:7])

        headline = H.escape(top.title) if top else 'Market Intelligence Brief'
        deck = H.escape((top.rationale[:240] + '…') if top and len(top.rationale) > 240
                        else (top.rationale if top else ''))
        thought_q = H.escape(top.hypothesis) if top else ''
        thought_body = H.escape(', '.join(top.catalysts)) if top else ''
        thought_bear = H.escape(top.bear_case) if top and top.bear_case else ''
        thought_conviction = H.escape(top.conviction_adjustment) if top and top.conviction_adjustment else ''
        grid_html = '\n'.join(grid_col(n, i) for i, n in enumerate(narrs))

        # ---- Signal cards: narrative-cited tweets ∪ top-N most recent ----
        # Self-contained "trade reference" cards — no external X widget, so the
        # report renders fully offline and identically every time. Tweets cited
        # as supporting evidence by a narrative are always carded and flagged.
        import re as _re
        EMBED_LIMIT = 55

        def _tweet_text(s, limit=280):
            t = _re.sub(r'<[^>]+>', ' ', s or '')   # strip Nitter HTML
            t = H.unescape(t)
            t = _re.sub(r'\s+', ' ', t).strip()
            return t[:limit] + ('…' if len(t) > limit else '')

        cited_ids = set()
        for _n in narratives:
            cited_ids.update(getattr(_n, 'supporting_feeds', None) or [])

        def _tweet_card(i, f):
            handle = f['author'].lstrip('@')
            ts     = f['timestamp'][:16].replace('T', ' ')
            text   = H.escape(_tweet_text(f.get('content', '')))
            url    = H.escape(f.get('url', ''))
            cited  = f.get('id') in cited_ids
            badge  = '<span class="tw-cited">&#9670; CITED</span>' if cited else ''
            cls    = 'tw-card tw-card-cited' if cited else 'tw-card'
            # data-* attributes drive the client-side command bar (search/filter/sort)
            search = H.escape(('@' + handle + ' ' + _tweet_text(f.get('content', ''), 10000)).lower())
            return (f'<div class="tweet-embed" id="feed-{i}" data-handle="{H.escape(handle.lower())}" '
                    f'data-cited="{"1" if cited else "0"}" data-ts="{H.escape(f.get("timestamp",""))}" '
                    f'data-search="{search}"><div class="{cls}">'
                    f'<div class="tw-head"><span class="tw-handle">@{handle}</span>'
                    f'<span class="tw-meta">{badge}<span class="tw-ts">{ts}</span></span></div>'
                    f'<div class="tw-body">{text}</div>'
                    f'<a class="tw-link" href="{url}" target="_blank">View on X &rarr;</a>'
                    f'</div></div>')

        # Card a tweet if it's within the top-N recent OR cited by a narrative.
        embed_cards, rest = [], []
        for i, f in enumerate(twitter_feeds, 1):
            if i <= EMBED_LIMIT or f.get('id') in cited_ids:
                embed_cards.append(_tweet_card(i, f))
            else:
                rest.append((i, f))
        embeds_html = '\n'.join(embed_cards)
        embed_count = len(embed_cards)
        cited_count = sum(1 for f in twitter_feeds if f.get('id') in cited_ids)

        # Un-carded tweets stay as a compact links table so synopsis "feed N"
        # anchors beyond the card set still resolve.
        if rest:
            rest_rows = ''.join(
                f'<tr id="feed-{i}"><td class="feed-num">{i}</td>'
                f'<td class="ts">{f["timestamp"][:16].replace("T"," ")}</td>'
                f'<td class="author">{H.escape(f["author"])}</td>'
                f'<td><a href="{H.escape(f["url"])}" target="_blank">{H.escape(f["url"])}</a></td></tr>'
                for i, f in rest
            )
            links_section_html = (
                '<details class="links-section sec">'
                '<summary class="sec-summary">'
                f'<span class="links-header">Additional Signal Links &mdash; '
                f'{len(rest)} more &middot; {run_time_short}</span>'
                '<span class="sec-chevron">&#9662;</span></summary>'
                '<table class="links-table">'
                '<thead><tr><th>#</th><th>Timestamp</th><th>Account</th><th>Link</th></tr></thead>'
                f'<tbody>{rest_rows}</tbody></table></details>'
            )
        else:
            links_section_html = ''

        ticker_html = self._fetch_ticker_prices()

        # ---- Trading signal panel ----
        trading_html = ''
        if trading_data:
            def rec_css(r):
                return 'rec-in' if r == 'IN' else 'rec-out' if r == 'OUT' else 'rec-neutral'

            def trend_arrow(t):
                return '&#9650;' if t == 'UP' else '&#9660;'

            def trend_css(t):
                return 'up' if t == 'UP' else 'down'

            cards = []
            for s in trading_data:
                sym    = H.escape(str(s.get('Symbol', '—')))
                price  = H.escape(str(s.get('Price', '—')))
                rec    = str(s.get('Recommendation', 'NEUTRAL')).upper()
                ent_sig = str(s.get('EntropySignal', 'NEUTRAL')).upper()
                prc_sig = str(s.get('PriceSignal', 'NEUTRAL')).upper()
                trend  = str(s.get('Trend', '—')).upper()
                mom    = s.get('Momentum', 0) or 0
                rsi    = s.get('RSI', 0) or 0
                temp   = s.get('Temperature', 0) or 0
                t_stat = H.escape(str(s.get('TempStatus', '—')))
                entr   = s.get('Entropy', 0) or 0
                e_stat = H.escape(str(s.get('EntropyStatus', '—')))
                pos    = s.get('PositionSize', 0) or 0
                ma20   = s.get('MA20', 0) or 0
                ma50   = s.get('MA50', 0) or 0
                ts_raw = H.escape(str(s.get('Timestamp', '')))

                # Format price nicely
                try:
                    p_val = float(str(price).replace(',','').replace('$',''))
                    price_fmt = f'${p_val:,.0f}' if p_val > 999 else f'${p_val:,.2f}'
                except Exception:
                    price_fmt = price

                mom_sign = '+' if mom >= 0 else ''
                mom_css  = 'up' if mom >= 0 else 'down'

                cards.append(
                    f'<div class="tc-card">'
                    f'<div class="tc-header">'
                    f'<span class="tc-sym">{sym}</span>'
                    f'<span class="tc-rec {rec_css(rec)}">{rec}</span>'
                    f'</div>'
                    f'<div class="tc-price">{price_fmt}'
                    f'<span class="tc-trend {trend_css(trend)}">'
                    f'{trend_arrow(trend)} {trend}</span></div>'
                    f'<div class="tc-row"><span class="tc-lbl">Entropy Signal</span>'
                    f'<span class="tc-val"><span class="tc-rec {rec_css(ent_sig)}">{ent_sig}</span></span></div>'
                    f'<div class="tc-row"><span class="tc-lbl">Price Signal</span>'
                    f'<span class="tc-val"><span class="tc-rec {rec_css(prc_sig)}">{prc_sig}</span></span></div>'
                    f'<div class="tc-row"><span class="tc-lbl">Momentum</span>'
                    f'<span class="tc-val {mom_css}">{mom_sign}{mom:.2f}%</span></div>'
                    f'<div class="tc-row"><span class="tc-lbl">RSI</span>'
                    f'<span class="tc-val">{rsi:.1f}</span></div>'
                    f'<div class="tc-row"><span class="tc-lbl">Temperature</span>'
                    f'<span class="tc-val">{temp:.2f} <span class="tc-badge">{t_stat}</span></span></div>'
                    f'<div class="tc-row"><span class="tc-lbl">Entropy</span>'
                    f'<span class="tc-val">{entr:.3f} <span class="tc-badge">{e_stat}</span></span></div>'
                    f'<div class="tc-row"><span class="tc-lbl">MA20 / MA50</span>'
                    f'<span class="tc-val">${ma20:,.2f} / ${ma50:,.2f}</span></div>'
                    f'<div class="tc-row"><span class="tc-lbl">Position Size</span>'
                    f'<span class="tc-val">${pos:,.0f}</span></div>'
                    f'<div class="tc-ts">{ts_raw}</div>'
                    f'</div>'
                )

            cards_html = '\n'.join(cards)
            trading_html = (
                f'<div class="trading-section">'
                f'<div class="trading-label">Quantitative Signal Analysis</div>'
                f'<div class="trading-grid">{cards_html}</div>'
                f'</div>'
            )

        # ---- BBC-style synopsis ----
        bbc_paras = []
        if narratives:
            n1 = narratives[0]
            lede = (n1.rationale if n1.rationale else n1.hypothesis)
            if lede:
                bbc_paras.append(H.escape(lede))

            if len(narratives) >= 2:
                n2 = narratives[1]
                p2 = n2.hypothesis or ''
                cats = [c for c in (n2.catalysts or []) if c][:2]
                if cats:
                    p2 += f" Market participants are closely monitoring {', '.join(c.lower() for c in cats)}."
                if p2.strip():
                    bbc_paras.append(H.escape(p2.strip()))

            bears = [n.bear_case for n in narratives[:5] if n.bear_case]
            if bears:
                bbc_paras.append(H.escape(
                    f"However, analysts have flagged material downside risks. {bears[0]}"
                ))
            elif len(narratives) >= 3 and narratives[2].hypothesis:
                bbc_paras.append(H.escape(narratives[2].hypothesis))

        if bbc_paras:
            byline = (f"Compiled from {feed_count} signal sources "
                      f"&middot; {run_time_short} &middot; AI-assisted analysis")
            paras_html = ''.join(
                f'<p class="synopsis-para">{p}</p>' for p in bbc_paras
            )
            synopsis_html = (
                f'<div class="synopsis-section">'
                f'<div class="synopsis-label">Market Intelligence Synopsis</div>'
                f'<div class="synopsis-byline">{byline}</div>'
                f'<div class="synopsis-body">{paras_html}</div>'
                f'</div>'
            )
        else:
            synopsis_html = ''

        # Auto-link "feed N" / "feeds N-M" references in synopsis to anchors in the links table
        def _linkify_feeds(text):
            def repl(m):
                word, nums = m.group(1), m.group(2)
                if '-' in nums:
                    a, b = nums.split('-', 1)
                    return (f'{word} <a class="feed-link" href="#feed-{a}">{a}</a>'
                            f'-<a class="feed-link" href="#feed-{b}">{b}</a>')
                return f'<a class="feed-link" href="#feed-{nums}">{word} {nums}</a>'
            return _re.sub(r'\b(feeds?)\s+(\d+(?:-\d+)?)\b', repl, text, flags=_re.IGNORECASE)
        synopsis_html = _linkify_feeds(synopsis_html)

        # Regime panel
        regime_panel_html = ''
        if regime_state:
            _REGIME_COLORS = {
                'TRENDING':   ('#00e5a0', 'Low T &middot; Low S &mdash; amplify signals'),
                'CHOPPY':     ('#f5a623', 'High T &middot; Low S &mdash; reduce size'),
                'CRISIS':     ('#ff4060', 'High T &middot; High S &mdash; block entries'),
                'TRANSITION': ('#7b8cde', 'Low T &middot; High S &mdash; watch closely'),
            }
            rlabel = regime_state.label.value
            rcolor, rdesc = _REGIME_COLORS.get(rlabel, ('#c8d4f0', ''))
            rwarn = ('<span class="regime-warn">&#9888; REGIME DRIFT</span>'
                     if regime_state.warning else '')
            regime_panel_html = (
                f'<div class="regime-panel">'
                f'<div class="regime-panel-label">Thermodynamic Regime &mdash; SPY (20-bar)</div>'
                f'<div class="regime-badge-row">'
                f'<span class="regime-badge" style="color:{rcolor};border-color:{rcolor}40;background:{rcolor}12">{rlabel}</span>'
                f'<span class="regime-desc">{rdesc}</span>'
                f'{rwarn}</div>'
                f'<div class="regime-metrics">'
                f'<div class="rm"><div class="rm-lbl">Temperature</div>'
                f'<div class="rm-val" style="color:{rcolor}">{regime_state.temperature:.1%}</div>'
                f'<div class="rm-sub">base 15%</div></div>'
                f'<div class="rm"><div class="rm-lbl">Entropy</div>'
                f'<div class="rm-val">{regime_state.entropy:.3f}</div>'
                f'<div class="rm-sub">base 2.50</div></div>'
                f'<div class="rm"><div class="rm-lbl">KL Divergence</div>'
                f'<div class="rm-val" style="color:{"#ff9a3c" if regime_state.warning else "#c8d4f0"}">'
                f'{regime_state.kl_divergence:.4f}</div>'
                f'<div class="rm-sub">{"drift detected" if regime_state.warning else "within bounds"}</div></div>'
                f'<div class="rm"><div class="rm-lbl">Signal Mult</div>'
                f'<div class="rm-val">{regime_state.signal_multiplier:.2f}&times;</div>'
                f'<div class="rm-sub">applied to signals</div></div>'
                f'<div class="rm"><div class="rm-lbl">Heat Budget</div>'
                f'<div class="rm-val">{regime_state.heat_budget:.0%}</div>'
                f'<div class="rm-sub">remaining</div></div>'
                f'</div></div>'
            )

        # Tactical posture badge derived from the thermodynamic regime, plus an
        # ISO run-timestamp the client clock uses for the live data-age readout.
        posture_html = ''
        if regime_state:
            _POSTURE = {
                'TRENDING':   ('WEAPONS FREE', '#00e5a0'),
                'CHOPPY':     ('TIGHTENED',    '#f5a623'),
                'CRISIS':     ('WEAPONS HOLD', '#ff4060'),
                'TRANSITION': ('WATCH',        '#7b8cde'),
            }
            plabel, pcolor = _POSTURE.get(regime_state.label.value, ('WATCH', '#c8d4f0'))
            posture_html = (f'<span class="posture-pill" style="color:{pcolor};'
                            f'border-color:{pcolor}55;background:{pcolor}14">'
                            f'POSTURE&nbsp;&middot;&nbsp;{plabel}</span>')
        run_iso = dt.strftime('%Y-%m-%dT%H:%M:%S')

        # Build HTML using string replacement to avoid f-string brace conflicts with CSS
        tpl = self._html_report_template()
        html_out = (tpl
            .replace('%%POSTURE%%',           posture_html)
            .replace('%%RUN_ISO%%',           run_iso)
            .replace('%%TOPBAR_DATE%%',       f'{run_date_full} &nbsp;|&nbsp; Week {week_num:02d}')
            .replace('%%ISSUE_NUM%%',         f'Run &middot; {window_label} &middot; {run_time_short}')
            .replace('%%VOL_NUM%%',           str(dt.strftime('%d')))
            .replace('%%HEADLINE%%',          headline)
            .replace('%%DECK%%',              deck)
            .replace('%%METRICS%%',           metrics_html)
            .replace('%%GRID%%',              grid_html)
            .replace('%%THOUGHT_Q%%',         thought_q)
            .replace('%%THOUGHT_BODY%%',      thought_body)
            .replace('%%THOUGHT_BEAR%%',      thought_bear)
            .replace('%%THOUGHT_CONVICTION%%', thought_conviction)
            .replace('%%TRADING%%',           trading_html)
            .replace('%%SYNOPSIS%%',          synopsis_html)
            .replace('%%REGIME_PANEL%%',      regime_panel_html)
            .replace('%%EMBEDS%%',            embeds_html)
            .replace('%%EMBED_COUNT%%',       str(embed_count))
            .replace('%%CITED_COUNT%%',       str(cited_count))
            .replace('%%LINKS_SECTION%%',     links_section_html)
            .replace('%%FEED_COUNT%%',        str(feed_count))
            .replace('%%RUN_TIME%%',          run_time_short)
            .replace('%%TICKER_HTML%%',       ticker_html)
        )
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_out)

    @staticmethod
    def _html_report_template() -> str:
        """RedHood Reads HTML template with %%TOKEN%% placeholders."""
        return '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RedHood Reads — %%RUN_TIME%%</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700;900&family=IBM+Plex+Mono:wght@300;400;500&family=DM+Serif+Display:ital@0;1&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --red: #C1121F; --red-dim: #8B0D16; --cream: #F5F0E8; --gold: #B8975A;
    --dark: #0A0A0A; --charcoal: #111111; --mid: #1C1C1C;
    --wire: rgba(255,255,255,0.06); --text-muted: rgba(245,240,232,0.45);
    --purple: #7B4FD6; --pink: #E8517A; --tangerine: #F47B3A;
  }
  body { background: var(--dark); font-family: "IBM Plex Mono", monospace; color: var(--cream);
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    padding: 32px 16px; overflow-x: hidden; }
  body::before { content: ""; position: fixed; inset: 0;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.04'/%3E%3C/svg%3E");
    pointer-events: none; z-index: 0; opacity: 0.6; }
  .card { position: relative; width: 100%; max-width: 900px; background: var(--charcoal);
    border: 1px solid rgba(123,79,214,0.3); z-index: 1; overflow: hidden;
    box-shadow: 0 0 40px rgba(123,79,214,0.06), 0 0 80px rgba(232,81,122,0.03); }
  .card::before { content: ""; position: absolute; top: -60px; right: -60px; width: 200px;
    height: 200px; background: linear-gradient(135deg, var(--purple), var(--pink));
    transform: rotate(45deg); opacity: 0.1; }
  .topbar { display: flex; align-items: center; justify-content: space-between;
    padding: 12px 28px; border-bottom: 1px solid rgba(123,79,214,0.15);
    background: rgba(123,79,214,0.04); }
  .topbar-left { display: flex; align-items: center; gap: 12px; }
  .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--pink);
    animation: pulse 2s ease-in-out infinite; }
  @keyframes pulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(232,81,122,0.5); }
    50% { opacity: 0.7; box-shadow: 0 0 0 5px rgba(232,81,122,0); }
  }
  .topbar-label { font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase;
    color: var(--pink); font-weight: 500; }
  .topbar-date { font-size: 9px; letter-spacing: 0.1em; color: var(--text-muted); }
  .ticker-wrap { overflow: hidden; border-bottom: 1px solid var(--wire);
    background: var(--mid); padding: 7px 0; }
  .ticker-inner { display: flex; gap: 0; animation: ticker 28s linear infinite; white-space: nowrap; }
  @keyframes ticker { 0% { transform: translateX(0); } 100% { transform: translateX(-50%); } }
  .tick-item { display: inline-flex; align-items: center; gap: 6px; padding: 0 24px;
    font-size: 9.5px; letter-spacing: 0.08em; border-right: 1px solid var(--wire); }
  .tick-sym { color: var(--tangerine); font-weight: 500; }
  .tick-val { color: var(--cream); }
  .tick-chg { font-size: 8.5px; color: var(--text-muted); }
  .up { color: #4CAF50; } .down { color: var(--red); }
  .hero { padding: 44px 40px 36px; position: relative; border-bottom: 1px solid var(--wire); }
  .issue-line { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; }
  .issue-num { font-size: 9px; letter-spacing: 0.25em; text-transform: uppercase; color: var(--text-muted); }
  .issue-rule { flex: 1; height: 1px; background: linear-gradient(to right, var(--wire), transparent); }
  .masthead { font-family: "Playfair Display", serif; font-weight: 900;
    font-size: clamp(48px, 8vw, 80px); line-height: 0.9; letter-spacing: -0.02em;
    color: var(--cream); margin-bottom: 6px; }
  .masthead .red-accent { color: var(--red); font-style: italic; }
  .sub-masthead { font-family: "IBM Plex Mono", monospace; font-size: 9px; letter-spacing: 0.3em;
    text-transform: uppercase; color: var(--tangerine); margin-bottom: 28px; }
  .headline-block { max-width: 620px; }
  .headline { font-family: "DM Serif Display", serif; font-size: clamp(18px, 3.2vw, 26px);
    line-height: 1.3; color: var(--cream); margin-bottom: 14px; font-style: italic; }
  .deck { font-size: 10.5px; line-height: 1.7; color: var(--text-muted);
    letter-spacing: 0.03em; max-width: 540px; }
  .corner-deco { position: absolute; top: 44px; right: 40px; text-align: right; }
  .corner-deco .vol-label { font-size: 8px; letter-spacing: 0.2em; color: var(--text-muted);
    text-transform: uppercase; }
  .corner-deco .vol-num { font-family: "Playfair Display", serif; font-size: 52px;
    font-weight: 900; color: rgba(123,79,214,0.15); line-height: 1; letter-spacing: -0.04em; }
  .grid-section { display: grid; grid-template-columns: 1fr 1fr 1fr;
    border-bottom: 1px solid var(--wire); }
  .grid-col { padding: 22px 24px; border-right: 1px solid var(--wire); position: relative; }
  .grid-col:last-child { border-right: none; }
  .col-tag { font-size: 7.5px; letter-spacing: 0.25em; text-transform: uppercase;
    color: var(--pink); margin-bottom: 10px; font-weight: 500; }
  .col-title { font-family: "Playfair Display", serif; font-size: 15px; font-weight: 700;
    line-height: 1.25; margin-bottom: 10px; color: var(--cream); }
  .col-body { font-size: 9.5px; line-height: 1.75; color: var(--text-muted); }
  .sparkline { margin-top: 14px; height: 32px; display: flex; align-items: flex-end; gap: 2px; }
  .bar { flex: 1; background: var(--wire); border-radius: 1px; }
  .bar.hi { background: rgba(244,123,58,0.55); }
  .bar.lo { background: rgba(193,18,31,0.5); }
  .bar.mid-hi { background: rgba(232,81,122,0.45); }
  .metrics-strip { display: grid; grid-template-columns: repeat(5, 1fr);
    border-bottom: 1px solid var(--wire); }
  .metric { padding: 16px 20px; border-right: 1px solid var(--wire); position: relative; }
  .metric:last-child { border-right: none; }
  .metric-label { font-size: 7.5px; letter-spacing: 0.2em; text-transform: uppercase;
    color: var(--text-muted); margin-bottom: 5px; }
  .metric-val { font-family: "Playfair Display", serif; font-size: 20px; font-weight: 700;
    color: var(--cream); line-height: 1; margin-bottom: 3px; }
  .metric-delta { font-size: 9px; letter-spacing: 0.05em; }
  .metric-delta.up { color: #4CAF50; }
  .metric-delta.dn { color: var(--red); }
  .metric-delta.neutral { color: var(--tangerine); }
  .thought-block { padding: 26px 40px; border-bottom: 1px solid var(--wire);
    display: grid; grid-template-columns: 3px 1fr; gap: 22px; align-items: start; }
  .thought-rule { background: linear-gradient(to bottom, var(--purple), var(--pink), transparent);
    height: 100%; min-height: 60px; }
  .thought-label { font-size: 8px; letter-spacing: 0.25em; text-transform: uppercase;
    color: var(--purple); margin-bottom: 8px; font-weight: 500; }
  .thought-q { font-family: "DM Serif Display", serif; font-size: 18px; font-style: italic;
    line-height: 1.4; color: var(--cream); margin-bottom: 10px; }
  .thought-body { font-size: 9.5px; line-height: 1.75; color: var(--text-muted); }
  .links-section { padding: 22px 28px; border-bottom: 1px solid var(--wire); }
  .links-header { font-size: 8px; letter-spacing: 0.25em; text-transform: uppercase;
    color: var(--purple); margin-bottom: 14px; font-weight: 500; }
  .links-table { border-collapse: collapse; width: 100%; font-size: 9px; }
  .links-table th { color: rgba(245,240,232,0.3); text-align: left; padding: 5px 10px;
    border-bottom: 1px solid var(--wire); letter-spacing: 0.1em; font-weight: 400; }
  .links-table td { padding: 6px 10px; border-bottom: 1px solid rgba(255,255,255,0.03);
    vertical-align: top; }
  .ts { color: var(--text-muted); white-space: nowrap; width: 120px; }
  .author { color: var(--tangerine); white-space: nowrap; width: 140px; }
  .links-table a { color: var(--pink); text-decoration: none; word-break: break-all; }
  .links-table a:hover { text-decoration: underline; color: var(--cream); }
  .feed-num { color: var(--text-muted); width: 28px; text-align: right; padding-right: 14px; font-size: 8px; letter-spacing: 0.05em; }
  .feed-link { color: var(--purple) !important; text-decoration: none !important; border-bottom: 1px solid rgba(123,79,214,0.4); }
  .feed-link:hover { color: var(--cream) !important; }
  tr:target { background: rgba(123,79,214,0.08); outline: 1px solid rgba(123,79,214,0.3); }
  .embeds-section { padding: 22px 28px; border-bottom: 1px solid var(--wire); }
  /* ---- SIGINT signal cards (tactical trade-reference look) ---- */
  .tweet-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(264px, 1fr));
    gap: 14px; align-items: stretch; }
  .tweet-embed { min-width: 0; display: flex; }
  .tweet-embed:target .tw-card { outline: 1px solid rgba(184,151,90,0.55); outline-offset: 2px; }
  .tw-card { position: relative; display: flex; flex-direction: column; width: 100%;
    background: linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.012));
    border: 1px solid var(--wire); border-left: 2px solid var(--tangerine);
    padding: 12px 14px; font-size: 10px; line-height: 1.65;
    color: rgba(245,240,232,0.78); transition: border-color .15s, transform .15s; }
  .tw-card::before, .tw-card::after { content: ""; position: absolute; width: 7px; height: 7px;
    border-color: rgba(244,123,58,0.5); pointer-events: none; }
  .tw-card::before { top: 4px; right: 4px; border-top: 1px solid; border-right: 1px solid; }
  .tw-card::after  { bottom: 4px; left: 4px; border-bottom: 1px solid; border-left: 1px solid; }
  .tw-card:hover { border-left-color: var(--cream); transform: translateY(-1px); }
  .tw-card-cited { border-left: 2px solid var(--gold);
    background: linear-gradient(180deg, rgba(184,151,90,0.10), rgba(184,151,90,0.02));
    box-shadow: inset 0 0 0 1px rgba(184,151,90,0.15); }
  .tw-card-cited::before, .tw-card-cited::after { border-color: rgba(184,151,90,0.7); }
  .tw-head { display: flex; justify-content: space-between; align-items: baseline;
    gap: 8px; margin-bottom: 7px; }
  .tw-handle { color: var(--tangerine); font-weight: 500; letter-spacing: 0.05em; }
  .tw-meta { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; }
  .tw-cited { font-size: 7px; letter-spacing: 0.18em; color: var(--gold); font-weight: 600;
    border: 1px solid rgba(184,151,90,0.45); padding: 1px 5px; background: rgba(184,151,90,0.08); }
  .tw-ts { color: var(--text-muted); font-size: 8px; letter-spacing: 0.04em; }
  .tw-body { color: rgba(245,240,232,0.82); flex: 1; }
  .tw-link { display: inline-block; margin-top: 10px; font-size: 8px; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--pink); text-decoration: none;
    border-top: 1px solid var(--wire); padding-top: 7px; }
  .tw-link:hover { color: var(--cream); }
  .footer { display: flex; align-items: center; justify-content: space-between;
    padding: 14px 28px; background: rgba(193,18,31,0.04); }
  .footer-left { font-size: 8.5px; color: var(--text-muted); letter-spacing: 0.1em; }
  .footer-left span { color: var(--pink); }
  .footer-right { display: flex; align-items: center; gap: 18px; }
  .footer-tag { font-size: 8px; letter-spacing: 0.18em; text-transform: uppercase;
    color: var(--text-muted); padding: 4px 10px; border: 1px solid var(--wire); }
  .footer-tag.active { border-color: rgba(123,79,214,0.5); color: var(--purple); }
  .scanline { position: absolute; inset: 0;
    background: repeating-linear-gradient(0deg, transparent, transparent 2px,
      rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px); pointer-events: none; }
  .bear-label { font-size: 7.5px; letter-spacing: 0.2em; text-transform: uppercase;
    color: var(--pink); margin-top: 14px; margin-bottom: 5px; font-weight: 500; }
  .bear-body { font-size: 9px; line-height: 1.7; color: rgba(245,240,232,0.38); }
  .conviction-tag { margin-top: 7px; font-size: 8.5px; letter-spacing: 0.08em;
    color: var(--tangerine); font-weight: 500; }
  .thought-bear-label { font-size: 7.5px; letter-spacing: 0.2em; text-transform: uppercase;
    color: var(--pink); margin-top: 16px; margin-bottom: 6px; font-weight: 500; }
  .thought-bear { font-size: 9.5px; line-height: 1.75; color: var(--text-muted); }
  .thought-conviction { margin-top: 8px; font-size: 9px; letter-spacing: 0.08em;
    color: var(--tangerine); font-weight: 500; }
  .synopsis-section { padding: 28px 40px; border-bottom: 1px solid var(--wire);
    background: rgba(123,79,214,0.03); }
  .synopsis-label { font-size: 8px; letter-spacing: 0.25em; text-transform: uppercase;
    color: var(--purple); margin-bottom: 6px; font-weight: 500; }
  .synopsis-byline { font-size: 8px; color: var(--text-muted); letter-spacing: 0.08em;
    margin-bottom: 18px; padding-bottom: 12px; border-bottom: 1px solid var(--wire); }
  .synopsis-body { column-count: 2; column-gap: 36px; }
  .synopsis-para { font-size: 10px; line-height: 1.8; color: var(--cream);
    margin-bottom: 14px; letter-spacing: 0.02em; text-align: justify; }
  .synopsis-para:first-child::first-letter { font-family: "Playfair Display", serif;
    font-size: 2.8em; font-weight: 900; float: left; line-height: 0.8;
    margin: 4px 8px 0 0; color: var(--purple); }
  @media (max-width: 600px) { .synopsis-body { column-count: 1; } }
  .trading-section { padding: 22px 28px; border-bottom: 1px solid var(--wire); }
  .trading-label { font-size: 8px; letter-spacing: 0.25em; text-transform: uppercase;
    color: var(--tangerine); margin-bottom: 14px; font-weight: 500; }
  .trading-grid { display: flex; gap: 14px; flex-wrap: wrap; }
  .tc-card { flex: 1; min-width: 180px; background: rgba(255,255,255,0.03);
    border: 1px solid var(--wire); padding: 14px 16px; }
  .tc-header { display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 8px; }
  .tc-sym { font-family: "Playfair Display", serif; font-size: 18px; font-weight: 700;
    color: var(--cream); }
  .tc-rec { font-size: 8px; letter-spacing: 0.2em; font-weight: 600;
    padding: 3px 8px; border: 1px solid; }
  .rec-in  { color: #4CAF50; border-color: rgba(76,175,80,0.4); background: rgba(76,175,80,0.07); }
  .rec-out { color: var(--red); border-color: rgba(193,18,31,0.4); background: rgba(193,18,31,0.07); }
  .rec-neutral { color: var(--tangerine); border-color: rgba(244,123,58,0.4); background: rgba(244,123,58,0.07); }
  .tc-price { font-size: 15px; font-weight: 500; color: var(--cream);
    margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
  .tc-trend { font-size: 9px; letter-spacing: 0.05em; }
  .tc-row { display: flex; justify-content: space-between; align-items: baseline;
    padding: 3px 0; border-bottom: 1px solid rgba(255,255,255,0.03); }
  .tc-lbl { font-size: 8px; letter-spacing: 0.1em; color: var(--text-muted); }
  .tc-val { font-size: 8.5px; color: var(--cream); text-align: right; }
  .tc-badge { font-size: 7px; letter-spacing: 0.12em; color: var(--tangerine);
    border: 1px solid rgba(244,123,58,0.35); padding: 1px 4px; margin-left: 4px; }
  .tc-ts { font-size: 7px; color: var(--text-muted); margin-top: 8px;
    letter-spacing: 0.05em; text-align: right; }
  .regime-panel { padding: 22px 28px; border-bottom: 1px solid var(--wire);
    background: rgba(0,229,160,0.015); }
  .regime-panel-label { font-size: 8px; letter-spacing: 0.25em; text-transform: uppercase;
    color: #00e5a0; margin-bottom: 12px; font-weight: 500; }
  .regime-badge-row { display: flex; align-items: center; gap: 14px; margin-bottom: 14px;
    flex-wrap: wrap; }
  .regime-badge { font-family: "IBM Plex Mono", monospace; font-size: 13px; font-weight: 700;
    letter-spacing: 0.2em; padding: 5px 14px; border: 1px solid; }
  .regime-desc { font-size: 9px; color: var(--text-muted); letter-spacing: 0.08em; }
  .regime-warn { font-size: 8px; color: #ff9a3c; letter-spacing: 0.1em;
    border: 1px solid rgba(255,154,60,0.4); padding: 3px 8px; background: rgba(255,154,60,0.07); }
  .regime-metrics { display: flex; gap: 0; border: 1px solid var(--wire); }
  .rm { flex: 1; padding: 10px 14px; border-right: 1px solid var(--wire); }
  .rm:last-child { border-right: none; }
  .rm-lbl { font-size: 7.5px; letter-spacing: 0.2em; text-transform: uppercase;
    color: var(--text-muted); margin-bottom: 5px; }
  .rm-val { font-family: "Playfair Display", serif; font-size: 18px; font-weight: 700;
    color: var(--cream); line-height: 1; margin-bottom: 3px; }
  .rm-sub { font-size: 7.5px; color: var(--text-muted); letter-spacing: 0.05em; }
  /* ---- Tactical framing: reticle corners + classification banner ---- */
  .reticle { position: absolute; width: 16px; height: 16px; z-index: 3; pointer-events: none;
    border-color: rgba(244,123,58,0.55); }
  .reticle.tl { top: 6px; left: 6px; border-top: 1px solid; border-left: 1px solid; }
  .reticle.tr { top: 6px; right: 6px; border-top: 1px solid; border-right: 1px solid; }
  .reticle.bl { bottom: 6px; left: 6px; border-bottom: 1px solid; border-left: 1px solid; }
  .reticle.br { bottom: 6px; right: 6px; border-bottom: 1px solid; border-right: 1px solid; }
  .classbar { display: flex; align-items: center; justify-content: space-between;
    padding: 4px 28px; background: repeating-linear-gradient(45deg,
      rgba(193,18,31,0.12) 0 10px, rgba(193,18,31,0.04) 10px 20px);
    border-bottom: 1px solid rgba(193,18,31,0.25);
    font-size: 7.5px; letter-spacing: 0.28em; text-transform: uppercase; color: var(--gold); }
  .classbar .cb-mid { color: rgba(245,240,232,0.55); letter-spacing: 0.2em; }
  @media (max-width: 600px) { .classbar .cb-mid { display: none; } }
  .posture-pill { font-size: 7.5px; letter-spacing: 0.18em; font-weight: 600;
    padding: 2px 8px; border: 1px solid; margin-left: 6px; }
  #dataAge { color: var(--tangerine); }
  /* ---- collapsible sections (native <details>) ---- */
  details.sec { padding: 0; border-bottom: 1px solid var(--wire); }
  details.sec > summary { list-style: none; cursor: pointer; display: flex;
    align-items: center; justify-content: space-between; gap: 12px; padding: 18px 28px 0; }
  details.sec > summary::-webkit-details-marker { display: none; }
  .sec-summary .links-header { margin-bottom: 0; }
  .sec-chevron { color: var(--text-muted); font-size: 10px; transition: transform .2s; }
  details.sec[open] > summary .sec-chevron { transform: rotate(180deg); }
  details.sec > .tweet-grid, details.sec > .cmdbar { margin: 14px 28px 22px; }
  details.sec > table.links-table { margin: 8px 28px 20px; width: calc(100% - 56px); }
  /* ---- command bar (signal filter HUD) ---- */
  .cmdbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
    padding: 10px 12px; border: 1px solid var(--wire); background: rgba(255,255,255,0.02); }
  .cmd-input { flex: 1; min-width: 150px; background: rgba(0,0,0,0.3); border: 1px solid var(--wire);
    color: var(--cream); font-family: "IBM Plex Mono", monospace; font-size: 9px;
    letter-spacing: 0.1em; padding: 6px 9px; }
  .cmd-input::placeholder { color: var(--text-muted); letter-spacing: 0.18em; }
  .cmd-input:focus { outline: none; border-color: rgba(244,123,58,0.6); }
  .cmd-btn, .cmd-select { background: rgba(0,0,0,0.3); border: 1px solid var(--wire);
    color: var(--text-muted); font-family: "IBM Plex Mono", monospace; font-size: 8px;
    letter-spacing: 0.16em; text-transform: uppercase; padding: 6px 10px; cursor: pointer; }
  .cmd-btn:hover, .cmd-select:hover { color: var(--cream); border-color: rgba(244,123,58,0.5); }
  .cmd-btn.on { color: var(--gold); border-color: rgba(184,151,90,0.6); background: rgba(184,151,90,0.1); }
  .cmd-count { font-size: 8px; letter-spacing: 0.12em; color: var(--text-muted); margin-left: auto; }
</style>
</head>
<body>
<div class="card">
  <div class="scanline"></div>
  <div class="reticle tl"></div><div class="reticle tr"></div>
  <div class="reticle bl"></div><div class="reticle br"></div>

  <div class="topbar">
    <div class="topbar-left">
      <div class="pulse"></div>
      <span class="topbar-label">RedHood Reads &middot; Live Edition</span>
      %%POSTURE%%
    </div>
    <span class="topbar-date">%%TOPBAR_DATE%% &middot; <span id="dataAge" data-runts="%%RUN_ISO%%">live</span></span>
  </div>

  <div class="classbar">
    <span>// SIGNAL INTELLIGENCE</span>
    <span class="cb-mid">TRADE REFERENCE &middot; HANDLE WITH DISCRETION</span>
    <span>NOT FINANCIAL ADVICE //</span>
  </div>

  <div class="ticker-wrap"><div class="ticker-inner">
    %%TICKER_HTML%%
  </div></div>

  <div class="hero">
    <div class="issue-line">
      <span class="issue-num">%%ISSUE_NUM%%</span>
      <div class="issue-rule"></div>
    </div>
    <div class="masthead">Red<span class="red-accent">Hood</span><br>Reads</div>
    <div class="sub-masthead">Markets &middot; Macro &middot; Intelligence</div>
    <div class="headline-block">
      <div class="headline">%%HEADLINE%%</div>
      <div class="deck">%%DECK%%</div>
    </div>
    <div class="corner-deco">
      <div class="vol-label">Day</div>
      <div class="vol-num">%%VOL_NUM%%</div>
    </div>
  </div>

  <div class="metrics-strip">%%METRICS%%</div>

  %%SYNOPSIS%%

  <div class="grid-section">%%GRID%%</div>

  <div class="thought-block">
    <div class="thought-rule"></div>
    <div>
      <div class="thought-label">Top Trade Hypothesis</div>
      <div class="thought-q">%%THOUGHT_Q%%</div>
      <div class="thought-body">%%THOUGHT_BODY%%</div>
      <div class="thought-bear-label">Bear Case</div>
      <div class="thought-bear">%%THOUGHT_BEAR%%</div>
      <div class="thought-conviction">%%THOUGHT_CONVICTION%%</div>
    </div>
  </div>

  %%TRADING%%

  %%REGIME_PANEL%%

  <details class="embeds-section sec" open>
    <summary class="sec-summary">
      <span class="links-header">SIGINT &mdash; Signal Cards &middot; %%EMBED_COUNT%% of %%FEED_COUNT%% &middot; %%CITED_COUNT%% narrative-cited + top 55 &middot; %%RUN_TIME%%</span>
      <span class="sec-chevron">&#9662;</span>
    </summary>
    <div class="cmdbar">
      <input id="cardSearch" class="cmd-input" type="text" placeholder="SEARCH SIGNALS / HANDLES…" autocomplete="off">
      <button id="citedToggle" class="cmd-btn" type="button">&#9670; CITED ONLY</button>
      <select id="acctFilter" class="cmd-select" aria-label="Filter by account"><option value="">ALL ACCOUNTS</option></select>
      <select id="sortSel" class="cmd-select" aria-label="Sort cards">
        <option value="recent">SORT &middot; RECENT</option>
        <option value="handle">SORT &middot; HANDLE</option>
      </select>
      <span id="cardCount" class="cmd-count"></span>
    </div>
    <div class="tweet-grid" id="tweetGrid">%%EMBEDS%%</div>
  </details>

  %%LINKS_SECTION%%

  <div class="footer">
    <div class="footer-left"><span>@redhoodcapital</span> &nbsp;&middot;&nbsp; Not financial advice</div>
    <div class="footer-right">
      <span class="footer-tag active">AI</span>
      <span class="footer-tag">MACRO</span>
      <span class="footer-tag">CRYPTO</span>
      <span class="footer-tag">SIGNALS</span>
    </div>
  </div>
</div>
<script>
(function(){
  "use strict";
  var grid = document.getElementById('tweetGrid');
  if (grid) {
    var cards   = Array.prototype.slice.call(grid.querySelectorAll('.tweet-embed'));
    var search  = document.getElementById('cardSearch');
    var cited   = document.getElementById('citedToggle');
    var acct    = document.getElementById('acctFilter');
    var sortSel = document.getElementById('sortSel');
    var count   = document.getElementById('cardCount');
    var citedOnly = false;

    // Populate the account dropdown from the cards present.
    var seen = {};
    cards.forEach(function(c){ var h = c.getAttribute('data-handle'); if (h) seen[h] = 1; });
    Object.keys(seen).sort().forEach(function(h){
      var o = document.createElement('option'); o.value = h; o.textContent = '@' + h; acct.appendChild(o);
    });

    function apply(){
      var q = (search.value || '').toLowerCase().trim();
      var a = acct.value;
      var shown = 0;
      cards.forEach(function(c){
        var ok = true;
        if (q && c.getAttribute('data-search').indexOf(q) < 0) ok = false;
        if (a && c.getAttribute('data-handle') !== a) ok = false;
        if (citedOnly && c.getAttribute('data-cited') !== '1') ok = false;
        c.style.display = ok ? '' : 'none';
        if (ok) shown++;
      });
      count.textContent = shown + ' / ' + cards.length + ' shown';
    }
    function sortCards(){
      var mode = sortSel.value;
      cards.slice().sort(function(x, y){
        if (mode === 'handle') return x.getAttribute('data-handle').localeCompare(y.getAttribute('data-handle'));
        return y.getAttribute('data-ts').localeCompare(x.getAttribute('data-ts'));
      }).forEach(function(c){ grid.appendChild(c); });
    }

    search.addEventListener('input', apply);
    acct.addEventListener('change', apply);
    cited.addEventListener('click', function(){
      citedOnly = !citedOnly; cited.classList.toggle('on', citedOnly); apply();
    });
    sortSel.addEventListener('change', function(){ sortCards(); apply(); });
    apply();
  }

  // Live data-age readout: "T+Xh Ym" since the run timestamp.
  var age = document.getElementById('dataAge');
  if (age) {
    var t0 = new Date(age.getAttribute('data-runts')).getTime();
    var tick = function(){
      if (!t0 || isNaN(t0)) { age.textContent = 'live'; return; }
      var s = Math.max(0, Math.floor((Date.now() - t0) / 1000));
      var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
      age.textContent = 'T+' + (h ? h + 'h ' : '') + m + 'm';
    };
    tick(); setInterval(tick, 30000);
  }
})();
</script>
</body>
</html>'''

    def _persist_to_db(self, hours_back: float, all_feeds: list, narratives: list,
                        json_path: str, html_path: str) -> int:
        """Persist run results into SQLite (runs, feeds, narratives, narrative_feeds)."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                """INSERT INTO runs (run_at, hours_back, feeds_collected, narratives_extracted, json_path, html_path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), hours_back,
                 len(all_feeds), len(narratives), json_path, html_path)
            )
            run_id = cursor.lastrowid
            conn.commit()

            for feed in all_feeds:
                conn.execute(
                    """INSERT OR IGNORE INTO feeds
                       (id, run_id, source, author, content, published_at, url, nitter_instance)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (feed.id, run_id, feed.source, feed.author, feed.content,
                     feed.timestamp.isoformat(), feed.url,
                     feed.metadata.get('nitter_instance'))
                )

            ticker_rows_total = 0
            now_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            for narrative in narratives:
                catalysts_json = json.dumps(narrative.catalysts)
                cat_count = _catalyst_count(catalysts_json)
                conv_size = _conviction_size(narrative.conviction_adjustment)
                ent_band  = _entropy_band(narrative.entropy_risk)

                conn.execute(
                    """INSERT OR IGNORE INTO narratives
                       (id, run_id, title, entropy_risk, hypothesis, rationale, catalysts, created_at,
                        bear_case, disconfirming_signals, conviction_adjustment,
                        catalyst_count, conviction_size, entropy_band)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (narrative.id, run_id, narrative.title, narrative.entropy_risk,
                     narrative.hypothesis, narrative.rationale,
                     catalysts_json, narrative.date.isoformat(),
                     narrative.bear_case, json.dumps(narrative.disconfirming_signals),
                     narrative.conviction_adjustment,
                     cat_count, conv_size, ent_band)
                )
                for feed_id in narrative.supporting_feeds:
                    conn.execute(
                        "INSERT OR IGNORE INTO narrative_feeds (narrative_id, feed_id) VALUES (?, ?)",
                        (narrative.id, feed_id)
                    )

                # --- Ticker bridge + dim_ticker auto-seed (audit gaps G1, G2) ---
                ticker_rows = extract_tickers(narrative.hypothesis or "")
                for row in ticker_rows:
                    conn.execute(
                        """INSERT OR IGNORE INTO tickers (ticker, first_seen_at)
                           VALUES (?, ?)""",
                        (row["ticker"], now_iso)
                    )
                    conn.execute(
                        """INSERT OR IGNORE INTO narrative_tickers
                               (narrative_id, ticker, side, extracted_pattern)
                           VALUES (?, ?, ?, ?)""",
                        (narrative.id, row["ticker"], row["side"], row["pattern"])
                    )
                ticker_rows_total += len(ticker_rows)

            conn.commit()
            print(f"🗄️  DB: run #{run_id} saved — {len(all_feeds)} feeds, "
                  f"{len(narratives)} narratives, {ticker_rows_total} ticker mentions")
            return run_id
        except Exception as e:
            conn.rollback()
            print(f"⚠️  DB persist error: {e}")
            return None
        finally:
            conn.close()

    def _print_summary(self, narratives: list[Narrative], trading_data: list = None):
        """Print formatted summary of narratives and trading signals"""

        if trading_data:
            print("\n" + "=" * 60)
            print("📊 POSITIONAL SIGNALS")
            print("=" * 60)
            for s in trading_data:
                sym  = s.get('Symbol', '—')
                price = s.get('Price', 0)
                rec  = str(s.get('Recommendation', 'NEUTRAL')).upper()
                ent_sig = str(s.get('EntropySignal', 'NEUTRAL')).upper()
                prc_sig = str(s.get('PriceSignal', 'NEUTRAL')).upper()
                trend = s.get('Trend', '—')
                rsi  = s.get('RSI', 0)
                mom  = s.get('Momentum', 0) or 0
                pos  = s.get('PositionSize', 0) or 0
                ma20 = s.get('MA20', 0) or 0
                ma50 = s.get('MA50', 0) or 0
                entr = s.get('EntropyStatus', '—')
                ts   = s.get('Timestamp', '—')
                rec_icon = '🟢 IN' if rec == 'IN' else '🔴 OUT' if rec == 'OUT' else '🟡 NEUTRAL'
                trend_icon = '↑' if trend == 'UP' else '↓'
                price_fmt = f"${price:,.0f}" if price > 1000 else f"${price:,.2f}"
                print(f"\n  {sym}  {price_fmt}  |  {rec_icon}  |  Trend {trend_icon}  |  RSI {rsi:.1f}  |  Mom {mom:+.2f}%")
                print(f"  Entropy signal: {ent_sig}  |  Price signal: {prc_sig}")
                print(f"  MA20 {ma20:,.2f}  MA50 {ma50:,.2f}  |  Entropy {entr}  |  Position ${pos:,.0f}  |  As of {ts}")
            print()

        print("\n" + "=" * 60)
        print("📋 DAILY BRIEF - TOP NARRATIVES")
        print("=" * 60 + "\n")

        for i, narrative in enumerate(narratives, 1):
            entropy_level = "🟢 LOW" if narrative.entropy_risk <= 3 else \
                           "🟡 MEDIUM" if narrative.entropy_risk <= 7 else "🔴 HIGH"

            print(f"[{i}] {narrative.title}")
            print(f"    Entropy Risk: {entropy_level} ({narrative.entropy_risk}/10)")
            print(f"    💡 Hypothesis: {narrative.hypothesis}")
            print(f"    📝 Rationale: {narrative.rationale}")
            print(f"    📅 Catalysts: {', '.join(narrative.catalysts)}")
            if narrative.bear_case:
                print(f"    🐻 Bear Case: {narrative.bear_case}")
            if narrative.conviction_adjustment:
                print(f"    📊 Conviction: {narrative.conviction_adjustment}")
            print()


# ============================================================================
# CLI INTERFACE
# ============================================================================

def main():
    """Command-line interface for the aggregator"""

    import argparse

    parser = argparse.ArgumentParser(
        description='RedHood Systems - AI-Powered Market Intelligence'
    )
    parser.add_argument(
        '--hours',
        type=float,
        default=round(10/60, 4),
        help='Hours of history to fetch, accepts decimals e.g. 0.1667 for 10 minutes (default: 0.1667)'
    )
    parser.add_argument(
        '--api-key',
        type=str,
        help='Anthropic API key (or set ANTHROPIC_API_KEY env var)'
    )
    parser.add_argument(
        '--trading-json',
        type=str,
        default=None,
        help='Path to latest_trading.json produced by run.ps1'
    )

    args = parser.parse_args()

    # Auto-detect latest_trading.json if --trading-json not provided
    if not args.trading_json:
        default_trading = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       'data', 'latest_trading.json')
        if os.path.exists(default_trading):
            args.trading_json = default_trading

    # Override API key if provided
    if args.api_key:
        os.environ['ANTHROPIC_API_KEY'] = args.api_key

    # Check for required API key
    if not os.getenv('ANTHROPIC_API_KEY'):
        print("❌ Error: ANTHROPIC_API_KEY not set")
        print("\nPlease set your API key:")
        print("  export ANTHROPIC_API_KEY='your-key-here'")
        print("  python redhood_aggregator.py --api-key your-key-here")
        return

    # Run aggregator
    aggregator = RedHoodAggregator()
    results = aggregator.run(hours_back=args.hours, trading_json=args.trading_json)

    print("\n✅ Pipeline complete!")
    print(f"   Feeds processed: {len(results['feeds'])}")
    print(f"   Narratives extracted: {len(results['narratives'])}")


if __name__ == '__main__':
    main()

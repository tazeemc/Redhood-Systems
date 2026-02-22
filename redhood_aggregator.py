"""
RedHood Insights - Feed Aggregator & AI Analysis Tool
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
from datetime import datetime, timedelta
from typing import List, Dict, Any
import sqlite3
import feedparser
from anthropic import Anthropic
from dotenv import load_dotenv
from accounts_db import get_active_handles, init_db
from models import DB_PATH, init_schema

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
    CLAUDE_MODEL = 'claude-sonnet-4-5'
    MAX_FEEDS_TO_PROCESS = 50  # Limit for cost control
    
    # Output
    OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')


# ============================================================================
# DATA MODELS
# ============================================================================

class FeedItem:
    """Represents a single feed item from any source"""
    
    def __init__(self, source: str, author: str, content: str, 
                 timestamp: datetime, url: str = None, metadata: Dict = None):
        self.id = f"{source}_{author}_{int(timestamp.timestamp())}"
        self.source = source
        self.author = author
        self.content = content
        self.timestamp = timestamp
        self.url = url
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
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
                 rationale: str, catalysts: List[str], supporting_feeds: List[str]):
        self.id = f"narrative_{int(time.time())}_{id(self)}"
        self.date = datetime.now()
        self.title = title
        self.entropy_risk = entropy_risk  # 1-10 scale
        self.hypothesis = hypothesis
        self.rationale = rationale
        self.catalysts = catalysts
        self.supporting_feeds = supporting_feeds
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'title': self.title,
            'entropy_risk': self.entropy_risk,
            'hypothesis': self.hypothesis,
            'rationale': self.rationale,
            'catalysts': self.catalysts,
            'supporting_feeds': self.supporting_feeds
        }


# ============================================================================
# FEED SCRAPERS
# ============================================================================

class RSSFeedScraper:
    """Scraper for Substack and other RSS feeds"""
    
    @staticmethod
    def fetch(feed_urls: List[str], hours_back: float = 24) -> List[FeedItem]:
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

    def __init__(self, instances: List[str]):
        self.instances = instances

    def _rss_url(self, instance: str, account: str) -> str:
        return f"https://{instance}/{account}/rss"

    def fetch(self, accounts: List[str], hours_back: float = 24) -> List[FeedItem]:
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
    
    def extract_narratives(self, feeds: List[FeedItem], max_feeds: int = 50) -> List[Narrative]:
        """
        Process feeds through Claude to extract top narratives
        
        Args:
            feeds: List of FeedItem objects
            max_feeds: Maximum number of feeds to process (cost control)
        
        Returns:
            List of Narrative objects
        """
        
        # Limit feeds for cost control
        feeds_to_process = feeds[:max_feeds]
        
        # Format feeds for prompt
        feeds_text = self._format_feeds_for_prompt(feeds_to_process)
        
        # Build prompt
        prompt = self._build_extraction_prompt(feeds_text)
        
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
            return narratives
            
        except Exception as e:
            print(f"❌ Error calling Claude API: {e}")
            return []
    
    def _format_feeds_for_prompt(self, feeds: List[FeedItem]) -> str:
        """Format feeds into readable text for Claude"""
        
        formatted = []
        for i, feed in enumerate(feeds, 1):
            formatted.append(
                f"[{i}] {feed.source.upper()} | {feed.author} | "
                f"{feed.timestamp.strftime('%Y-%m-%d %H:%M')}\n"
                f"{feed.content[:300]}...\n"
            )
        
        return "\n".join(formatted)
    
    def _build_extraction_prompt(self, feeds_text: str) -> str:
        """Build the prompt for Claude"""
        
        return f"""You are a portfolio manager with a physics PhD analyzing market intelligence feeds.

Your task: Extract the top 3 market narratives from these feeds and generate actionable trade hypotheses.

FEEDS:
{feeds_text}

ANALYSIS FRAMEWORK:
1. Identify the 3 most significant narratives (themes repeated across multiple sources)
2. Score "entropy risk" for each narrative (1-10 scale):
   - Low (1-3): Stable consensus, low uncertainty
   - Medium (4-7): Mixed signals, moderate debate
   - High (8-10): Conflicting information, high volatility potential
3. Generate a trade hypothesis for each narrative with:
   - Entry logic (why this trade, why now?)
   - Risk parameters (position size, stop loss)
   - Expected catalysts (upcoming events that could move the market)
4. Use physics analogies where helpful (entropy, momentum, phase transitions, etc.)

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
- Include exactly 3 narratives
- Be specific with trade ideas (not just "buy tech")
- Entropy scoring should reflect information quality/consensus level"""
    
    def _parse_claude_response(self, response_text: str, feeds: List[FeedItem]) -> List[Narrative]:
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
    
    def run(self, hours_back: float = 24) -> Dict[str, Any]:
        """
        Run full aggregation and analysis pipeline
        
        Returns:
            Dictionary with feeds and narratives
        """
        
        print("=" * 60)
        print("🔥 REDHOOD INSIGHTS - Feed Aggregator")
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
        
        # Extract narratives using AI
        print("🧠 AI Analysis Phase...\n")
        narratives = self.ai_engine.extract_narratives(
            all_feeds,
            max_feeds=self.config.MAX_FEEDS_TO_PROCESS
        )
        
        # Save results
        results = {
            'timestamp': datetime.now().isoformat(),
            'feeds': [f.to_dict() for f in all_feeds],
            'narratives': [n.to_dict() for n in narratives]
        }
        
        json_path, html_path = self._save_results(results, narratives, hours_back)
        self._persist_to_db(hours_back, all_feeds, narratives, json_path, html_path)
        self._print_summary(narratives)
        
        return results
    
    def _save_results(self, results: Dict[str, Any],
                      narratives: List[Narrative], hours_back: float):
        """Save results to JSON and HTML report. Returns (json_path, html_path)."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        json_path = os.path.join(self.config.OUTPUT_DIR,
                                 f'redhood_insights_{timestamp}.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        print(f"\n💾 Results saved to: {json_path}")

        html_path = os.path.join(self.config.OUTPUT_DIR,
                                 f'redhood_reads_{timestamp}.html')
        self._save_html_report(results, narratives, html_path, timestamp, hours_back)
        print(f"📰 Report saved to:   {html_path}")

        return json_path, html_path

    def _save_html_report(self, results: Dict[str, Any], narratives: List[Narrative],
                          filepath: str, timestamp: str, hours_back: float):
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

        narrs = list(narratives[:3]) + [None] * max(0, 3 - len(narratives))
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

        col_tags = ['Intelligence', 'Market Signal', 'Macro View']

        def grid_col(narr, idx):
            if narr is None:
                return '<div class="grid-col"><div class="col-tag">—</div></div>'
            tag = H.escape(f'{col_tags[idx]} · Risk {narr.entropy_risk}/10')
            title = H.escape(narr.title)
            body = H.escape(narr.hypothesis[:240] + ('…' if len(narr.hypothesis) > 240 else ''))
            return (f'<div class="grid-col">'
                    f'<div class="col-tag">{tag}</div>'
                    f'<div class="col-title">{title}</div>'
                    f'<div class="col-body">{body}</div>'
                    f'{sparkline(narr.entropy_risk)}</div>')

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
        metrics_html = '\n'.join(metric_blocks[:5])

        headline = H.escape(top.title) if top else 'Market Intelligence Brief'
        deck = H.escape((top.rationale[:240] + '…') if top and len(top.rationale) > 240
                        else (top.rationale if top else ''))
        thought_q = H.escape(top.hypothesis) if top else ''
        thought_body = H.escape(', '.join(top.catalysts)) if top else ''
        grid_html = '\n'.join(grid_col(n, i) for i, n in enumerate(narrs))

        link_rows = ''.join(
            f'<tr><td class="ts">{f["timestamp"][:16].replace("T"," ")}</td>'
            f'<td class="author">{H.escape(f["author"])}</td>'
            f'<td><a href="{H.escape(f["url"])}" target="_blank">{H.escape(f["url"])}</a></td></tr>'
            for f in twitter_feeds
        )

        # Build HTML using string replacement to avoid f-string brace conflicts with CSS
        tpl = self._html_report_template()
        html_out = (tpl
            .replace('%%TOPBAR_DATE%%',  f'{run_date_full} &nbsp;|&nbsp; Week {week_num:02d}')
            .replace('%%ISSUE_NUM%%',    f'Run &middot; {window_label} &middot; {run_time_short}')
            .replace('%%VOL_NUM%%',      str(dt.strftime('%d')))
            .replace('%%HEADLINE%%',     headline)
            .replace('%%DECK%%',         deck)
            .replace('%%METRICS%%',      metrics_html)
            .replace('%%GRID%%',         grid_html)
            .replace('%%THOUGHT_Q%%',    thought_q)
            .replace('%%THOUGHT_BODY%%', thought_body)
            .replace('%%LINK_ROWS%%',    link_rows)
            .replace('%%FEED_COUNT%%',   str(feed_count))
            .replace('%%RUN_TIME%%',     run_time_short)
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
  }
  body { background: var(--dark); font-family: "IBM Plex Mono", monospace; color: var(--cream);
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    padding: 32px 16px; overflow-x: hidden; }
  body::before { content: ""; position: fixed; inset: 0;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.04'/%3E%3C/svg%3E");
    pointer-events: none; z-index: 0; opacity: 0.6; }
  .card { position: relative; width: 100%; max-width: 900px; background: var(--charcoal);
    border: 1px solid rgba(193,18,31,0.25); z-index: 1; overflow: hidden; }
  .card::before { content: ""; position: absolute; top: -60px; right: -60px; width: 200px;
    height: 200px; background: var(--red); transform: rotate(45deg); opacity: 0.08; }
  .topbar { display: flex; align-items: center; justify-content: space-between;
    padding: 12px 28px; border-bottom: 1px solid var(--wire);
    background: rgba(193,18,31,0.05); }
  .topbar-left { display: flex; align-items: center; gap: 12px; }
  .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--red);
    animation: pulse 2s ease-in-out infinite; }
  @keyframes pulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(193,18,31,0.5); }
    50% { opacity: 0.7; box-shadow: 0 0 0 5px rgba(193,18,31,0); }
  }
  .topbar-label { font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase;
    color: var(--red); font-weight: 500; }
  .topbar-date { font-size: 9px; letter-spacing: 0.1em; color: var(--text-muted); }
  .ticker-wrap { overflow: hidden; border-bottom: 1px solid var(--wire);
    background: var(--mid); padding: 7px 0; }
  .ticker-inner { display: flex; gap: 0; animation: ticker 28s linear infinite; white-space: nowrap; }
  @keyframes ticker { 0% { transform: translateX(0); } 100% { transform: translateX(-50%); } }
  .tick-item { display: inline-flex; align-items: center; gap: 6px; padding: 0 24px;
    font-size: 9.5px; letter-spacing: 0.08em; border-right: 1px solid var(--wire); }
  .tick-sym { color: var(--gold); font-weight: 500; }
  .tick-val { color: var(--cream); }
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
    text-transform: uppercase; color: var(--gold); margin-bottom: 28px; }
  .headline-block { max-width: 620px; }
  .headline { font-family: "DM Serif Display", serif; font-size: clamp(18px, 3.2vw, 26px);
    line-height: 1.3; color: var(--cream); margin-bottom: 14px; font-style: italic; }
  .deck { font-size: 10.5px; line-height: 1.7; color: var(--text-muted);
    letter-spacing: 0.03em; max-width: 540px; }
  .corner-deco { position: absolute; top: 44px; right: 40px; text-align: right; }
  .corner-deco .vol-label { font-size: 8px; letter-spacing: 0.2em; color: var(--text-muted);
    text-transform: uppercase; }
  .corner-deco .vol-num { font-family: "Playfair Display", serif; font-size: 52px;
    font-weight: 900; color: rgba(193,18,31,0.12); line-height: 1; letter-spacing: -0.04em; }
  .grid-section { display: grid; grid-template-columns: 1fr 1fr 1fr;
    border-bottom: 1px solid var(--wire); }
  .grid-col { padding: 22px 24px; border-right: 1px solid var(--wire); position: relative; }
  .grid-col:last-child { border-right: none; }
  .col-tag { font-size: 7.5px; letter-spacing: 0.25em; text-transform: uppercase;
    color: var(--red); margin-bottom: 10px; font-weight: 500; }
  .col-title { font-family: "Playfair Display", serif; font-size: 15px; font-weight: 700;
    line-height: 1.25; margin-bottom: 10px; color: var(--cream); }
  .col-body { font-size: 9.5px; line-height: 1.75; color: var(--text-muted); }
  .sparkline { margin-top: 14px; height: 32px; display: flex; align-items: flex-end; gap: 2px; }
  .bar { flex: 1; background: var(--wire); border-radius: 1px; }
  .bar.hi { background: rgba(76,175,80,0.5); }
  .bar.lo { background: rgba(193,18,31,0.5); }
  .bar.mid-hi { background: rgba(184,151,90,0.4); }
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
  .metric-delta.neutral { color: var(--gold); }
  .thought-block { padding: 26px 40px; border-bottom: 1px solid var(--wire);
    display: grid; grid-template-columns: 3px 1fr; gap: 22px; align-items: start; }
  .thought-rule { background: linear-gradient(to bottom, var(--red), transparent);
    height: 100%; min-height: 60px; }
  .thought-label { font-size: 8px; letter-spacing: 0.25em; text-transform: uppercase;
    color: var(--red); margin-bottom: 8px; font-weight: 500; }
  .thought-q { font-family: "DM Serif Display", serif; font-size: 18px; font-style: italic;
    line-height: 1.4; color: var(--cream); margin-bottom: 10px; }
  .thought-body { font-size: 9.5px; line-height: 1.75; color: var(--text-muted); }
  .links-section { padding: 22px 28px; border-bottom: 1px solid var(--wire); }
  .links-header { font-size: 8px; letter-spacing: 0.25em; text-transform: uppercase;
    color: var(--red); margin-bottom: 14px; font-weight: 500; }
  .links-table { border-collapse: collapse; width: 100%; font-size: 9px; }
  .links-table th { color: rgba(245,240,232,0.3); text-align: left; padding: 5px 10px;
    border-bottom: 1px solid var(--wire); letter-spacing: 0.1em; font-weight: 400; }
  .links-table td { padding: 6px 10px; border-bottom: 1px solid rgba(255,255,255,0.03);
    vertical-align: top; }
  .ts { color: var(--text-muted); white-space: nowrap; width: 120px; }
  .author { color: var(--gold); white-space: nowrap; width: 140px; }
  .links-table a { color: #4ea3ff; text-decoration: none; word-break: break-all; }
  .links-table a:hover { text-decoration: underline; }
  .footer { display: flex; align-items: center; justify-content: space-between;
    padding: 14px 28px; background: rgba(193,18,31,0.04); }
  .footer-left { font-size: 8.5px; color: var(--text-muted); letter-spacing: 0.1em; }
  .footer-left span { color: var(--gold); }
  .footer-right { display: flex; align-items: center; gap: 18px; }
  .footer-tag { font-size: 8px; letter-spacing: 0.18em; text-transform: uppercase;
    color: var(--text-muted); padding: 4px 10px; border: 1px solid var(--wire); }
  .footer-tag.active { border-color: rgba(193,18,31,0.4); color: var(--red); }
  .scanline { position: absolute; inset: 0;
    background: repeating-linear-gradient(0deg, transparent, transparent 2px,
      rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px); pointer-events: none; }
</style>
</head>
<body>
<div class="card">
  <div class="scanline"></div>

  <div class="topbar">
    <div class="topbar-left">
      <div class="pulse"></div>
      <span class="topbar-label">RedHood Reads &middot; Live Edition</span>
    </div>
    <span class="topbar-date">%%TOPBAR_DATE%%</span>
  </div>

  <div class="ticker-wrap"><div class="ticker-inner">
    <span class="tick-item"><span class="tick-sym">BTC/USD</span><span class="tick-val">—</span></span>
    <span class="tick-item"><span class="tick-sym">S&amp;P 500</span><span class="tick-val">—</span></span>
    <span class="tick-item"><span class="tick-sym">WTI</span><span class="tick-val">—</span></span>
    <span class="tick-item"><span class="tick-sym">GOLD</span><span class="tick-val">—</span></span>
    <span class="tick-item"><span class="tick-sym">VIX</span><span class="tick-val">—</span></span>
    <span class="tick-item"><span class="tick-sym">10YR UST</span><span class="tick-val">—</span></span>
    <span class="tick-item"><span class="tick-sym">USD/CAD</span><span class="tick-val">—</span></span>
    <span class="tick-item"><span class="tick-sym">BTC/USD</span><span class="tick-val">—</span></span>
    <span class="tick-item"><span class="tick-sym">S&amp;P 500</span><span class="tick-val">—</span></span>
    <span class="tick-item"><span class="tick-sym">WTI</span><span class="tick-val">—</span></span>
    <span class="tick-item"><span class="tick-sym">GOLD</span><span class="tick-val">—</span></span>
    <span class="tick-item"><span class="tick-sym">VIX</span><span class="tick-val">—</span></span>
    <span class="tick-item"><span class="tick-sym">10YR UST</span><span class="tick-val">—</span></span>
    <span class="tick-item"><span class="tick-sym">USD/CAD</span><span class="tick-val">—</span></span>
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

  <div class="grid-section">%%GRID%%</div>

  <div class="thought-block">
    <div class="thought-rule"></div>
    <div>
      <div class="thought-label">Top Trade Hypothesis</div>
      <div class="thought-q">%%THOUGHT_Q%%</div>
      <div class="thought-body">%%THOUGHT_BODY%%</div>
    </div>
  </div>

  <div class="links-section">
    <div class="links-header">Raw Signal Links &mdash; %%FEED_COUNT%% feeds &middot; %%RUN_TIME%%</div>
    <table class="links-table">
      <thead><tr><th>Timestamp</th><th>Account</th><th>Link</th></tr></thead>
      <tbody>%%LINK_ROWS%%</tbody>
    </table>
  </div>

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
</body>
</html>'''
    
    def _persist_to_db(self, hours_back: float, all_feeds: List, narratives: List,
                        json_path: str, html_path: str) -> int:
        """Persist run results into SQLite (runs, feeds, narratives, narrative_feeds)."""
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                """INSERT INTO runs (run_at, hours_back, feeds_collected, narratives_extracted, json_path, html_path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (datetime.utcnow().isoformat(), hours_back,
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

            for narrative in narratives:
                conn.execute(
                    """INSERT OR IGNORE INTO narratives
                       (id, run_id, title, entropy_risk, hypothesis, rationale, catalysts, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (narrative.id, run_id, narrative.title, narrative.entropy_risk,
                     narrative.hypothesis, narrative.rationale,
                     json.dumps(narrative.catalysts), narrative.date.isoformat())
                )
                for feed_id in narrative.supporting_feeds:
                    conn.execute(
                        "INSERT OR IGNORE INTO narrative_feeds (narrative_id, feed_id) VALUES (?, ?)",
                        (narrative.id, feed_id)
                    )

            conn.commit()
            print(f"🗄️  DB: run #{run_id} saved — {len(all_feeds)} feeds, {len(narratives)} narratives")
            return run_id
        except Exception as e:
            conn.rollback()
            print(f"⚠️  DB persist error: {e}")
            return None
        finally:
            conn.close()

    def _print_summary(self, narratives: List[Narrative]):
        """Print formatted summary of narratives"""
        
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
            print()


# ============================================================================
# CLI INTERFACE
# ============================================================================

def main():
    """Command-line interface for the aggregator"""
    
    import argparse
    
    parser = argparse.ArgumentParser(
        description='RedHood Insights - AI-Powered Market Intelligence'
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
    
    args = parser.parse_args()
    
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
    results = aggregator.run(hours_back=args.hours)
    
    print("\n✅ Pipeline complete!")
    print(f"   Feeds processed: {len(results['feeds'])}")
    print(f"   Narratives extracted: {len(results['narratives'])}")


if __name__ == '__main__':
    main()

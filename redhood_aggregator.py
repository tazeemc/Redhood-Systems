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
    pip install anthropic feedparser tweepy pandas python-dotenv --break-system-packages
"""

import os
import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any
import feedparser
from anthropic import Anthropic

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Centralized configuration for API keys and feed sources"""
    
    # API Keys (set via environment variables)
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
    TWITTER_BEARER_TOKEN = os.getenv('TWITTER_BEARER_TOKEN', '')
    
    # Feed Sources (customize these!)
    TWITTER_ACCOUNTS = [
        'unusual_whales',
        'FirstSquawk',
        'AutismCapital',
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
        self.id = f"narrative_{int(time.time())}"
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
    def fetch(feed_urls: List[str], hours_back: int = 24) -> List[FeedItem]:
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


class TwitterScraper:
    """Scraper for X/Twitter using official API"""
    
    def __init__(self, bearer_token: str):
        self.bearer_token = bearer_token
        self.enabled = bool(bearer_token)
    
    def fetch(self, accounts: List[str], hours_back: int = 24) -> List[FeedItem]:
        """Fetch recent tweets from specified accounts"""
        
        if not self.enabled:
            print("⚠️  Twitter API not configured - skipping")
            return []
        
        # NOTE: This is a simplified version. 
        # In production, use tweepy library with proper authentication
        items = []
        
        try:
            import tweepy
            
            # Authenticate
            client = tweepy.Client(bearer_token=self.bearer_token)
            cutoff_time = datetime.now() - timedelta(hours=hours_back)
            
            for account in accounts:
                try:
                    # Get user ID
                    user = client.get_user(username=account)
                    user_id = user.data.id
                    
                    # Get recent tweets
                    tweets = client.get_users_tweets(
                        user_id, 
                        max_results=10,
                        tweet_fields=['created_at', 'public_metrics']
                    )
                    
                    if not tweets.data:
                        continue
                    
                    for tweet in tweets.data:
                        if tweet.created_at < cutoff_time:
                            continue
                        
                        item = FeedItem(
                            source='twitter',
                            author=f"@{account}",
                            content=tweet.text,
                            timestamp=tweet.created_at,
                            url=f"https://twitter.com/{account}/status/{tweet.id}",
                            metadata={
                                'likes': tweet.public_metrics['like_count'],
                                'retweets': tweet.public_metrics['retweet_count']
                            }
                        )
                        items.append(item)
                        
                except Exception as e:
                    print(f"Error fetching tweets from @{account}: {e}")
            
        except ImportError:
            print("⚠️  tweepy not installed - install with: pip install tweepy")
        except Exception as e:
            print(f"Error with Twitter API: {e}")
        
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
        
        # Initialize scrapers
        self.rss_scraper = RSSFeedScraper()
        self.twitter_scraper = TwitterScraper(self.config.TWITTER_BEARER_TOKEN)
        
        # Initialize AI engine
        self.ai_engine = NarrativeExtractor(self.config.ANTHROPIC_API_KEY)
        
        # Ensure output directory exists
        os.makedirs(self.config.OUTPUT_DIR, exist_ok=True)
    
    def run(self, hours_back: int = 24) -> Dict[str, Any]:
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
        twitter_feeds = self.twitter_scraper.fetch(self.config.TWITTER_ACCOUNTS, hours_back)
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
        
        self._save_results(results)
        self._print_summary(narratives)
        
        return results
    
    def _save_results(self, results: Dict[str, Any]):
        """Save results to JSON file"""
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = os.path.join(
            self.config.OUTPUT_DIR,
            f'redhood_insights_{timestamp}.json'
        )
        
        with open(filepath, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"\n💾 Results saved to: {filepath}")
    
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
        type=int,
        default=24,
        help='Hours of history to fetch (default: 24)'
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

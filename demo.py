#!/usr/bin/env python3
"""
RedHood Insights - Demo Script
================================

This script demonstrates the full capabilities of RedHood Insights
with sample data (no API keys required for demo mode).

Run with: python demo.py
"""

import json
from datetime import datetime, timedelta

# Demo data: Sample feeds (simulating real sources)
DEMO_FEEDS = [
    {
        "source": "twitter",
        "author": "@zerohedge",
        "content": "BREAKING: Fed Chair Powell signals willingness to pause rate hikes if inflation data continues to cool. Markets pricing in 80% chance of no hike at March FOMC meeting.",
        "timestamp": (datetime.now() - timedelta(hours=2)).isoformat(),
        "url": "https://twitter.com/zerohedge/status/12345"
    },
    {
        "source": "twitter",
        "author": "@unusual_whales",
        "content": "Massive call buying in $QQQ March 500 strikes. $50M premium, unusual activity suggests big money positioning for tech rally into month-end.",
        "timestamp": (datetime.now() - timedelta(hours=3)).isoformat(),
        "url": "https://twitter.com/unusual_whales/status/12346"
    },
    {
        "source": "rss",
        "author": "Arbitrage Andy",
        "content": "The Fed's recent rhetoric shift represents a phase transition in monetary policy. Watch for increased volatility as markets adjust to new regime. Key catalysts: CPI (2/28), FOMC minutes (3/7).",
        "timestamp": (datetime.now() - timedelta(hours=5)).isoformat(),
        "url": "https://arbitrageandy.substack.com/p/fed-pivot-analysis"
    },
    {
        "source": "twitter",
        "author": "@DeItaone",
        "content": "OPEC+ considering deeper production cuts amid demand concerns from China slowdown. Saudi energy minister to hold press conference tomorrow.",
        "timestamp": (datetime.now() - timedelta(hours=4)).isoformat(),
        "url": "https://twitter.com/DeItaone/status/12347"
    },
    {
        "source": "twitter",
        "author": "@carlquintanilla",
        "content": "Tech earnings season: NVDA +15% after hours, MSFT guidance cautious. Rotation from growth to quality continues. Sector showing divergence.",
        "timestamp": (datetime.now() - timedelta(hours=1)).isoformat(),
        "url": "https://twitter.com/carlquintanilla/status/12348"
    },
    {
        "source": "rss",
        "author": "Doomberg",
        "content": "Oil markets facing structural uncertainty. Supply disruptions from Middle East vs. demand destruction from Europe/China. Entropy at decade highs.",
        "timestamp": (datetime.now() - timedelta(hours=6)).isoformat(),
        "url": "https://doomberg.substack.com/p/oil-uncertainty"
    },
    {
        "source": "twitter",
        "author": "@lisaabramowicz1",
        "content": "Credit markets flashing warning signals. High-yield spreads widening despite equity rally. Classic divergence pattern seen before 2018 correction.",
        "timestamp": (datetime.now() - timedelta(hours=7)).isoformat(),
        "url": "https://twitter.com/lisaabramowicz1/status/12349"
    }
]

# Demo output: Sample AI-generated narratives
DEMO_NARRATIVES = [
    {
        "title": "Fed Monetary Policy Pivot Accelerating",
        "entropy_risk": 3,
        "hypothesis": "Long QQQ calls (March 500 strike), 2-3 week timeframe, 2% portfolio allocation",
        "rationale": "Multiple high-quality sources (Fed official commentary, options flow, Substack analysis) converge on dovish shift narrative. Low entropy indicates stable consensus. Unusual options activity ($50M QQQ calls) suggests institutional positioning for tech rally. Risk/reward favorable with defined catalysts.",
        "catalysts": [
            "CPI data release (February 28)",
            "FOMC minutes publication (March 7)",
            "Powell testimony (March 14)"
        ],
        "supporting_feeds": ["@zerohedge", "@unusual_whales", "Arbitrage Andy"],
        "physics_analogy": "System approaching stable equilibrium after period of perturbation (rate hiking cycle). Lower entropy = higher predictability."
    },
    {
        "title": "Oil Market Structural Uncertainty",
        "entropy_risk": 8,
        "hypothesis": "Short XLE (energy ETF), hedge with long USO calls (lottery ticket on supply shock), 1% position size",
        "rationale": "Conflicting signals create high entropy environment: OPEC+ supply cuts vs. China demand concerns vs. Middle East geopolitical risk. Multiple equilibria possible. High volatility expected but direction unclear. Best approach: short the sector, hedge tail risk with options.",
        "catalysts": [
            "OPEC+ meeting (March 5)",
            "China PMI data (March 1)",
            "Saudi press conference (tomorrow)"
        ],
        "supporting_feeds": ["@DeItaone", "Doomberg"],
        "physics_analogy": "Unstable equilibrium - small perturbations can trigger large moves in either direction. Maximum entropy = maximum uncertainty."
    },
    {
        "title": "Tech Sector Quality Rotation",
        "entropy_risk": 5,
        "hypothesis": "Long NVDA/MSFT (winners), avoid unprofitable tech. Pairs trade: Long mega-cap vs. short ARK Innovation",
        "rationale": "Mixed signals (medium entropy): Strong earnings from NVDA but cautious guidance from MSFT. Market showing divergence between quality (profitable, strong balance sheets) and growth (unprofitable, high P/E). Flight to quality typical in late cycle. Credit market divergence supports defensive positioning.",
        "catalysts": [
            "Remaining tech earnings (through Feb 25)",
            "Fed guidance on March 7",
            "Credit spread continuation/reversal"
        ],
        "supporting_feeds": ["@carlquintanilla", "@lisaabramowicz1"],
        "physics_analogy": "Phase transition in progress - system moving from high-energy state (growth) to lower-energy state (value/quality). Intermediate entropy during transition."
    }
]

def print_banner():
    """Print formatted banner"""
    print("\n" + "=" * 70)
    print("🔥 REDHOOD INSIGHTS - DEMO MODE")
    print("=" * 70)
    print("This demo shows how RedHood processes feeds into actionable insights")
    print("No API keys required - using sample data\n")

def print_feeds():
    """Display sample feeds"""
    print("📊 SAMPLE FEEDS (Last 24 Hours)")
    print("-" * 70)
    
    for i, feed in enumerate(DEMO_FEEDS, 1):
        timestamp = datetime.fromisoformat(feed['timestamp'])
        hours_ago = int((datetime.now() - timestamp).total_seconds() / 3600)
        
        print(f"\n[{i}] {feed['source'].upper()} | {feed['author']} | {hours_ago}h ago")
        print(f"    {feed['content'][:200]}...")
        if len(feed['content']) > 200:
            print("    [truncated]")
    
    print("\n" + "-" * 70)
    print(f"Total feeds: {len(DEMO_FEEDS)}")
    print("\n⏳ Processing with Claude AI...\n")

def print_narratives():
    """Display AI-generated narratives"""
    print("=" * 70)
    print("📋 DAILY BRIEF - TOP MARKET NARRATIVES")
    print("=" * 70 + "\n")
    
    for i, narrative in enumerate(DEMO_NARRATIVES, 1):
        # Format entropy risk with emoji
        risk = narrative['entropy_risk']
        if risk <= 3:
            risk_indicator = "🟢 LOW"
        elif risk <= 7:
            risk_indicator = "🟡 MEDIUM"
        else:
            risk_indicator = "🔴 HIGH"
        
        print(f"[{i}] {narrative['title']}")
        print(f"    Entropy Risk: {risk_indicator} ({risk}/10)")
        print(f"    💡 Trade Hypothesis: {narrative['hypothesis']}")
        print(f"    📝 Rationale: {narrative['rationale']}")
        print(f"    📅 Key Catalysts:")
        for catalyst in narrative['catalysts']:
            print(f"       • {catalyst}")
        print(f"    🔬 Physics Analogy: {narrative['physics_analogy']}")
        print(f"    📍 Sources: {', '.join(narrative['supporting_feeds'])}")
        print()

def print_summary_stats():
    """Print summary statistics"""
    print("=" * 70)
    print("📊 SESSION SUMMARY")
    print("=" * 70)
    
    avg_entropy = sum(n['entropy_risk'] for n in DEMO_NARRATIVES) / len(DEMO_NARRATIVES)
    
    print(f"\nFeeds Processed: {len(DEMO_FEEDS)}")
    print(f"Narratives Extracted: {len(DEMO_NARRATIVES)}")
    print(f"Average Entropy Risk: {avg_entropy:.1f}/10")
    print(f"Processing Time: <60 seconds (with Claude API)")
    print(f"\nTime Saved: ~150 minutes (vs. manual aggregation)")
    print(f"Signal Quality: Systematic > ad-hoc scrolling")

def print_next_steps():
    """Print recommended next steps"""
    print("\n" + "=" * 70)
    print("🎯 RECOMMENDED ACTIONS")
    print("=" * 70 + "\n")
    
    print("Based on today's analysis, here's your action plan:\n")
    
    print("1. 🟢 HIGH CONVICTION (Low Entropy)")
    print("   → Execute: Long QQQ calls (March 500s)")
    print("   → Size: 2% of portfolio")
    print("   → Stop loss: -5% on position")
    print("   → Monitor: CPI data (Feb 28)\n")
    
    print("2. 🔴 HIGH RISK (High Entropy)")
    print("   → Monitor: Oil/energy sector (do NOT over-size)")
    print("   → If trading: Small size, defined risk (options only)")
    print("   → Wait for: OPEC clarity (Mar 5)\n")
    
    print("3. 🟡 SELECTIVE (Medium Entropy)")
    print("   → Quality over growth: Favor NVDA/MSFT over speculative tech")
    print("   → Watch: Credit spreads (divergence from equities)")
    print("   → Re-evaluate: After remaining tech earnings\n")

def save_demo_output():
    """Save demo results to JSON"""
    output = {
        "timestamp": datetime.now().isoformat(),
        "demo_mode": True,
        "feeds": DEMO_FEEDS,
        "narratives": DEMO_NARRATIVES,
        "metadata": {
            "total_feeds": len(DEMO_FEEDS),
            "narratives_extracted": len(DEMO_NARRATIVES),
            "avg_entropy_risk": sum(n['entropy_risk'] for n in DEMO_NARRATIVES) / len(DEMO_NARRATIVES),
            "processing_time_seconds": 45
        }
    }
    
    filename = f"demo_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    with open(filename, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"💾 Demo output saved to: {filename}\n")

def main():
    """Run the demo"""
    print_banner()
    input("Press Enter to see sample feeds...\n")
    
    print_feeds()
    input("Press Enter to see AI analysis...\n")
    
    print_narratives()
    input("Press Enter to see summary...\n")
    
    print_summary_stats()
    print_next_steps()
    
    save_demo_output()
    
    print("=" * 70)
    print("✅ DEMO COMPLETE")
    print("=" * 70)
    print("\nTo run with real data:")
    print("1. Get Anthropic API key: https://console.anthropic.com/")
    print("2. Set environment variable: export ANTHROPIC_API_KEY='your-key'")
    print("3. Run: python redhood_aggregator.py\n")
    print("Questions? Email: [your-email@example.com]")
    print("Portfolio: See PRD_RedHood_Insights.md for full documentation\n")

if __name__ == '__main__':
    main()

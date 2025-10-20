#!/usr/bin/env python3
"""
Prepare API files for GitHub Pages deployment.

Creates clean, mobile-friendly endpoints:
- /latest.json - Current currency rates
- /crypto.json - Cryptocurrency data
- /history/1d.json - Last 1 day (Hansha → Bonbast fallback)
- /history/1w.json - Last 1 week (Hansha → Bonbast fallback)
- /history/1m.json - Last 1 month (Hansha → Bonbast fallback)
- /history/1y.json - Last 1 year (Hansha → Bonbast fallback)
- /news.json - Blockchain news
"""

import json
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List


def load_json(filepath):
    """Load JSON file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data, filepath):
    """Save data as JSON file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def fetch_history_for_date(date_str: str) -> Dict[str, Any]:
    """
    Fetch history data for a specific date using bonbast CLI.

    Args:
        date_str: Date string in YYYY-MM-DD format

    Returns:
        Dictionary with date and rates, or None on error
    """
    try:
        from helper import run_bonbast_history

        history_json = await run_bonbast_history(date=date_str)

        if not history_json:
            return None

        history_data = json.loads(history_json)
        return {
            'date': date_str,
            'rates': history_data
        }
    except Exception as e:
        print(f"   ✗ Failed to fetch {date_str}: {e}")
        return None


async def generate_date_range(days: int) -> List[Dict[str, Any]]:
    """
    Generate history data for the last N days.

    Args:
        days: Number of days to fetch (starting from yesterday)

    Returns:
        List of date/rates dictionaries
    """
    history_list = []
    start_date = datetime.now() - timedelta(days=1)

    for i in range(days):
        date_obj = start_date - timedelta(days=i)
        date_str = date_obj.strftime('%Y-%m-%d')

        data = await fetch_history_for_date(date_str)
        if data:
            history_list.append(data)

    history_list.sort(key=lambda x: x['date'], reverse=True)

    return history_list


async def fetch_hansha_historical(period: str, item: str = 'usd') -> Dict[str, Any]:
    """
    Fetch historical data from Hansha API for a specific period.

    Args:
        period: Period name from Hansha API (e.g., 'oneWeek', 'oneMonth', 'all')
        item: Currency code (default: 'usd')

    Returns:
        Historical data dictionary or None on error
    """
    try:
        import aiohttp
        url = f'https://hansha.online/historical?period={period}&item={item}'

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    print(f"   ⚠️  Hansha API returned status {response.status} for {period}")
                    return None
    except Exception as e:
        print(f"   ⚠️  Hansha API failed for {period}: {e}")
        return None


async def generate_bonbast_period_fallback(days: int) -> List[Dict[str, Any]]:
    """
    Generate bonbast history as fallback for a specific period.

    Args:
        days: Number of days to fetch

    Returns:
        List of historical data
    """
    return await generate_date_range(min(days, 90))  


async def generate_period_endpoint(history_dir: Path, period_key: str, period_name: str, days_fallback: int):
    """
    Generate a period-based history endpoint with Hansha primary and bonbast fallback.

    Args:
        history_dir: Directory to save the file
        period_key: Short key (e.g., '1w', '1m', '1y')
        period_name: Hansha API period name (e.g., 'oneWeek', 'oneMonth')
        days_fallback: Number of days to use for bonbast fallback
    """
    print(f"   • Creating /history/{period_key}.json (Hansha: {period_name})")

    hansha_data = await fetch_hansha_historical(period_name, item='usd')

    if hansha_data:
        save_json(hansha_data, history_dir / f'{period_key}.json')
        print(f"     ✓ Success (Hansha)")
    else:
        # Fallback to bonbast
        print(f"     ⚠️  Hansha failed, using bonbast fallback...")
        bonbast_data = await generate_bonbast_period_fallback(days_fallback)
        if bonbast_data:
            save_json(bonbast_data, history_dir / f'{period_key}.json')
            print(f"     ✓ Success (Bonbast fallback)")
        else:
            print(f"     ✗ Failed (both sources)")


async def generate_history_endpoints(api_dir: Path):
    """Generate mobile-friendly history endpoints with Hansha + bonbast fallback."""
    print("\n📅 Generating period-based history endpoints...")

    history_dir = api_dir / 'history'
    history_dir.mkdir(exist_ok=True)

    # Period-based endpoints (Hansha primary, bonbast fallback)
    # Only keep periods where fallback makes sense
    periods = [
        ('1d', 'oneDay', 1),      # Yesterday
        ('1w', 'oneWeek', 7),     # Last week
        ('1m', 'oneMonth', 30),   # Last month
        ('1y', 'oneYear', 90),    # Last year (limit fallback to 90 days)
    ]

    for period_key, period_name, days_fallback in periods:
        await generate_period_endpoint(history_dir, period_key, period_name, days_fallback)


async def async_main():
    """Main execution."""
    print("\n🚀 Preparing API files...\n")

    api_dir = Path('api')
    api_dir.mkdir(exist_ok=True)

    currencies = load_json('data/currencies.json')

    print("   ✓ Creating /latest.json")
    latest_data = currencies.get('hansha_rates') or currencies.get('bonbast', [])
    save_json(latest_data, api_dir / 'latest.json')

    print("   ✓ Creating /crypto.json")
    save_json(currencies.get('crypto', []), api_dir / 'crypto.json')

    print("   ✓ Creating /history.json")
    history_data = currencies.get('hansha_history') or currencies.get('bonbast_history', [])
    save_json(history_data, api_dir / 'history.json')

    # Generate mobile-friendly history endpoints
    await generate_history_endpoints(api_dir)

    news_file = Path('data/news.json')
    if news_file.exists():
        print("   ✓ Creating /news.json")
        news = load_json(news_file)
        save_json(news, api_dir / 'news.json')
    else:
        print("   ⚠️  news.json not found, skipping")

    print("   ✓ Creating /index.html")
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Currency Cap Portal API</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.8;
            color: #1a1a1a;
            background: #fafafa;
            padding: 40px 20px;
        }
        .container {
            max-width: 700px;
            margin: 0 auto;
        }
        h1 {
            font-size: 2em;
            margin-bottom: 8px;
            font-weight: 600;
        }
        .subtitle {
            color: #666;
            margin-bottom: 40px;
            font-size: 1.1em;
        }
        h2 {
            font-size: 1.3em;
            margin: 40px 0 20px 0;
            font-weight: 600;
        }
        .endpoint {
            background: white;
            border: 1px solid #e0e0e0;
            padding: 20px;
            margin: 12px 0;
            border-radius: 6px;
        }
        .endpoint h3 {
            font-size: 1em;
            margin-bottom: 6px;
            font-weight: 600;
            color: #0066cc;
        }
        .endpoint p {
            color: #666;
            font-size: 0.95em;
            margin-bottom: 12px;
        }
        .url {
            background: #f5f5f5;
            padding: 10px;
            border-radius: 4px;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.85em;
            word-break: break-all;
            color: #333;
        }
        pre {
            background: #f5f5f5;
            padding: 16px;
            border-radius: 4px;
            overflow-x: auto;
            font-size: 0.85em;
            margin: 12px 0;
            border: 1px solid #e0e0e0;
        }
        .features {
            color: #666;
            line-height: 2;
        }
        footer {
            margin-top: 60px;
            padding-top: 20px;
            border-top: 1px solid #e0e0e0;
            text-align: center;
            color: #999;
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Currency Cap Portal</h1>
        <p class="subtitle">Free Currency & Crypto API</p>

        <h2>Endpoints</h2>

        <div class="endpoint">
            <h3>GET /latest.json</h3>
            <p>Current Iranian currency exchange rates (Hansha with icons and full details)</p>
            <div class="url">https://linx64.github.io/CurrencyCapPortal/latest.json</div>
        </div>

        <div class="endpoint">
            <h3>GET /history/1d.json</h3>
            <p>Yesterday's rates (Hansha → Bonbast fallback)</p>
            <div class="url">https://linx64.github.io/CurrencyCapPortal/history/1d.json</div>
        </div>

        <div class="endpoint">
            <h3>GET /history/1w.json</h3>
            <p>Last week's rates (Hansha → Bonbast fallback)</p>
            <div class="url">https://linx64.github.io/CurrencyCapPortal/history/1w.json</div>
        </div>

        <div class="endpoint">
            <h3>GET /history/1m.json</h3>
            <p>Last month's rates (Hansha → Bonbast fallback)</p>
            <div class="url">https://linx64.github.io/CurrencyCapPortal/history/1m.json</div>
        </div>

        <div class="endpoint">
            <h3>GET /history/1y.json</h3>
            <p>Last year's rates (Hansha → Bonbast fallback)</p>
            <div class="url">https://linx64.github.io/CurrencyCapPortal/history/1y.json</div>
        </div>

        <div class="endpoint">
            <h3>GET /crypto.json</h3>
            <p>Top 100 cryptocurrencies by market cap</p>
            <div class="url">https://linx64.github.io/CurrencyCapPortal/crypto.json</div>
        </div>

        <div class="endpoint">
            <h3>GET /news.json</h3>
            <p>Latest blockchain news articles</p>
            <div class="url">https://linx64.github.io/CurrencyCapPortal/news.json</div>
        </div>

        <h2>Usage Examples</h2>

        <p><strong>Latest Rates</strong></p>
        <pre>const rates = await fetch('https://linx64.github.io/CurrencyCapPortal/latest.json')
  .then(res => res.json());</pre>

        <p><strong>Period-Based History (Mobile-Friendly!)</strong></p>
        <pre>// Get last week - perfect for mobile apps!
const weekData = await fetch('https://linx64.github.io/CurrencyCapPortal/history/1w.json')
  .then(res => res.json());

// Get last month for charts
const monthData = await fetch('https://linx64.github.io/CurrencyCapPortal/history/1m.json')
  .then(res => res.json());

// Get last year for trends
const yearData = await fetch('https://linx64.github.io/CurrencyCapPortal/history/1y.json')
  .then(res => res.json());

// Available periods: 1d, 1w, 1m, 1y</pre>

        <p><strong>Perfect for Mobile Apps</strong></p>
        <pre>✓ No date calculations needed
✓ Simple, clean URLs (1d, 1w, 1m, 1y)
✓ Hansha → Bonbast auto-fallback
✓ Auto-updated every 6 hours
✓ Works with React Native, Flutter, Swift, Kotlin</pre>

        <h2>Features</h2>
        <div class="features">
        • Auto-updates every 6 hours<br>
        • Free, no rate limits<br>
        • CORS enabled<br>
        • Powered by GitHub Pages
        </div>

        <footer>
            Built with GitHub Actions
        </footer>
    </div>
</body>
</html>"""

    with open(api_dir / 'index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print("\n✅ API preparation complete!\n")


def main():
    """Wrapper to run async main."""
    asyncio.run(async_main())


if __name__ == '__main__':
    main()

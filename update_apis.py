#!/usr/bin/env python3
"""
Update all API endpoints for Currency Cap Portal.

Generates 7 API endpoints with smart caching (runs every 5 minutes):
- /latest.json - Current Iranian currency rates (Hansha with full details)
- /history/1d.json - Yesterday's rates (Hansha → Bonbast fallback)
- /history/1w.json - Last week's rates (Hansha → Bonbast fallback)
- /history/1m.json - Last month's rates (Hansha → Bonbast fallback)
- /history/1y.json - Last year's rates (Hansha → Bonbast fallback)
- /crypto.json - Top 100 cryptocurrencies by market cap
- /news.json - Latest blockchain news articles

Each endpoint has its own cache with appropriate expiry times.
"""

import asyncio
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import aiohttp
from dotenv import load_dotenv

from helper import (
    fetch,
    run_bonbast_history,
    fetch_hansha_latest,
    fetch_all_currencies_historical,
    generate_bonbast_period_fallback
)

load_dotenv()
news_api_key = os.getenv('NEWS_API_KEY')

# Cache directory
CACHE_DIR = Path('cache')
CACHE_DIR.mkdir(exist_ok=True)

# API output directory
API_DIR = Path('api')
API_DIR.mkdir(exist_ok=True)

# Cache expiry times (in minutes)
CACHE_EXPIRY = {
    'latest': 5,      # 5 minutes (matches update frequency)
    '1d': 60,         # 1 hour (historical data changes less frequently)
    '1w': 360,        # 6 hours
    '1m': 720,        # 12 hours
    '1y': 1440,       # 24 hours
    'crypto': 5,      # 5 minutes
    'news': 60        # 1 hour
}


def load_cache(endpoint: str) -> Optional[Dict[str, Any]]:
    """
    Load cached data for an endpoint if it exists and is not expired.

    Args:
        endpoint: Endpoint name (e.g., 'latest', '1d', 'crypto')

    Returns:
        Cached data or None if expired/missing
    """
    cache_file = CACHE_DIR / f'{endpoint}.json'

    if not cache_file.exists():
        return None

    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)

        cache_time = datetime.fromisoformat(cache_data['cached_at'])
        age_minutes = (datetime.now() - cache_time).total_seconds() / 60
        expiry = CACHE_EXPIRY.get(endpoint, 60)

        if age_minutes < expiry:
            print(f"   ✓ Using cached {endpoint} ({age_minutes:.1f}min old, expires in {expiry - age_minutes:.1f}min)")
            return cache_data['data']
        else:
            print(f"   ⚠ Cache expired for {endpoint} ({age_minutes:.1f}min old, limit {expiry}min)")
            return None
    except Exception as e:
        print(f"   ✗ Failed to load cache for {endpoint}: {e}")
        return None


def save_cache(endpoint: str, data: Any) -> None:
    """
    Save data to cache with timestamp.

    Args:
        endpoint: Endpoint name
        data: Data to cache
    """
    try:
        cache_file = CACHE_DIR / f'{endpoint}.json'
        cache_data = {
            'cached_at': datetime.now().isoformat(),
            'data': data
        }
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"   ⚠ Failed to save cache for {endpoint}: {e}")


def save_api_endpoint(endpoint_path: str, data: Any) -> None:
    """
    Save data to API directory.

    Args:
        endpoint_path: Path relative to api/ (e.g., 'latest.json', 'history/1d.json')
        data: Data to save
    """
    output_file = API_DIR / endpoint_path
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"   ✓ Saved {endpoint_path}")


async def fetch_news() -> Optional[List[Dict[str, Any]]]:
    """
    Fetch latest blockchain news from NewsAPI.

    Returns:
        News articles or None on error
    """
    if not news_api_key:
        print("   ⚠ NEWS_API_KEY not set, skipping news")
        return None

    url = f'https://newsapi.org/v2/everything?q=blockchain&apiKey={news_api_key}&pageSize=20&sortBy=publishedAt'

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    news_data = await response.json()
                    return news_data.get('articles', [])
                else:
                    print(f"   ✗ News API returned status {response.status}")
                    return None
    except Exception as e:
        print(f"   ✗ Failed to fetch news: {e}")
        return None


async def update_latest():
    """Update /latest.json endpoint."""
    print("\n📊 Updating /latest.json...")

    # Check cache first
    cached = load_cache('latest')
    if cached:
        save_api_endpoint('latest.json', cached)
        return

    # Fetch fresh data from Hansha
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = await fetch('https://hansha.online/latest', session)

            if data and not isinstance(data, dict) or not data.get('error'):
                save_cache('latest', data)
                save_api_endpoint('latest.json', data)
                print(f"   ✓ Fetched fresh data from Hansha")
            else:
                print(f"   ✗ Failed to fetch from Hansha: {data.get('error') if isinstance(data, dict) else 'Unknown error'}")
    except Exception as e:
        print(f"   ✗ Error fetching latest: {e}")


async def update_history_period(period_key: str, period_name: str, days_fallback: int, currencies: List[str]):
    """
    Update a history period endpoint with Hansha → Bonbast fallback.

    Args:
        period_key: Short key (e.g., '1d', '1w', '1m', '1y')
        period_name: Hansha API period name (e.g., 'latest', 'oneWeek', 'oneMonth', 'oneYear')
        days_fallback: Number of days for Bonbast fallback
        currencies: List of currency codes to fetch
    """
    print(f"\n📅 Updating /history/{period_key}.json...")

    # Check cache first
    cached = load_cache(period_key)
    if cached:
        save_api_endpoint(f'history/{period_key}.json', cached)
        return

    # Fetch fresh data from Hansha
    try:
        if period_name == 'latest':
            # For 1d, use /latest endpoint which has 24h data
            hansha_data = await fetch_hansha_latest()
        else:
            # For other periods, fetch historical data
            hansha_data = await fetch_all_currencies_historical(period_name, currencies)

        if hansha_data and len(hansha_data) > 0:
            save_cache(period_key, hansha_data)
            save_api_endpoint(f'history/{period_key}.json', hansha_data)
            print(f"   ✓ Fetched from Hansha ({len(hansha_data)} currencies)")
        else:
            # Fallback to Bonbast
            print(f"   ⚠ Hansha failed, using Bonbast fallback...")
            bonbast_data = await generate_bonbast_period_fallback(days_fallback)

            if bonbast_data:
                save_cache(period_key, bonbast_data)
                save_api_endpoint(f'history/{period_key}.json', bonbast_data)
                print(f"   ✓ Fetched from Bonbast fallback ({len(bonbast_data)} days)")
            else:
                print(f"   ✗ Both Hansha and Bonbast failed")
    except Exception as e:
        print(f"   ✗ Error updating history/{period_key}: {e}")


async def update_crypto():
    """Update /crypto.json endpoint."""
    print("\n💰 Updating /crypto.json...")

    # Check cache first
    cached = load_cache('crypto')
    if cached:
        save_api_endpoint('crypto.json', cached)
        return

    # Fetch fresh data from CoinGecko
    try:
        url = 'https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1&sparkline=false'
        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = await fetch(url, session)

            if data and isinstance(data, list):
                save_cache('crypto', data)
                save_api_endpoint('crypto.json', data)
                print(f"   ✓ Fetched {len(data)} cryptocurrencies from CoinGecko")
            else:
                print(f"   ✗ Failed to fetch from CoinGecko")
    except Exception as e:
        print(f"   ✗ Error fetching crypto: {e}")


async def update_news():
    """Update /news.json endpoint."""
    print("\n📰 Updating /news.json...")

    # Check cache first
    cached = load_cache('news')
    if cached:
        save_api_endpoint('news.json', cached)
        return

    # Fetch fresh news
    news_data = await fetch_news()

    if news_data:
        save_cache('news', news_data)
        save_api_endpoint('news.json', news_data)
        print(f"   ✓ Fetched {len(news_data)} news articles")
    else:
        print(f"   ✗ Failed to fetch news")


async def get_currency_list() -> List[str]:
    """
    Get list of currency codes from latest Hansha data.

    Returns:
        List of currency codes
    """
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = await fetch('https://hansha.online/latest', session)

            if data and isinstance(data, list):
                return [item.get('ab') for item in data if item.get('ab')]
    except Exception as e:
        print(f"   ⚠ Failed to get currency list: {e}")

    # Fallback to common currencies
    return ['usd', 'eur', 'gbp', 'chf', 'cad', 'aud', 'jpy', 'cny', 'try', 'rub']


async def main():
    """Main execution."""
    print("=" * 60)
    print("🚀 Currency Cap Portal - API Update")
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Get list of currencies for historical data
    currencies = await get_currency_list()
    print(f"\n📋 Found {len(currencies)} currencies: {', '.join(currencies[:5])}...")

    # Update all endpoints concurrently
    await asyncio.gather(
        update_latest(),
        update_crypto(),
        update_news(),
        update_history_period('1d', 'latest', 1, currencies),
        update_history_period('1w', 'oneWeek', 7, currencies),
        update_history_period('1m', 'oneMonth', 30, currencies),
        update_history_period('1y', 'oneYear', 90, currencies),
    )

    print("\n" + "=" * 60)
    print("✅ All API endpoints updated successfully!")
    print(f"⏰ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60 + "\n")


if __name__ == '__main__':
    asyncio.run(main())

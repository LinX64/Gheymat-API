import os
import aiohttp
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

from helper import (
    fetch,
    fetch_hansha_latest,
    fetch_all_currencies_historical,
    generate_bonbast_period_fallback
)
from cache import load_cache, save_cache, save_api_endpoint

# Import enhanced data sources
try:
    from enhanced_data_sources import fetch_all_enhanced_data
    ENHANCED_DATA_AVAILABLE = True
except ImportError:
    ENHANCED_DATA_AVAILABLE = False
    print("   ⚠ Enhanced data sources not available, using basic fetching")

load_dotenv()
news_api_key = os.getenv('NEWS_API_KEY')


async def fetch_news() -> Optional[List[Dict[str, Any]]]:
    """Fetch news using enhanced multi-source aggregator or fallback to basic"""
    if not news_api_key:
        print("   ⚠ NEWS_API_KEY not set, skipping news")
        return None

    # Try enhanced news fetching first
    if ENHANCED_DATA_AVAILABLE:
        try:
            print("   🔍 Using enhanced news aggregator...")
            enhanced_data = await fetch_all_enhanced_data()
            if enhanced_data and 'news' in enhanced_data:
                return enhanced_data['news']
        except Exception as e:
            print(f"   ⚠ Enhanced news fetch failed, falling back to basic: {e}")

    # Fallback to basic blockchain news
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
    print("\n📊 Updating /latest.json...")

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = await fetch('https://hansha.online/latest', session)

            if data and not isinstance(data, dict) or not data.get('error'):
                save_cache('latest', data)
                save_api_endpoint('latest.json', data)
                print(f"   ✓ Fetched fresh data from Hansha")
                return
            else:
                print(f"   ✗ Hansha failed: {data.get('error') if isinstance(data, dict) else 'Unknown error'}")
    except Exception as e:
        print(f"   ✗ Error fetching from Hansha: {e}")

    cached = load_cache('latest')
    if cached:
        save_api_endpoint('latest.json', cached)
        print(f"   ⚠ Using cached data as fallback")
    else:
        print(f"   ✗ No cached data available")


async def update_history_period(period_key: str, period_name: str, days_fallback: int, currencies: List[str]):
    print(f"\n📅 Updating /history/{period_key}.json...")

    try:
        if period_name == 'latest':
            hansha_data = await fetch_hansha_latest()
        else:
            hansha_data = await fetch_all_currencies_historical(period_name, currencies)

        if hansha_data and len(hansha_data) > 0:
            save_cache(period_key, hansha_data)
            save_api_endpoint(f'history/{period_key}.json', hansha_data)
            print(f"   ✓ Fetched from Hansha ({len(hansha_data)} currencies)")
            return
        else:
            print(f"   ⚠ Hansha failed, trying Bonbast...")
    except Exception as e:
        print(f"   ✗ Hansha error: {e}")

    try:
        bonbast_data = await generate_bonbast_period_fallback(days_fallback)
        if bonbast_data:
            save_cache(period_key, bonbast_data)
            save_api_endpoint(f'history/{period_key}.json', bonbast_data)
            print(f"   ✓ Fetched from Bonbast ({len(bonbast_data)} days)")
            return
        else:
            print(f"   ✗ Bonbast failed")
    except Exception as e:
        print(f"   ✗ Bonbast error: {e}")

    cached = load_cache(period_key)
    if cached:
        save_api_endpoint(f'history/{period_key}.json', cached)
        print(f"   ⚠ Using cached data as fallback")
    else:
        print(f"   ✗ No cached data available")


async def update_crypto():
    print("\n💰 Updating /crypto.json...")

    try:
        url = 'https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1&sparkline=false'
        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = await fetch(url, session)

            if data and isinstance(data, list):
                save_cache('crypto', data)
                save_api_endpoint('crypto.json', data)
                print(f"   ✓ Fetched {len(data)} cryptocurrencies from CoinGecko")
                return
            else:
                print(f"   ✗ CoinGecko failed")
    except Exception as e:
        print(f"   ✗ Error fetching from CoinGecko: {e}")

    cached = load_cache('crypto')
    if cached:
        save_api_endpoint('crypto.json', cached)
        print(f"   ⚠ Using cached data as fallback")
    else:
        print(f"   ✗ No cached data available")


async def update_news():
    print("\n📰 Updating /news.json...")

    news_data = await fetch_news()

    if news_data:
        save_cache('news', news_data)
        save_api_endpoint('news.json', news_data)
        print(f"   ✓ Fetched {len(news_data)} news articles")
        return

    cached = load_cache('news')
    if cached:
        save_api_endpoint('news.json', cached)
        print(f"   ⚠ Using cached data as fallback")
    else:
        print(f"   ✗ No cached data available")


async def update_economic_indicators():
    """Update economic indicators (oil, gold, sanctions data)"""
    print("\n📈 Updating /economic_indicators.json...")

    if not ENHANCED_DATA_AVAILABLE:
        print("   ⚠ Enhanced data sources not available, skipping economic indicators")
        return

    try:
        enhanced_data = await fetch_all_enhanced_data()
        if enhanced_data and 'economic_indicators' in enhanced_data:
            indicators = enhanced_data['economic_indicators']
            save_cache('economic_indicators', indicators)
            save_api_endpoint('economic_indicators.json', indicators)
            print(f"   ✓ Fetched economic indicators")
            print(f"      - Oil prices: {indicators.get('oil', {}).get('source', 'N/A')}")
            print(f"      - Gold prices: {indicators.get('gold', {}).get('source', 'N/A')}")
            print(f"      - Sanctions level: {indicators.get('sanctions', {}).get('iran_sanctions_level', 'N/A')}")
            return
    except Exception as e:
        print(f"   ✗ Failed to fetch economic indicators: {e}")

    cached = load_cache('economic_indicators')
    if cached:
        save_api_endpoint('economic_indicators.json', cached)
        print(f"   ⚠ Using cached data as fallback")
    else:
        print(f"   ✗ No cached data available")


async def get_currency_list() -> List[str]:
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = await fetch('https://hansha.online/latest', session)

            if data and isinstance(data, list):
                return [item.get('ab') for item in data if item.get('ab')]
    except Exception as e:
        print(f"   ⚠ Failed to get currency list: {e}")

    return ['usd', 'eur', 'gbp', 'chf', 'cad', 'aud', 'jpy', 'cny', 'try', 'rub']

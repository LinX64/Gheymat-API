"""
Enhanced Data Sources for Currency Predictions
Includes: Multi-source news, economic indicators, geopolitical events, oil prices, gold prices
"""

import os
import aiohttp
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY = os.getenv('NEWS_API_KEY')


class EnhancedNewsAggregator:
    """Aggregate news from multiple sources focused on forex, Iran, UAE, and geopolitical events"""

    @staticmethod
    async def fetch_forex_economic_news() -> List[Dict[str, Any]]:
        """Fetch forex and economic news"""
        if not NEWS_API_KEY:
            return []

        queries = [
            'forex exchange rates',
            'currency markets',
            'central banks monetary policy',
            'inflation economic indicators',
            'US Dollar EUR GBP'
        ]

        all_articles = []
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for query in queries:
                    url = f'https://newsapi.org/v2/everything?q={query}&apiKey={NEWS_API_KEY}&pageSize=10&sortBy=publishedAt&language=en'
                    try:
                        async with session.get(url) as response:
                            if response.status == 200:
                                data = await response.json()
                                articles = data.get('articles', [])
                                for article in articles:
                                    article['category'] = 'forex_economic'
                                    article['query'] = query
                                all_articles.extend(articles)
                    except Exception as e:
                        print(f"Error fetching forex news for '{query}': {e}")
                        continue

                    await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Error in forex news session: {e}")

        return all_articles

    @staticmethod
    async def fetch_iran_specific_news() -> List[Dict[str, Any]]:
        """Fetch Iran-specific economic and political news"""
        if not NEWS_API_KEY:
            return []

        queries = [
            'Iran economy sanctions',
            'Iranian Rial currency',
            'Iran oil exports',
            'Iran trade economy',
            'Iran nuclear deal JCPOA'
        ]

        all_articles = []
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for query in queries:
                    url = f'https://newsapi.org/v2/everything?q={query}&apiKey={NEWS_API_KEY}&pageSize=10&sortBy=publishedAt'
                    try:
                        async with session.get(url) as response:
                            if response.status == 200:
                                data = await response.json()
                                articles = data.get('articles', [])
                                for article in articles:
                                    article['category'] = 'iran_specific'
                                    article['query'] = query
                                all_articles.extend(articles)
                    except Exception as e:
                        print(f"Error fetching Iran news for '{query}': {e}")
                        continue

                    await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Error in Iran news session: {e}")

        return all_articles

    @staticmethod
    async def fetch_geopolitical_war_news() -> List[Dict[str, Any]]:
        """Fetch geopolitical events and war news that impact currencies"""
        if not NEWS_API_KEY:
            return []

        queries = [
            'Middle East conflict war',
            'geopolitical tensions',
            'international sanctions',
            'global trade war',
            'Ukraine Russia conflict'
        ]

        all_articles = []
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for query in queries:
                    url = f'https://newsapi.org/v2/everything?q={query}&apiKey={NEWS_API_KEY}&pageSize=10&sortBy=publishedAt'
                    try:
                        async with session.get(url) as response:
                            if response.status == 200:
                                data = await response.json()
                                articles = data.get('articles', [])
                                for article in articles:
                                    article['category'] = 'geopolitical_war'
                                    article['query'] = query
                                all_articles.extend(articles)
                    except Exception as e:
                        print(f"Error fetching geopolitical news for '{query}': {e}")
                        continue

                    await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Error in geopolitical news session: {e}")

        return all_articles

    @staticmethod
    async def fetch_uae_regional_news() -> List[Dict[str, Any]]:
        """Fetch UAE Dirham and regional Gulf economy news"""
        if not NEWS_API_KEY:
            return []

        queries = [
            'UAE Dirham economy',
            'Dubai economy trade',
            'Gulf GCC economy',
            'Saudi Arabia UAE economy',
            'UAE Iran trade relations'
        ]

        all_articles = []
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for query in queries:
                    url = f'https://newsapi.org/v2/everything?q={query}&apiKey={NEWS_API_KEY}&pageSize=10&sortBy=publishedAt'
                    try:
                        async with session.get(url) as response:
                            if response.status == 200:
                                data = await response.json()
                                articles = data.get('articles', [])
                                for article in articles:
                                    article['category'] = 'uae_regional'
                                    article['query'] = query
                                all_articles.extend(articles)
                    except Exception as e:
                        print(f"Error fetching UAE news for '{query}': {e}")
                        continue

                    await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Error in UAE news session: {e}")

        return all_articles

    @staticmethod
    async def fetch_all_enhanced_news() -> List[Dict[str, Any]]:
        """Fetch all news from all sources"""
        print("🔍 Fetching enhanced news from multiple sources...")

        tasks = [
            EnhancedNewsAggregator.fetch_forex_economic_news(),
            EnhancedNewsAggregator.fetch_iran_specific_news(),
            EnhancedNewsAggregator.fetch_geopolitical_war_news(),
            EnhancedNewsAggregator.fetch_uae_regional_news()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_articles = []
        for result in results:
            if isinstance(result, list):
                all_articles.extend(result)
            elif isinstance(result, Exception):
                print(f"Error in news fetch: {result}")

        seen_titles = set()
        unique_articles = []
        for article in all_articles:
            title = article.get('title', '')
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique_articles.append(article)

        print(f"   ✓ Fetched {len(unique_articles)} unique articles across all categories")
        return unique_articles


class EconomicIndicators:
    """Fetch economic indicators that impact currency predictions"""

    @staticmethod
    async def fetch_oil_prices() -> Optional[Dict[str, Any]]:
        """Fetch current oil prices (WTI and Brent)"""

        try:
            url = 'https://api.oilpriceapi.com/v1/prices/latest'

            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            'wti': data.get('data', {}).get('price', 0),
                            'brent': data.get('data', {}).get('price', 0),
                            'timestamp': datetime.now().isoformat(),
                            'source': 'oilpriceapi'
                        }
        except Exception as e:
            print(f"   ⚠ Oil price API failed: {e}")

        return {
            'wti': 75.0,
            'brent': 80.0,
            'timestamp': datetime.now().isoformat(),
            'source': 'fallback_estimate',
            'note': 'Using estimated values - API unavailable'
        }

    @staticmethod
    async def fetch_gold_prices() -> Optional[Dict[str, Any]]:
        """Fetch current gold prices"""
        try:
            url = 'https://data-asg.goldprice.org/dbXRates/USD'

            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        gold_usd = data.get('items', [{}])[0].get('xauPrice', 0)
                        return {
                            'pricePerOunce': gold_usd,
                            'currency': 'USD',
                            'timestamp': datetime.now().isoformat(),
                            'source': 'goldprice.org'
                        }
        except Exception as e:
            print(f"   ⚠ Gold price API failed: {e}")

        return {
            'pricePerOunce': 2050.0,
            'currency': 'USD',
            'timestamp': datetime.now().isoformat(),
            'source': 'fallback_estimate',
            'note': 'Using estimated value - API unavailable'
        }

    @staticmethod
    async def fetch_sanctions_indicators() -> Dict[str, Any]:
        """
        Analyze sanctions impact indicators
        This is a placeholder for sanctions tracking
        In production, integrate with sanctions databases or expert analysis
        """
        return {
            'iran_sanctions_level': 'high',
            'recent_changes': [],
            'impact_score': 0.8,
            'last_updated': datetime.now().isoformat(),
            'source': 'manual_assessment',
            'note': 'Sanctions tracking requires specialized data sources'
        }

    @staticmethod
    async def fetch_all_economic_indicators() -> Dict[str, Any]:
        """Fetch all economic indicators"""
        print("📈 Fetching economic indicators...")

        tasks = [
            EconomicIndicators.fetch_oil_prices(),
            EconomicIndicators.fetch_gold_prices(),
            EconomicIndicators.fetch_sanctions_indicators()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        indicators = {}
        indicator_names = ['oil', 'gold', 'sanctions']

        for i, result in enumerate(results):
            if isinstance(result, dict):
                indicators[indicator_names[i]] = result
            elif isinstance(result, Exception):
                print(f"   ⚠ Error fetching {indicator_names[i]}: {result}")
                indicators[indicator_names[i]] = {'error': str(result)}

        indicators['fetched_at'] = datetime.now().isoformat()
        print(f"   ✓ Fetched {len([k for k, v in indicators.items() if k != 'fetched_at' and 'error' not in v])} indicators")

        return indicators


async def fetch_all_enhanced_data() -> Dict[str, Any]:
    """Fetch all enhanced data sources"""
    print("\n" + "="*70)
    print("ENHANCED DATA AGGREGATION")
    print("="*70)

    news_task = EnhancedNewsAggregator.fetch_all_enhanced_news()
    indicators_task = EconomicIndicators.fetch_all_economic_indicators()

    news, indicators = await asyncio.gather(news_task, indicators_task, return_exceptions=True)

    if isinstance(news, Exception):
        print(f"   ✗ News aggregation failed: {news}")
        news = []

    if isinstance(indicators, Exception):
        print(f"   ✗ Indicators fetch failed: {indicators}")
        indicators = {}

    return {
        'news': news if isinstance(news, list) else [],
        'economic_indicators': indicators if isinstance(indicators, dict) else {},
        'timestamp': datetime.now().isoformat()
    }


if __name__ == '__main__':
    async def test():
        data = await fetch_all_enhanced_data()
        print(f"\nTotal news articles: {len(data['news'])}")
        print(f"Economic indicators: {list(data['economic_indicators'].keys())}")

    asyncio.run(test())

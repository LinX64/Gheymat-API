import asyncio
import json
import os
import subprocess
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from aiohttp import ClientSession
from dotenv import load_dotenv
from APIs import APIs

load_dotenv()
news_api_key = os.getenv('NEWS_API_KEY')

CACHE_FILE = 'data/currencies_cache.json'
CACHE_EXPIRY_HOURS = 24  # Use cache if data is less than 24 hours old


async def fetch(url, session, retries=15, delay=10):
    if not isinstance(url, str):
        return {"error": "URL must be a string", "status_code": 400}

    for attempt in range(retries):
        try:
            async with session.get(url) as response:
                if response.status == 429:
                    await asyncio.sleep(delay)
                    continue
                elif response.status == 404:
                    await asyncio.sleep(delay)
                    continue
                elif response.status != 200:
                    return {"error": f"Error {response.status} from {url}", "status_code": response.status}
                try:
                    data = await response.json()
                    return data
                except aiohttp.ContentTypeError:
                    return {"error": "Invalid response format", "status_code": response.status}
        except (aiohttp.ClientConnectorError, aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f"Network error on attempt {attempt + 1}/{retries} for {url}: {str(e)}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)
                continue
            else:
                return {"error": f"Network error: {str(e)}", "status_code": 503}
    return {"error": f"Failed to fetch from {url} after {retries} retries", "status_code": 404}


async def run_bonbast():
    try:
        process = await asyncio.create_subprocess_exec(
            'bonbast', 'export',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            print(f"Error occurred in running bonbast command: {stderr.decode()}")
            return None

        return stdout.decode()
    except (subprocess.CalledProcessError, FileNotFoundError, Exception) as e:
        print(f"Error occurred in running bonbast command: {e}")
        return None


async def run_bonbast_history():
    try:
        process = await asyncio.create_subprocess_exec(
            'bonbast', 'history', '--json',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            print(f"Error occurred in running bonbast history command: {stderr.decode()}")
            return None

        return stdout.decode()
    except (subprocess.CalledProcessError, FileNotFoundError, Exception) as e:
        print(f"Error occurred in running bonbast history command: {e}")
        return None


def save_cache(data: Dict[str, Any]) -> None:
    """Save data to cache file with timestamp"""
    try:
        os.makedirs('data', exist_ok=True)
        cache_data = {
            'timestamp': datetime.now().isoformat(),
            'data': data
        }
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
        print(f"Cache saved successfully at {cache_data['timestamp']}")
    except Exception as e:
        print(f"Failed to save cache: {e}")


def load_cache() -> Optional[Dict[str, Any]]:
    """Load data from cache if it exists and is not too old"""
    try:
        if not os.path.exists(CACHE_FILE):
            print("No cache file found")
            return None

        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)

        cache_time = datetime.fromisoformat(cache_data['timestamp'])
        age = datetime.now() - cache_time

        if age > timedelta(hours=CACHE_EXPIRY_HOURS):
            print(f"Cache is too old ({age.total_seconds() / 3600:.1f} hours), ignoring")
            return None

        print(f"Using cache from {cache_time} ({age.total_seconds() / 60:.1f} minutes ago)")
        return cache_data['data']
    except Exception as e:
        print(f"Failed to load cache: {e}")
        return None


def combine_data(hansha_rates, cryptos, bonbast, hansha_history, bonbast_history, sources_status):
    """Combine data from all sources with status tracking"""
    data = {
        'sources_status': sources_status,
        'last_updated': datetime.now().isoformat(),
        'hansha_rates': hansha_rates,
        'hansha_history': hansha_history,
        'bonbast_history': bonbast_history,
        'crypto': cryptos,
        'bonbast': bonbast
    }
    return data


async def aggregator():
    """
    Aggregate data from multiple sources with resilience:
    - Continues even if some sources fail
    - Uses cache as fallback when all sources fail
    - Tracks health status of each source
    """
    sources_status = {
        'hansha': {'status': 'unknown', 'error': None},
        'hansha_history': {'status': 'unknown', 'error': None},
        'crypto': {'status': 'unknown', 'error': None},
        'bonbast': {'status': 'unknown', 'error': None},
        'bonbast_history': {'status': 'unknown', 'error': None}
    }

    hansha_rates = None
    hansha_history = None
    bonbast_history = None
    cryptos = []
    bonbast = []

    timeout = aiohttp.ClientTimeout(total=60, connect=30, sock_read=30)

    try:
        async with ClientSession(timeout=timeout) as session:
            # Fetch Hansha rates
            print("Fetching Hansha rates...")
            hansha_result = await fetch(APIs.HANSHA_LATEST.url, session)
            if isinstance(hansha_result, dict) and hansha_result.get('error'):
                sources_status['hansha']['status'] = 'failed'
                sources_status['hansha']['error'] = hansha_result.get('error')
                print(f"Hansha failed: {hansha_result.get('error')}")
            else:
                hansha_rates = hansha_result
                sources_status['hansha']['status'] = 'success'
                print("Hansha rates fetched successfully")

            # Fetch Hansha history
            print("Fetching Hansha history...")
            hansha_history_result = await fetch(APIs.HANSHA_HISTORY.url, session)
            if isinstance(hansha_history_result, dict) and hansha_history_result.get('error'):
                sources_status['hansha_history']['status'] = 'failed'
                sources_status['hansha_history']['error'] = hansha_history_result.get('error')
                print(f"Hansha history failed: {hansha_history_result.get('error')}")

                # Fallback to bonbast history
                print("Attempting to fetch Bonbast history as fallback...")
                bonbast_history_result_str = await run_bonbast_history()
                if bonbast_history_result_str:
                    try:
                        bonbast_history = json.loads(bonbast_history_result_str)
                        sources_status['bonbast_history']['status'] = 'success'
                        print(f"Bonbast history fetched successfully as fallback")
                    except json.JSONDecodeError as e:
                        sources_status['bonbast_history']['status'] = 'failed'
                        sources_status['bonbast_history']['error'] = f'JSON decode error: {str(e)}'
                        print(f"Bonbast history JSON decode failed: {e}")
                else:
                    sources_status['bonbast_history']['status'] = 'failed'
                    sources_status['bonbast_history']['error'] = 'Command execution failed'
                    print("Bonbast history command execution failed")
            else:
                hansha_history = hansha_history_result
                sources_status['hansha_history']['status'] = 'success'
                print("Hansha history fetched successfully")
                # Mark bonbast_history as skipped since hansha succeeded
                sources_status['bonbast_history']['status'] = 'skipped'
                sources_status['bonbast_history']['error'] = 'Not needed - hansha_history succeeded'

            # Fetch Crypto rates
            print("Fetching Crypto rates...")
            crypto_result = await fetch(APIs.CRYPTO_RATES.url, session)
            if isinstance(crypto_result, dict) and crypto_result.get('error'):
                sources_status['crypto']['status'] = 'failed'
                sources_status['crypto']['error'] = crypto_result.get('error')
                print(f"Crypto failed: {crypto_result.get('error')}")
            elif isinstance(crypto_result, list):
                cryptos = [crypto.copy() for crypto in crypto_result]
                sources_status['crypto']['status'] = 'success'
                print(f"Crypto rates fetched successfully ({len(cryptos)} currencies)")
            else:
                sources_status['crypto']['status'] = 'failed'
                sources_status['crypto']['error'] = 'Unexpected data format'
                print("Crypto returned unexpected data format")

        # Fetch Bonbast rates
        print("Fetching Bonbast rates...")
        bonbast_result_str = await run_bonbast()
        if bonbast_result_str:
            try:
                bonbast_result_json = json.loads(bonbast_result_str)
                bonbast = [{k: v} for k, v in bonbast_result_json.items()]
                sources_status['bonbast']['status'] = 'success'
                print(f"Bonbast rates fetched successfully ({len(bonbast)} currencies)")
            except json.JSONDecodeError as e:
                sources_status['bonbast']['status'] = 'failed'
                sources_status['bonbast']['error'] = f'JSON decode error: {str(e)}'
                print(f"Bonbast JSON decode failed: {e}")
        else:
            sources_status['bonbast']['status'] = 'failed'
            sources_status['bonbast']['error'] = 'Command execution failed'
            print("Bonbast command execution failed")

        # Check if we have any successful data
        successful_sources = sum(1 for s in sources_status.values() if s['status'] == 'success')

        if successful_sources == 0:
            # All sources failed - try to use cache
            print("All sources failed. Attempting to use cached data...")
            cached_data = load_cache()
            if cached_data:
                print("Serving data from cache (all sources unavailable)")
                cached_data['sources_status']['serving_from_cache'] = True
                cached_data['sources_status']['cache_reason'] = 'All sources failed'
                return cached_data
            else:
                # No cache available - return error
                return {
                    "error": "All data sources are unavailable and no cache is available",
                    "sources_status": sources_status
                }, 503

        # Combine available data (even if partial)
        combined_data = combine_data(hansha_rates, cryptos, bonbast, hansha_history, bonbast_history, sources_status)

        # Save to cache for future use
        save_cache(combined_data)

        print(f"Data aggregation complete: {successful_sources}/3 sources successful")
        return combined_data

    except Exception as e:
        print(f"Unexpected error in aggregator: {e}")
        # Try to use cache on unexpected errors
        cached_data = load_cache()
        if cached_data:
            print("Serving data from cache due to unexpected error")
            cached_data['sources_status']['serving_from_cache'] = True
            cached_data['sources_status']['cache_reason'] = f'Unexpected error: {str(e)}'
            return cached_data
        else:
            return {
                "error": f"Unexpected error: {str(e)}",
                "sources_status": sources_status
            }, 500


async def getBlockchainNews():
    if not news_api_key:
        raise ValueError("NEWS_API_KEY environment variable is not set")

    url = f'https://newsapi.org/v2/everything?q=blockchain&apiKey={news_api_key}'

    timeout = aiohttp.ClientTimeout(total=60, connect=30, sock_read=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    try:
                        news = await response.json()
                        return news
                    except Exception as e:
                        print(f"Error parsing JSON: {e}")
                        return None
                else:
                    return {
                        "error": "Blockchain news API request failed",
                        "status_code": response.status
                    }
        except (aiohttp.ClientConnectorError, aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f"Network error fetching blockchain news: {str(e)}")
            return {
                "error": f"Network error: {str(e)}",
                "status_code": 503
            }

import asyncio
import json
import os
import subprocess
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv

load_dotenv()
news_api_key = os.getenv('NEWS_API_KEY')


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


async def run_bonbast_history(date: Optional[str] = None):
    """
    Run bonbast history command.

    Args:
        date: Optional date in format YYYY-MM-DD or YYYY/MM/DD.
              Valid from 2012-10-09 to one day before current date.

    Returns:
        JSON string of history data or None on error
    """
    try:
        cmd = ['bonbast', 'history', '--json']
        if date:
            cmd.extend(['--date', date])

        process = await asyncio.create_subprocess_exec(
            *cmd,
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


async def fetch_hansha_latest() -> Optional[List[Dict[str, Any]]]:
    """
    Fetch latest data (24-hour history) from Hansha API for all currencies.

    Returns:
        List of currency data with 24-hour historical prices or None on error
    """
    try:
        url = 'https://hansha.online/latest'
        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    print(f"   ⚠️  Hansha /latest API returned status {response.status}")
                    return None
    except Exception as e:
        print(f"   ⚠️  Hansha /latest API failed: {e}")
        return None


async def fetch_single_currency(session, url: str, period: str, currency_code: str) -> Optional[Dict[str, Any]]:
    """
    Fetch historical data for a single currency.

    Args:
        session: aiohttp ClientSession
        url: API URL to fetch
        period: Period name for logging
        currency_code: Currency code for logging

    Returns:
        Historical data dictionary or None on error
    """
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
            if response.status == 200:
                return await response.json()
            else:
                print(f"   ⚠️  Hansha API returned status {response.status} for {period}/{currency_code}")
                return None
    except Exception as e:
        print(f"   ⚠️  Hansha API failed for {period}/{currency_code}: {e}")
        return None


async def fetch_all_currencies_historical(period: str, currencies: List[str]) -> List[Dict[str, Any]]:
    """
    Fetch historical data for all currencies from Hansha API.

    Args:
        period: Period name from Hansha API (e.g., 'oneWeek', 'oneMonth', 'oneYear')
        currencies: List of currency codes to fetch

    Returns:
        List of historical data dictionaries for all currencies
    """
    async with aiohttp.ClientSession() as session:
        tasks = []
        for currency_code in currencies:
            url = f'https://hansha.online/historical?period={period}&item={currency_code}'
            tasks.append(fetch_single_currency(session, url, period, currency_code))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Filter out None values and exceptions
        return [r for r in results if r is not None and not isinstance(r, Exception)]


async def fetch_history_for_date(date_str: str) -> Optional[Dict[str, Any]]:
    """
    Fetch history data for a specific date using bonbast CLI.

    Args:
        date_str: Date string in YYYY-MM-DD format

    Returns:
        Dictionary with date and rates, or None on error
    """
    try:
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


async def generate_bonbast_period_fallback(days: int) -> List[Dict[str, Any]]:
    """
    Generate bonbast history as fallback for a specific period.

    Args:
        days: Number of days to fetch

    Returns:
        List of historical data
    """
    return await generate_date_range(min(days, 90))



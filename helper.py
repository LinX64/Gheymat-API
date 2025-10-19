import asyncio
import json
import os
import subprocess
import aiohttp

from aiohttp import ClientSession
from dotenv import load_dotenv
from APIs import APIs

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
    except subprocess.CalledProcessError as e:
        print(f"Error occurred in running bonbast command: {e}")
        return None


def combine_data(results):
    data = {}
    hansha_rates = results[0]
    cryptos = results[1]
    bonbast = results[2]

    data['hansha_rates'] = hansha_rates
    data['crypto'] = [crypto.copy() for crypto in cryptos]
    data['bonbast'] = [{k: v} for k, v in bonbast.items()]

    return data


async def aggregator():
    timeout = aiohttp.ClientTimeout(total=60, connect=30, sock_read=30)
    async with ClientSession(timeout=timeout) as session:
        urls = [APIs.HANSHA_LATEST.url, APIs.CRYPTO_RATES.url]
        tasks = [fetch(url, session) for url in urls]
        results = await asyncio.gather(*tasks)

        for result in results:
            if isinstance(result, dict):
                if result.get('error'):
                    return result, result.get('status_code')
            elif isinstance(result, list):
                continue
            else:
                return {"error": f"Unexpected data type: {type(result)}"}, 400

        bonbast_result_str = await run_bonbast()
        bonbast_result_json = json.loads(bonbast_result_str)
        results.append(bonbast_result_json)

        combined_data = combine_data(results)
        data = combined_data

        return data


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

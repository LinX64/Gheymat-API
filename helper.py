import asyncio
from aiohttp import ClientSession
from APIs import APIs
import subprocess
import json


# Asynchronous function to fetch a single URL
async def fetch(url, session):
    async with session.get(url.url) as response:
        if response.status == 200:
            return await response.json()
        else:
            return {
                "error": f'{url.title} API request failed',
                "status_code": response.status
            }


async def run_bonbast():
    try:
        # Run the 'bonbast export' command asynchronously
        process = await asyncio.create_subprocess_exec(
            'bonbast', 'export',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Wait for the command to complete and capture the output
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
    markets = results[0]['data']
    rates = results[1]['data']
    cryptos = results[2]['Data']
    bonbast = results[3]

    data['markets'] = []
    for market in markets:
        obj = {}
        for attribute in market:
            obj[attribute] = market[attribute]
        data['markets'].append(obj)

    data['rates'] = []
    for rate in rates:
        obj = {}
        for attribute in rate:
            obj[attribute] = rate[attribute]
        data['rates'].append(obj)

    data['crypto'] = []
    for crypto in cryptos:
        obj = {}
        for attribute in crypto['CoinInfo']:
            obj[attribute] = crypto['CoinInfo'][attribute]
        obj['ImageUrl'] = 'https://www.cryptocompare.com' + obj['ImageUrl']
        data['crypto'].append(obj)

    data['bonbast'] = []
    for attribute in bonbast:
        obj = {attribute: bonbast[attribute]}
        data['bonbast'].append(obj)

    return data


async def aggregator():
    async with ClientSession() as session:
        urls = [APIs.COINCAP_MARKETS, APIs.COINCAP_RATES, APIs.CRYPTO_COMPARE]
        tasks = [fetch(url, session) for url in urls]
        results = await asyncio.gather(*tasks)

        # Check for errors in the API responses
        for result in results:
            if result.get('error'):
                return result, result.get('status_code')

        bonbast_result_str = await run_bonbast()
        bonbast_result_json = json.loads(bonbast_result_str)
        results.append(bonbast_result_json)

        # combine all fetched data into one json object
        combined_data = combine_data(results)
        data = combined_data

        return data

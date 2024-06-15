import asyncio
from aiohttp import ClientSession
from .APIs import APIs


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


def combine_data(results):
    data = {}
    markets = results[0]['data']
    rates = results[1]['data']
    cryptos = results[2]['Data']

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

    return data


async def aggregator():
    data = {}
    async with ClientSession() as session:
        urls = [APIs.COINCAP_MARKETS, APIs.COINCAP_RATES, APIs.CRYPTO_COMPARE]
        tasks = [fetch(url, session) for url in urls]
        results = await asyncio.gather(*tasks)

        # Check for errors in the API responses
        for result in results:
            if result.get('error'):
                return result, result.get('status_code')

        # combine all fetched data into one json object
        combined_data = combine_data(results)
        data = combined_data

        return data

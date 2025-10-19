import asyncio
import json
import os

from helper import aggregator


async def main():
    result = await aggregator()

    if isinstance(result, tuple):
        currencies_data, status_code = result
        print(f"Error fetching currencies (status {status_code}): {currencies_data.get('error')}")
        print("No data written to file")
        return currencies_data

    currencies_data = result

    os.makedirs('data', exist_ok=True)
    with open('data/currencies.json', 'w', encoding='utf-8') as f:
        json.dump(currencies_data, f, indent=2, ensure_ascii=False)

    status = currencies_data.get('sources_status', {})
    successful = sum(1 for s in status.values() if isinstance(s, dict) and s.get('status') == 'success')

    if status.get('serving_from_cache'):
        print(f"WARNING: Serving from cache - {status.get('cache_reason')}")
    else:
        print(f"Data aggregation complete: {successful}/3 sources successful")

    print("Currencies data written to data/currencies.json")

    return {
        "currencies": currencies_data
    }


if __name__ == '__main__':
    result = asyncio.run(main())

import asyncio
import json
import os

from helper import aggregator


async def main():
    currencies_data = await aggregator()

    os.makedirs('data', exist_ok=True)
    with open('data/currencies.json', 'w', encoding='utf-8') as f:
        json.dump(currencies_data, f, indent=2, ensure_ascii=False)
    print("Currencies data written to data/currencies.json")

    return {
        "currencies": currencies_data
    }


if __name__ == '__main__':
    result = asyncio.run(main())

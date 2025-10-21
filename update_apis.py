#!/usr/bin/env python3

import asyncio
from datetime import datetime

from updaters import (
    update_latest,
    update_crypto,
    update_news,
    update_history_period,
    get_currency_list
)


async def main():
    print("=" * 60)
    print("🚀 Currency Cap Portal - API Update")
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    currencies = await get_currency_list()
    print(f"\n📋 Found {len(currencies)} currencies: {', '.join(currencies[:5])}...")

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

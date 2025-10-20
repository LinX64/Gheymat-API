#!/usr/bin/env python3
"""
Generate historical currency data for a specific date.

This script uses the bonbast CLI to fetch historical exchange rates
for a specific date and saves it to the API directory.

Usage:
    python3 generate_history_date.py 2020-10-10
    python3 generate_history_date.py 2020/10/10

Valid date range: 2012-10-09 to one day before current date
Date format: YYYY-MM-DD or YYYY/MM/DD (Gregorian calendar)
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from helper import run_bonbast_history


def validate_date(date_str: str) -> bool:
    """
    Validate date string format and range.

    Args:
        date_str: Date string in YYYY-MM-DD or YYYY/MM/DD format

    Returns:
        True if valid, False otherwise
    """
    try:
        normalized = date_str.replace('/', '-')
        date_obj = datetime.strptime(normalized, '%Y-%m-%d')

        min_date = datetime(2012, 10, 9)
        max_date = datetime.now() - timedelta(days=1)

        if date_obj < min_date:
            print(f"❌ Error: Date must be on or after 2012-10-09")
            return False

        if date_obj > max_date:
            print(f"❌ Error: Date must be before {max_date.strftime('%Y-%m-%d')}")
            return False

        return True
    except ValueError:
        print(f"❌ Error: Invalid date format. Use YYYY-MM-DD or YYYY/MM/DD")
        return False


async def generate_history_for_date(date_str: str):
    """
    Generate history data for a specific date.

    Args:
        date_str: Date string in YYYY-MM-DD or YYYY/MM/DD format
    """
    print(f"\n🔍 Fetching history for {date_str}...\n")

    history_json = await run_bonbast_history(date=date_str)

    if not history_json:
        print(f"❌ Failed to fetch history data for {date_str}")
        return False

    try:
        history_data = json.loads(history_json)

        api_dir = Path('api/history')
        api_dir.mkdir(parents=True, exist_ok=True)

        normalized_date = date_str.replace('/', '-')
        output_file = api_dir / f'{normalized_date}.json'

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(history_data, f, ensure_ascii=False, indent=2)

        print(f"✅ History data saved to {output_file}")
        print(f"\n📍 URL: https://linx64.github.io/CurrencyCapPortal/history/{normalized_date}.json\n")
        return True

    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON response: {e}")
        return False


async def main():
    """Main execution."""
    if len(sys.argv) != 2:
        print(__doc__)
        print("\nExample:")
        print("  python3 generate_history_date.py 2020-10-10")
        sys.exit(1)

    date_str = sys.argv[1]

    if not validate_date(date_str):
        sys.exit(1)

    success = await generate_history_for_date(date_str)

    if not success:
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())

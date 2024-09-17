import asyncio
import json

from helper import aggregator

if __name__ == '__main__':
    data = asyncio.run(aggregator())
    print(json.dumps(data, indent=2))

import asyncio

from flask import json

from helper import aggregator, getBlockchainNews

if __name__ == '__main__':
    data = asyncio.run(aggregator())

    print(json.dumps(data))

import asyncio

from flask import json

from helper import aggregator, getBlockchainNews

if __name__ == '__main__':
    blockchainNews = asyncio.run(getBlockchainNews())
    data = asyncio.run(aggregator())

    print(json.dumps(blockchainNews, indent=2))
    print(json.dumps(data, indent=2))
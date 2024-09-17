import asyncio

from flask import json

from helper import aggregator, getBlockchainNews

if __name__ == '__main__':
    blockchainNews = asyncio.run(getBlockchainNews())
    data = asyncio.run(aggregator())

    combined_data = {
        "blockchainNews": blockchainNews,
        "aggregatedData": data
    }

    print(json.dumps(combined_data, indent=2))

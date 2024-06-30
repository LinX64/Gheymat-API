import asyncio

from flask import json

from helper import getBlockchainNews

if __name__ == '__main__':
    blockchainNews = asyncio.run(getBlockchainNews())
    print(json.dumps(blockchainNews, indent=2))

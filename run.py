from helper import aggregator
import asyncio

if __name__ == '__main__':
    data = asyncio.run(aggregator())
    print(data)

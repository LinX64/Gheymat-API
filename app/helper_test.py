import pytest
from aiohttp import ClientSession
from flask import Flask


@pytest.mark.asyncio
async def test_fetch():
    coincap_url = 'https://api.coincap.io/v2/markets'
    async with ClientSession() as session:
        async with session.get(coincap_url) as response:
            result = await response.json()
            assert response.status == 200
            print(result)


if __name__ == '__main__':
    pytest.main()

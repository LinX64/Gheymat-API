import pytest
import asyncio
import requests


@pytest.mark.asyncio
async def test_fetch():
    coincap_url = 'https://api.coincap.io/v2/markets'

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, requests.get, coincap_url)
    result = response.json()

    assert response.status_code == 200
    print(result)


if __name__ == '__main__':
    pytest.main()

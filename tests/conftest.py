"""Pytest configuration and shared fixtures for Currency Cap Portal tests."""

import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, AsyncMock


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Create a temporary cache directory for testing."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(exist_ok=True)
    yield cache_dir
    # Cleanup
    if cache_dir.exists():
        shutil.rmtree(cache_dir)


@pytest.fixture
def temp_api_dir(tmp_path):
    """Create a temporary API directory for testing."""
    api_dir = tmp_path / "api"
    api_dir.mkdir(exist_ok=True)
    yield api_dir
    # Cleanup
    if api_dir.exists():
        shutil.rmtree(api_dir)


@pytest.fixture
def mock_aiohttp_session():
    """Create a mock aiohttp ClientSession."""
    session = AsyncMock()
    return session


@pytest.fixture
def mock_aiohttp_response():
    """Create a mock aiohttp response."""
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"data": "test"})
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock()
    return response


@pytest.fixture
def sample_currency_data():
    """Sample currency data for testing."""
    return [
        {
            "ab": "usd",
            "price": 50000,
            "name": "US Dollar",
            "history": [
                {"date": "2023-01-01", "price": 49000},
                {"date": "2023-01-02", "price": 49500},
                {"date": "2023-01-03", "price": 50000}
            ]
        },
        {
            "ab": "eur",
            "price": 55000,
            "name": "Euro",
            "history": [
                {"date": "2023-01-01", "price": 54000},
                {"date": "2023-01-02", "price": 54500},
                {"date": "2023-01-03", "price": 55000}
            ]
        }
    ]


@pytest.fixture
def sample_crypto_data():
    """Sample cryptocurrency data for testing."""
    return [
        {
            "id": "bitcoin",
            "symbol": "btc",
            "name": "Bitcoin",
            "current_price": 45000,
            "market_cap": 850000000000,
            "price_change_percentage_24h": 2.5
        },
        {
            "id": "ethereum",
            "symbol": "eth",
            "name": "Ethereum",
            "current_price": 3000,
            "market_cap": 360000000000,
            "price_change_percentage_24h": 1.8
        }
    ]


@pytest.fixture
def sample_news_data():
    """Sample news articles for testing."""
    return [
        {
            "title": "Bitcoin Reaches New High",
            "description": "Bitcoin price surges to new all-time high",
            "url": "https://example.com/news/1",
            "publishedAt": "2023-01-01T12:00:00Z"
        },
        {
            "title": "Ethereum Upgrade Complete",
            "description": "Latest Ethereum upgrade successfully deployed",
            "url": "https://example.com/news/2",
            "publishedAt": "2023-01-02T12:00:00Z"
        }
    ]


@pytest.fixture
def sample_bonbast_data():
    """Sample Bonbast exchange rate data."""
    return {
        "usd": {"sell": 50000, "buy": 49000},
        "eur": {"sell": 55000, "buy": 54000},
        "gbp": {"sell": 60000, "buy": 59000},
        "chf": {"sell": 52000, "buy": 51000},
        "cad": {"sell": 37000, "buy": 36500}
    }


@pytest.fixture
def sample_historical_data():
    """Sample historical data for testing."""
    return [
        {
            "date": "2023-01-03",
            "rates": {"usd": 50000, "eur": 55000}
        },
        {
            "date": "2023-01-02",
            "rates": {"usd": 49500, "eur": 54500}
        },
        {
            "date": "2023-01-01",
            "rates": {"usd": 49000, "eur": 54000}
        }
    ]


@pytest.fixture(autouse=True)
def reset_cache_between_tests():
    """Reset any module-level caches between tests."""
    yield
    # Cleanup code after each test


@pytest.fixture
def mock_datetime_now(monkeypatch):
    """Mock datetime.now() for consistent testing."""
    from datetime import datetime

    class MockDatetime:
        @staticmethod
        def now():
            return datetime(2023, 1, 15, 12, 0, 0)

        @staticmethod
        def fromisoformat(date_string):
            return datetime.fromisoformat(date_string)

    def mock_now():
        return datetime(2023, 1, 15, 12, 0, 0)

    return mock_now


# Custom markers
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests"
    )

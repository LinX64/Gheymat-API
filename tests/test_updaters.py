"""Unit tests for updaters.py module."""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock, call
import aiohttp

from updaters import (
    fetch_news,
    update_latest,
    update_history_period,
    update_crypto,
    update_news,
    get_currency_list
)


class TestFetchNews:
    """Tests for fetch_news function."""

    @pytest.mark.asyncio
    async def test_fetch_news_success(self):
        """Test successful news fetch."""
        mock_articles = [
            {"title": "Article 1", "description": "Description 1"},
            {"title": "Article 2", "description": "Description 2"}
        ]

        with patch('updaters.news_api_key', 'test_api_key'):
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json = AsyncMock(return_value={"articles": mock_articles})

                # Create proper async context manager mocks
                mock_get_cm = AsyncMock()
                mock_get_cm.__aenter__.return_value = mock_response
                mock_get_cm.__aexit__.return_value = None

                mock_session = MagicMock()
                mock_session.get = MagicMock(return_value=mock_get_cm)

                mock_session_cm = AsyncMock()
                mock_session_cm.__aenter__.return_value = mock_session
                mock_session_cm.__aexit__.return_value = None

                mock_session_class.return_value = mock_session_cm

                result = await fetch_news()
                assert result == mock_articles
                assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_news_no_api_key(self):
        """Test news fetch without API key."""
        with patch('updaters.news_api_key', None):
            result = await fetch_news()
            assert result is None

    @pytest.mark.asyncio
    async def test_fetch_news_api_error(self):
        """Test news fetch with API error."""
        with patch('os.getenv', return_value='test_api_key'):
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session = AsyncMock()
                mock_response = AsyncMock()
                mock_response.status = 500

                mock_session.get = AsyncMock(return_value=mock_response)
                mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
                mock_session.get.return_value.__aexit__ = AsyncMock()

                mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_class.return_value.__aexit__ = AsyncMock()

                result = await fetch_news()
                assert result is None


class TestUpdateLatest:
    """Tests for update_latest function."""

    @pytest.mark.asyncio
    async def test_update_latest_success(self):
        """Test successful latest update."""
        mock_data = [{"ab": "usd", "price": 50000}]

        with patch('updaters.fetch') as mock_fetch:
            with patch('updaters.save_cache') as mock_save_cache:
                with patch('updaters.save_api_endpoint') as mock_save_api:
                    mock_fetch.return_value = mock_data

                    await update_latest()

                    mock_save_cache.assert_called_once_with('latest', mock_data)
                    mock_save_api.assert_called_once_with('latest.json', mock_data)

    @pytest.mark.asyncio
    async def test_update_latest_fallback_to_cache(self):
        """Test latest update falling back to cache."""
        cached_data = [{"ab": "usd", "price": 48000}]

        with patch('updaters.fetch') as mock_fetch:
            with patch('updaters.load_cache', return_value=cached_data):
                with patch('updaters.save_api_endpoint') as mock_save_api:
                    mock_fetch.return_value = {"error": "API failed"}

                    await update_latest()

                    mock_save_api.assert_called_once_with('latest.json', cached_data)

    @pytest.mark.asyncio
    async def test_update_latest_no_cache_no_data(self):
        """Test latest update with no data and no cache."""
        with patch('updaters.fetch') as mock_fetch:
            with patch('updaters.load_cache', return_value=None):
                with patch('updaters.save_api_endpoint') as mock_save_api:
                    mock_fetch.return_value = None

                    await update_latest()

                    mock_save_api.assert_not_called()


class TestUpdateHistoryPeriod:
    """Tests for update_history_period function."""

    @pytest.mark.asyncio
    async def test_update_history_period_latest(self):
        """Test updating latest period (24h history)."""
        mock_data = [{"ab": "usd", "history": []}]
        currencies = ["usd", "eur"]

        with patch('updaters.fetch_hansha_latest', return_value=mock_data):
            with patch('updaters.save_cache') as mock_save_cache:
                with patch('updaters.save_api_endpoint') as mock_save_api:
                    await update_history_period('1d', 'latest', 1, currencies)

                    mock_save_cache.assert_called_once_with('1d', mock_data)
                    mock_save_api.assert_called_once_with('history/1d.json', mock_data)

    @pytest.mark.asyncio
    async def test_update_history_period_hansha_success(self):
        """Test updating period with successful Hansha fetch."""
        mock_data = [{"ab": "usd", "history": []}, {"ab": "eur", "history": []}]
        currencies = ["usd", "eur"]

        with patch('updaters.fetch_all_currencies_historical', return_value=mock_data):
            with patch('updaters.save_cache') as mock_save_cache:
                with patch('updaters.save_api_endpoint') as mock_save_api:
                    await update_history_period('1w', 'oneWeek', 7, currencies)

                    mock_save_cache.assert_called_once_with('1w', mock_data)
                    mock_save_api.assert_called_once_with('history/1w.json', mock_data)

    @pytest.mark.asyncio
    async def test_update_history_period_fallback_to_bonbast(self):
        """Test updating period falling back to Bonbast."""
        bonbast_data = [{"date": "2023-01-01", "rates": {}}]
        currencies = ["usd", "eur"]

        with patch('updaters.fetch_all_currencies_historical', return_value=[]):
            with patch('updaters.generate_bonbast_period_fallback', return_value=bonbast_data):
                with patch('updaters.save_cache') as mock_save_cache:
                    with patch('updaters.save_api_endpoint') as mock_save_api:
                        await update_history_period('1m', 'oneMonth', 30, currencies)

                        mock_save_cache.assert_called_once_with('1m', bonbast_data)
                        mock_save_api.assert_called_once_with('history/1m.json', bonbast_data)

    @pytest.mark.asyncio
    async def test_update_history_period_fallback_to_cache(self):
        """Test updating period falling back to cache."""
        cached_data = [{"date": "2023-01-01", "rates": {}}]
        currencies = ["usd", "eur"]

        with patch('updaters.fetch_all_currencies_historical', return_value=[]):
            with patch('updaters.generate_bonbast_period_fallback', return_value=None):
                with patch('updaters.load_cache', return_value=cached_data):
                    with patch('updaters.save_api_endpoint') as mock_save_api:
                        await update_history_period('1y', 'oneYear', 90, currencies)

                        mock_save_api.assert_called_once_with('history/1y.json', cached_data)


class TestUpdateCrypto:
    """Tests for update_crypto function."""

    @pytest.mark.asyncio
    async def test_update_crypto_success(self):
        """Test successful crypto update."""
        mock_data = [
            {"id": "bitcoin", "symbol": "btc", "current_price": 50000},
            {"id": "ethereum", "symbol": "eth", "current_price": 3000}
        ]

        with patch('updaters.fetch', return_value=mock_data):
            with patch('updaters.save_cache') as mock_save_cache:
                with patch('updaters.save_api_endpoint') as mock_save_api:
                    await update_crypto()

                    mock_save_cache.assert_called_once_with('crypto', mock_data)
                    mock_save_api.assert_called_once_with('crypto.json', mock_data)

    @pytest.mark.asyncio
    async def test_update_crypto_fallback_to_cache(self):
        """Test crypto update falling back to cache."""
        cached_data = [{"id": "bitcoin", "symbol": "btc"}]

        with patch('updaters.fetch', return_value={"error": "Failed"}):
            with patch('updaters.load_cache', return_value=cached_data):
                with patch('updaters.save_api_endpoint') as mock_save_api:
                    await update_crypto()

                    mock_save_api.assert_called_once_with('crypto.json', cached_data)


class TestUpdateNews:
    """Tests for update_news function."""

    @pytest.mark.asyncio
    async def test_update_news_success(self):
        """Test successful news update."""
        mock_articles = [{"title": "News 1"}]

        with patch('updaters.fetch_news', return_value=mock_articles):
            with patch('updaters.save_cache') as mock_save_cache:
                with patch('updaters.save_api_endpoint') as mock_save_api:
                    await update_news()

                    mock_save_cache.assert_called_once_with('news', mock_articles)
                    mock_save_api.assert_called_once_with('news.json', mock_articles)

    @pytest.mark.asyncio
    async def test_update_news_fallback_to_cache(self):
        """Test news update falling back to cache."""
        cached_data = [{"title": "Cached News"}]

        with patch('updaters.fetch_news', return_value=None):
            with patch('updaters.load_cache', return_value=cached_data):
                with patch('updaters.save_api_endpoint') as mock_save_api:
                    await update_news()

                    mock_save_api.assert_called_once_with('news.json', cached_data)


class TestGetCurrencyList:
    """Tests for get_currency_list function."""

    @pytest.mark.asyncio
    async def test_get_currency_list_success(self):
        """Test successful currency list fetch."""
        mock_data = [
            {"ab": "usd", "price": 50000},
            {"ab": "eur", "price": 55000},
            {"ab": "gbp", "price": 60000}
        ]

        with patch('updaters.fetch', return_value=mock_data):
            result = await get_currency_list()
            assert result == ["usd", "eur", "gbp"]

    @pytest.mark.asyncio
    async def test_get_currency_list_with_missing_ab(self):
        """Test currency list with some missing 'ab' fields."""
        mock_data = [
            {"ab": "usd", "price": 50000},
            {"price": 55000},  # Missing 'ab'
            {"ab": "gbp", "price": 60000}
        ]

        with patch('updaters.fetch', return_value=mock_data):
            result = await get_currency_list()
            assert result == ["usd", "gbp"]

    @pytest.mark.asyncio
    async def test_get_currency_list_fallback(self):
        """Test currency list fallback to defaults."""
        with patch('updaters.fetch', return_value=None):
            result = await get_currency_list()
            assert "usd" in result
            assert "eur" in result
            assert "gbp" in result
            assert len(result) == 10

    @pytest.mark.asyncio
    async def test_get_currency_list_exception(self):
        """Test currency list with exception."""
        with patch('updaters.fetch', side_effect=Exception("Network error")):
            result = await get_currency_list()
            # Should return default list
            assert "usd" in result
            assert len(result) == 10

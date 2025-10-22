"""Unit tests for helper.py module."""

import asyncio
import json
import pytest
import aiohttp
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime, timedelta

from helper import (
    fetch,
    run_bonbast,
    run_bonbast_history,
    fetch_hansha_latest,
    fetch_single_currency,
    fetch_all_currencies_historical,
    fetch_history_for_date,
    generate_date_range,
    generate_bonbast_period_fallback
)


class TestFetch:
    """Tests for the fetch function."""

    @pytest.mark.asyncio
    async def test_fetch_success(self):
        """Test successful fetch."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"data": "test"})

        # Create a proper async context manager mock
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)

        result = await fetch("https://example.com", mock_session)
        assert result == {"data": "test"}

    @pytest.mark.asyncio
    async def test_fetch_invalid_url_type(self):
        """Test fetch with invalid URL type."""
        mock_session = AsyncMock()
        result = await fetch(123, mock_session)
        assert result == {"error": "URL must be a string", "status_code": 400}

    @pytest.mark.asyncio
    async def test_fetch_404_error(self):
        """Test fetch with 404 error."""
        mock_response = AsyncMock()
        mock_response.status = 404

        # Create a proper async context manager mock
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)

        result = await fetch("https://example.com", mock_session, retries=2, delay=0.1)
        assert "error" in result
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_fetch_rate_limit(self):
        """Test fetch with 429 rate limit."""
        mock_response_429 = AsyncMock()
        mock_response_429.status = 429

        mock_response_200 = AsyncMock()
        mock_response_200.status = 200
        mock_response_200.json = AsyncMock(return_value={"data": "success"})

        # Create context managers for each response
        mock_cm_429 = AsyncMock()
        mock_cm_429.__aenter__.return_value = mock_response_429
        mock_cm_429.__aexit__.return_value = None

        mock_cm_200 = AsyncMock()
        mock_cm_200.__aenter__.return_value = mock_response_200
        mock_cm_200.__aexit__.return_value = None

        mock_session = MagicMock()
        # First call returns 429, second returns 200
        mock_session.get.side_effect = [mock_cm_429, mock_cm_200]

        result = await fetch("https://example.com", mock_session, retries=2, delay=0.1)
        assert result == {"data": "success"}

    @pytest.mark.asyncio
    async def test_fetch_content_type_error(self):
        """Test fetch with invalid content type."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(side_effect=aiohttp.ContentTypeError(
            Mock(), Mock()
        ))

        # Create a proper async context manager mock
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)

        result = await fetch("https://example.com", mock_session)
        assert result["error"] == "Invalid response format"


class TestRunBonbast:
    """Tests for bonbast CLI functions."""

    @pytest.mark.asyncio
    async def test_run_bonbast_success(self):
        """Test successful bonbast export."""
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b'{"usd": 50000}', b''))

        with patch('asyncio.create_subprocess_exec', return_value=mock_process):
            result = await run_bonbast()
            assert result == '{"usd": 50000}'

    @pytest.mark.asyncio
    async def test_run_bonbast_failure(self):
        """Test bonbast export failure."""
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b'', b'Error message'))

        with patch('asyncio.create_subprocess_exec', return_value=mock_process):
            result = await run_bonbast()
            assert result is None

    @pytest.mark.asyncio
    async def test_run_bonbast_history_with_date(self):
        """Test bonbast history with specific date."""
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b'{"usd": 45000}', b''))

        with patch('asyncio.create_subprocess_exec', return_value=mock_process) as mock_exec:
            result = await run_bonbast_history(date="2023-01-01")
            assert result == '{"usd": 45000}'
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args[0]
            assert 'bonbast' in call_args
            assert 'history' in call_args
            assert '--date' in call_args
            assert '2023-01-01' in call_args

    @pytest.mark.asyncio
    async def test_run_bonbast_history_without_date(self):
        """Test bonbast history without date."""
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b'{"usd": 48000}', b''))

        with patch('asyncio.create_subprocess_exec', return_value=mock_process) as mock_exec:
            result = await run_bonbast_history()
            assert result == '{"usd": 48000}'
            call_args = mock_exec.call_args[0]
            assert '--date' not in call_args


class TestHanshaAPI:
    """Tests for Hansha API functions."""

    @pytest.mark.asyncio
    async def test_fetch_hansha_latest_success(self):
        """Test successful Hansha latest fetch."""
        mock_data = [{"ab": "usd", "price": 50000}]

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_data)

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

            result = await fetch_hansha_latest()
            assert result == mock_data

    @pytest.mark.asyncio
    async def test_fetch_hansha_latest_failure(self):
        """Test Hansha latest fetch with error."""
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.status = 500

            mock_session.get = AsyncMock(return_value=mock_response)
            mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_session.get.return_value.__aexit__ = AsyncMock()

            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock()

            result = await fetch_hansha_latest()
            assert result is None

    @pytest.mark.asyncio
    async def test_fetch_single_currency_success(self):
        """Test successful single currency fetch."""
        mock_data = {"ab": "usd", "history": []}
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_data)

        # Create proper async context manager mock
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)

        result = await fetch_single_currency(
            mock_session,
            "https://hansha.online/historical?period=oneWeek&item=usd",
            "oneWeek",
            "usd"
        )
        assert result == mock_data

    @pytest.mark.asyncio
    async def test_fetch_single_currency_400_error(self):
        """Test single currency fetch with 400 error."""
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 400

        mock_session.get = AsyncMock(return_value=mock_response)
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.get.return_value.__aexit__ = AsyncMock()

        result = await fetch_single_currency(
            mock_session,
            "https://hansha.online/historical?period=fiveYear&item=usd",
            "fiveYear",
            "usd"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_all_currencies_historical(self):
        """Test fetching all currencies historical data."""
        currencies = ["usd", "eur", "gbp"]

        with patch('helper.fetch_single_currency') as mock_fetch:
            mock_fetch.side_effect = [
                {"ab": "usd", "history": []},
                {"ab": "eur", "history": []},
                None  # One failure
            ]

            result = await fetch_all_currencies_historical("oneWeek", currencies)
            assert len(result) == 2
            assert result[0]["ab"] == "usd"
            assert result[1]["ab"] == "eur"


class TestHistoryFunctions:
    """Tests for history generation functions."""

    @pytest.mark.asyncio
    async def test_fetch_history_for_date_success(self):
        """Test successful history fetch for date."""
        date_str = "2023-01-01"
        mock_json = '{"usd": 50000, "eur": 55000}'

        with patch('helper.run_bonbast_history', return_value=mock_json):
            result = await fetch_history_for_date(date_str)
            assert result["date"] == date_str
            assert result["rates"]["usd"] == 50000

    @pytest.mark.asyncio
    async def test_fetch_history_for_date_failure(self):
        """Test history fetch failure."""
        with patch('helper.run_bonbast_history', return_value=None):
            result = await fetch_history_for_date("2023-01-01")
            assert result is None

    @pytest.mark.asyncio
    async def test_generate_date_range(self):
        """Test date range generation."""
        with patch('helper.fetch_history_for_date') as mock_fetch:
            mock_fetch.side_effect = [
                {"date": "2023-01-03", "rates": {"usd": 50000}},
                {"date": "2023-01-02", "rates": {"usd": 49000}},
                {"date": "2023-01-01", "rates": {"usd": 48000}}
            ]

            result = await generate_date_range(3)
            assert len(result) == 3
            # Results should be sorted in reverse chronological order
            assert result[0]["date"] == "2023-01-03"

    @pytest.mark.asyncio
    async def test_generate_bonbast_period_fallback(self):
        """Test bonbast period fallback."""
        with patch('helper.generate_date_range') as mock_generate:
            mock_generate.return_value = [{"date": "2023-01-01", "rates": {}}]

            result = await generate_bonbast_period_fallback(100)
            # Should cap at 90 days
            mock_generate.assert_called_once_with(90)
            assert result == [{"date": "2023-01-01", "rates": {}}]

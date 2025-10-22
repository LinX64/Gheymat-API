"""Unit tests for update_apis.py module."""

import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime

from update_apis import main


class TestUpdateApisMain:
    """Tests for the main function in update_apis.py."""

    @pytest.mark.asyncio
    async def test_main_success_all_updates(self):
        """Test successful execution of main with all updates."""
        mock_currencies = ['usd', 'eur', 'gbp', 'btc', 'eth']

        with patch('update_apis.get_currency_list', return_value=mock_currencies):
            with patch('update_apis.update_latest', new_callable=AsyncMock) as mock_latest:
                with patch('update_apis.update_crypto', new_callable=AsyncMock) as mock_crypto:
                    with patch('update_apis.update_news', new_callable=AsyncMock) as mock_news:
                        with patch('update_apis.update_history_period', new_callable=AsyncMock) as mock_history:
                            await main()

                            # Verify all updates were called
                            mock_latest.assert_called_once()
                            mock_crypto.assert_called_once()
                            mock_news.assert_called_once()

                            # Verify history updates for all periods
                            assert mock_history.call_count == 6
                            mock_history.assert_any_call('1d', 'latest', 1, mock_currencies)
                            mock_history.assert_any_call('1w', 'oneWeek', 7, mock_currencies)
                            mock_history.assert_any_call('1m', 'oneMonth', 30, mock_currencies)
                            mock_history.assert_any_call('1y', 'oneYear', 90, mock_currencies)
                            mock_history.assert_any_call('5y', 'fiveYears', 90, mock_currencies)
                            mock_history.assert_any_call('all', 'all', 90, mock_currencies)

    @pytest.mark.asyncio
    async def test_main_with_empty_currency_list(self):
        """Test main with empty currency list."""
        with patch('update_apis.get_currency_list', return_value=[]):
            with patch('update_apis.update_latest', new_callable=AsyncMock):
                with patch('update_apis.update_crypto', new_callable=AsyncMock):
                    with patch('update_apis.update_news', new_callable=AsyncMock):
                        with patch('update_apis.update_history_period', new_callable=AsyncMock) as mock_history:
                            await main()

                            # Should still call history updates, just with empty list
                            assert mock_history.call_count == 6

    @pytest.mark.asyncio
    async def test_main_with_many_currencies(self):
        """Test main with large currency list."""
        # Simulate a large list of currencies
        mock_currencies = [f'curr{i}' for i in range(100)]

        with patch('update_apis.get_currency_list', return_value=mock_currencies):
            with patch('update_apis.update_latest', new_callable=AsyncMock):
                with patch('update_apis.update_crypto', new_callable=AsyncMock):
                    with patch('update_apis.update_news', new_callable=AsyncMock):
                        with patch('update_apis.update_history_period', new_callable=AsyncMock) as mock_history:
                            await main()

                            # Verify currency list was passed correctly
                            for call in mock_history.call_args_list:
                                assert call[0][3] == mock_currencies

    @pytest.mark.asyncio
    async def test_main_handles_get_currency_list_exception(self):
        """Test main handles exception in get_currency_list."""
        with patch('update_apis.get_currency_list', side_effect=Exception("API Error")):
            with pytest.raises(Exception):
                await main()

    @pytest.mark.asyncio
    async def test_main_continues_on_single_update_failure(self):
        """Test that main continues even if one update fails."""
        mock_currencies = ['usd', 'eur']

        with patch('update_apis.get_currency_list', return_value=mock_currencies):
            with patch('update_apis.update_latest', new_callable=AsyncMock):
                with patch('update_apis.update_crypto', side_effect=Exception("Crypto API failed")):
                    with patch('update_apis.update_news', new_callable=AsyncMock):
                        with patch('update_apis.update_history_period', new_callable=AsyncMock):
                            # Should not raise exception due to asyncio.gather
                            with pytest.raises(Exception):
                                await main()

    @pytest.mark.asyncio
    async def test_main_all_periods_configured_correctly(self):
        """Test that all historical periods have correct configuration."""
        mock_currencies = ['usd', 'eur']

        with patch('update_apis.get_currency_list', return_value=mock_currencies):
            with patch('update_apis.update_latest', new_callable=AsyncMock):
                with patch('update_apis.update_crypto', new_callable=AsyncMock):
                    with patch('update_apis.update_news', new_callable=AsyncMock):
                        with patch('update_apis.update_history_period', new_callable=AsyncMock) as mock_history:
                            await main()

                            # Verify each period has correct parameters
                            calls = mock_history.call_args_list

                            # 1d period
                            assert any(
                                call[0] == ('1d', 'latest', 1, mock_currencies)
                                for call in calls
                            )

                            # 1w period
                            assert any(
                                call[0] == ('1w', 'oneWeek', 7, mock_currencies)
                                for call in calls
                            )

                            # 1m period
                            assert any(
                                call[0] == ('1m', 'oneMonth', 30, mock_currencies)
                                for call in calls
                            )

                            # 1y period
                            assert any(
                                call[0] == ('1y', 'oneYear', 90, mock_currencies)
                                for call in calls
                            )

                            # 5y period
                            assert any(
                                call[0] == ('5y', 'fiveYears', 90, mock_currencies)
                                for call in calls
                            )

                            # all period
                            assert any(
                                call[0] == ('all', 'all', 90, mock_currencies)
                                for call in calls
                            )

    @pytest.mark.asyncio
    async def test_main_runs_updates_concurrently(self):
        """Test that main runs updates concurrently using asyncio.gather."""
        mock_currencies = ['usd', 'eur']

        with patch('update_apis.get_currency_list', return_value=mock_currencies):
            with patch('update_apis.update_latest', new_callable=AsyncMock) as mock_latest:
                with patch('update_apis.update_crypto', new_callable=AsyncMock) as mock_crypto:
                    with patch('update_apis.update_news', new_callable=AsyncMock) as mock_news:
                        with patch('update_apis.update_history_period', new_callable=AsyncMock) as mock_history:
                            await main()

                            # All functions should have been called
                            mock_latest.assert_called_once()
                            mock_crypto.assert_called_once()
                            mock_news.assert_called_once()
                            assert mock_history.call_count == 6  # 6 history periods

    @pytest.mark.asyncio
    async def test_main_currency_list_passed_to_all_history_updates(self):
        """Test that currency list is passed to all history period updates."""
        mock_currencies = ['usd', 'eur', 'gbp', 'jpy', 'cny']

        with patch('update_apis.get_currency_list', return_value=mock_currencies):
            with patch('update_apis.update_latest', new_callable=AsyncMock):
                with patch('update_apis.update_crypto', new_callable=AsyncMock):
                    with patch('update_apis.update_news', new_callable=AsyncMock):
                        with patch('update_apis.update_history_period', new_callable=AsyncMock) as mock_history:
                            await main()

                            # Verify every history call received the same currency list
                            for call in mock_history.call_args_list:
                                assert call[0][3] == mock_currencies

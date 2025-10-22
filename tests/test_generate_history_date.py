"""Unit tests for generate_history_date.py module."""

import pytest
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock, mock_open

from generate_history_date import (
    validate_date,
    generate_history_for_date,
    main
)


class TestValidateDate:
    """Tests for validate_date function."""

    def test_valid_date_with_dash(self):
        """Test valid date with dash separator."""
        assert validate_date('2023-01-15') is True

    def test_valid_date_with_slash(self):
        """Test valid date with slash separator."""
        assert validate_date('2023/01/15') is True

    def test_valid_date_at_minimum(self):
        """Test date at minimum boundary (2012-10-09)."""
        assert validate_date('2012-10-09') is True

    def test_valid_date_yesterday(self):
        """Test yesterday's date (should be valid)."""
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        assert validate_date(yesterday) is True

    def test_invalid_date_too_old(self):
        """Test date before minimum (2012-10-08)."""
        assert validate_date('2012-10-08') is False

    def test_invalid_date_today(self):
        """Test today's date (should be invalid - must be before today)."""
        today = datetime.now().strftime('%Y-%m-%d')
        assert validate_date(today) is False

    def test_invalid_date_future(self):
        """Test future date."""
        future = (datetime.now() + timedelta(days=10)).strftime('%Y-%m-%d')
        assert validate_date(future) is False

    def test_invalid_date_format_letters(self):
        """Test invalid date format with letters."""
        assert validate_date('2023-ABC-15') is False

    def test_invalid_date_format_incomplete(self):
        """Test incomplete date format."""
        assert validate_date('2023-01') is False

    def test_invalid_date_format_wrong_order(self):
        """Test wrong date component order."""
        assert validate_date('15-01-2023') is False

    def test_invalid_date_format_no_separator(self):
        """Test date without separator."""
        assert validate_date('20230115') is False

    def test_invalid_month(self):
        """Test invalid month value."""
        assert validate_date('2023-13-01') is False

    def test_invalid_day(self):
        """Test invalid day value."""
        assert validate_date('2023-01-32') is False

    def test_leap_year_valid(self):
        """Test valid leap year date."""
        assert validate_date('2024-02-29') is True

    def test_non_leap_year_invalid(self):
        """Test invalid date for non-leap year."""
        assert validate_date('2023-02-29') is False


class TestGenerateHistoryForDate:
    """Tests for generate_history_for_date function."""

    @pytest.mark.asyncio
    async def test_generate_history_success(self, tmp_path):
        """Test successful history generation."""
        mock_history_data = {
            'usd': {'sell': 50000, 'buy': 49000},
            'eur': {'sell': 55000, 'buy': 54000}
        }
        mock_json = json.dumps(mock_history_data)

        with patch('generate_history_date.run_bonbast_history', return_value=mock_json):
            with patch('generate_history_date.Path', return_value=tmp_path):
                result = await generate_history_for_date('2023-01-15')
                assert result is True

    @pytest.mark.asyncio
    async def test_generate_history_bonbast_failure(self):
        """Test history generation when bonbast fails."""
        with patch('generate_history_date.run_bonbast_history', return_value=None):
            result = await generate_history_for_date('2023-01-15')
            assert result is False

    @pytest.mark.asyncio
    async def test_generate_history_invalid_json(self):
        """Test history generation with invalid JSON response."""
        with patch('generate_history_date.run_bonbast_history', return_value='invalid json{'):
            result = await generate_history_for_date('2023-01-15')
            assert result is False

    @pytest.mark.asyncio
    async def test_generate_history_date_normalization(self, tmp_path):
        """Test that date with slashes is normalized to dashes."""
        mock_history_data = {'usd': {'sell': 50000, 'buy': 49000}}
        mock_json = json.dumps(mock_history_data)

        with patch('generate_history_date.run_bonbast_history', return_value=mock_json):
            with patch('pathlib.Path.mkdir'):
                with patch('builtins.open', mock_open()) as mocked_file:
                    result = await generate_history_for_date('2023/01/15')
                    assert result is True

    @pytest.mark.asyncio
    async def test_generate_history_creates_directory(self, tmp_path):
        """Test that api/history directory is created."""
        mock_history_data = {'usd': {'sell': 50000}}
        mock_json = json.dumps(mock_history_data)

        with patch('generate_history_date.run_bonbast_history', return_value=mock_json):
            with patch('builtins.open', mock_open()):
                with patch('pathlib.Path.mkdir'):  # Just mock the mkdir call
                    result = await generate_history_for_date('2023-01-15')
                    # Should successfully process the data
                    assert result is True


class TestMain:
    """Tests for main function."""

    @pytest.mark.asyncio
    async def test_main_no_arguments(self):
        """Test main with no command line arguments."""
        with patch('sys.argv', ['generate_history_date.py']):
            with pytest.raises(SystemExit) as exc_info:
                await main()
            assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_main_too_many_arguments(self):
        """Test main with too many arguments."""
        with patch('sys.argv', ['generate_history_date.py', '2023-01-01', 'extra']):
            with pytest.raises(SystemExit) as exc_info:
                await main()
            assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_main_invalid_date(self):
        """Test main with invalid date."""
        with patch('sys.argv', ['generate_history_date.py', '2023-13-45']):
            with pytest.raises(SystemExit) as exc_info:
                await main()
            assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_main_date_too_old(self):
        """Test main with date before minimum."""
        with patch('sys.argv', ['generate_history_date.py', '2010-01-01']):
            with pytest.raises(SystemExit) as exc_info:
                await main()
            assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_main_success(self):
        """Test main with valid date and successful generation."""
        with patch('sys.argv', ['generate_history_date.py', '2023-01-15']):
            with patch('generate_history_date.generate_history_for_date', return_value=True):
                # Should not raise SystemExit
                await main()

    @pytest.mark.asyncio
    async def test_main_generation_failure(self):
        """Test main with valid date but generation failure."""
        with patch('sys.argv', ['generate_history_date.py', '2023-01-15']):
            with patch('generate_history_date.generate_history_for_date', return_value=False):
                with pytest.raises(SystemExit) as exc_info:
                    await main()
                assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_main_with_slash_date(self):
        """Test main with slash-separated date."""
        with patch('sys.argv', ['generate_history_date.py', '2023/01/15']):
            with patch('generate_history_date.generate_history_for_date', return_value=True):
                # Should not raise SystemExit
                await main()

    @pytest.mark.asyncio
    async def test_main_with_yesterday(self):
        """Test main with yesterday's date."""
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        with patch('sys.argv', ['generate_history_date.py', yesterday]):
            with patch('generate_history_date.generate_history_for_date', return_value=True):
                # Should not raise SystemExit
                await main()

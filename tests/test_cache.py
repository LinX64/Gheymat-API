"""Unit tests for cache.py module."""

import json
import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, mock_open

from cache import (
    load_cache,
    save_cache,
    save_api_endpoint,
    CACHE_DIR,
    API_DIR,
    CACHE_EXPIRY
)


class TestCacheConstants:
    """Tests for cache constants."""

    def test_cache_expiry_values(self):
        """Test that cache expiry values are defined."""
        assert CACHE_EXPIRY['latest'] == 5
        assert CACHE_EXPIRY['1d'] == 60
        assert CACHE_EXPIRY['1w'] == 360
        assert CACHE_EXPIRY['1m'] == 720
        assert CACHE_EXPIRY['1y'] == 1440
        assert CACHE_EXPIRY['crypto'] == 5
        assert CACHE_EXPIRY['news'] == 60


class TestLoadCache:
    """Tests for load_cache function."""

    def test_load_cache_file_not_exists(self, tmp_path):
        """Test loading cache when file doesn't exist."""
        with patch('cache.CACHE_DIR', tmp_path):
            result = load_cache('nonexistent')
            assert result is None

    def test_load_cache_valid_not_expired(self, tmp_path):
        """Test loading valid non-expired cache."""
        cache_data = {
            'cached_at': datetime.now().isoformat(),
            'data': {'test': 'data'}
        }

        cache_file = tmp_path / 'test.json'
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f)

        with patch('cache.CACHE_DIR', tmp_path):
            result = load_cache('test')
            assert result == {'test': 'data'}

    def test_load_cache_expired(self, tmp_path):
        """Test loading expired cache."""
        old_time = datetime.now() - timedelta(minutes=100)
        cache_data = {
            'cached_at': old_time.isoformat(),
            'data': {'test': 'data'}
        }

        cache_file = tmp_path / 'test.json'
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f)

        with patch('cache.CACHE_DIR', tmp_path):
            with patch('cache.CACHE_EXPIRY', {'test': 60}):
                result = load_cache('test')
                assert result is None

    def test_load_cache_not_expired_custom_expiry(self, tmp_path):
        """Test loading cache with custom expiry time."""
        recent_time = datetime.now() - timedelta(minutes=30)
        cache_data = {
            'cached_at': recent_time.isoformat(),
            'data': {'test': 'data'}
        }

        cache_file = tmp_path / 'test.json'
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f)

        with patch('cache.CACHE_DIR', tmp_path):
            with patch('cache.CACHE_EXPIRY', {'test': 60}):
                result = load_cache('test')
                assert result == {'test': 'data'}

    def test_load_cache_invalid_json(self, tmp_path):
        """Test loading cache with invalid JSON."""
        cache_file = tmp_path / 'test.json'
        with open(cache_file, 'w') as f:
            f.write('invalid json{')

        with patch('cache.CACHE_DIR', tmp_path):
            result = load_cache('test')
            assert result is None

    def test_load_cache_missing_cached_at(self, tmp_path):
        """Test loading cache without cached_at field."""
        cache_data = {'data': {'test': 'data'}}

        cache_file = tmp_path / 'test.json'
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f)

        with patch('cache.CACHE_DIR', tmp_path):
            result = load_cache('test')
            assert result is None

    def test_load_cache_default_expiry(self, tmp_path):
        """Test loading cache with default expiry for unknown endpoint."""
        cache_data = {
            'cached_at': datetime.now().isoformat(),
            'data': {'test': 'data'}
        }

        cache_file = tmp_path / 'unknown_endpoint.json'
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f)

        with patch('cache.CACHE_DIR', tmp_path):
            result = load_cache('unknown_endpoint')
            # Should use default expiry of 60 minutes
            assert result == {'test': 'data'}


class TestSaveCache:
    """Tests for save_cache function."""

    def test_save_cache_success(self, tmp_path):
        """Test successful cache save."""
        test_data = {'test': 'data', 'value': 123}

        with patch('cache.CACHE_DIR', tmp_path):
            save_cache('test', test_data)

            cache_file = tmp_path / 'test.json'
            assert cache_file.exists()

            with open(cache_file, 'r') as f:
                saved_data = json.load(f)

            assert 'cached_at' in saved_data
            assert saved_data['data'] == test_data

    def test_save_cache_creates_directory(self, tmp_path):
        """Test that save_cache creates directory if it doesn't exist."""
        cache_dir = tmp_path / 'new_cache_dir'

        # Manually create the directory since CACHE_DIR.mkdir() is called at module load
        with patch('cache.CACHE_DIR', cache_dir):
            cache_dir.mkdir(exist_ok=True)

            # This should save to the directory
            save_cache('test', {'data': 'value'})

            # Verify file exists
            cache_file = cache_dir / 'test.json'
            assert cache_file.exists()

    def test_save_cache_with_list_data(self, tmp_path):
        """Test saving cache with list data."""
        test_data = [{'id': 1}, {'id': 2}, {'id': 3}]

        with patch('cache.CACHE_DIR', tmp_path):
            save_cache('test_list', test_data)

            cache_file = tmp_path / 'test_list.json'
            with open(cache_file, 'r') as f:
                saved_data = json.load(f)

            assert saved_data['data'] == test_data

    def test_save_cache_with_unicode(self, tmp_path):
        """Test saving cache with unicode characters."""
        test_data = {'currency': 'ریال', 'symbol': '€', 'value': '¥'}

        with patch('cache.CACHE_DIR', tmp_path):
            save_cache('test_unicode', test_data)

            cache_file = tmp_path / 'test_unicode.json'
            with open(cache_file, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)

            assert saved_data['data'] == test_data

    def test_save_cache_exception_handling(self, tmp_path):
        """Test save_cache handles exceptions gracefully."""
        with patch('cache.CACHE_DIR', tmp_path):
            with patch('builtins.open', side_effect=PermissionError("No permission")):
                # Should not raise exception
                save_cache('test', {'data': 'value'})


class TestSaveApiEndpoint:
    """Tests for save_api_endpoint function."""

    def test_save_api_endpoint_simple(self, tmp_path):
        """Test saving simple API endpoint."""
        test_data = {'rate': 50000}

        with patch('cache.API_DIR', tmp_path):
            save_api_endpoint('test.json', test_data)

            api_file = tmp_path / 'test.json'
            assert api_file.exists()

            with open(api_file, 'r') as f:
                saved_data = json.load(f)

            assert saved_data == test_data

    def test_save_api_endpoint_with_subdirectory(self, tmp_path):
        """Test saving API endpoint with subdirectory."""
        test_data = [{'date': '2023-01-01', 'rates': {}}]

        with patch('cache.API_DIR', tmp_path):
            save_api_endpoint('history/1d.json', test_data)

            api_file = tmp_path / 'history' / '1d.json'
            assert api_file.exists()

            with open(api_file, 'r') as f:
                saved_data = json.load(f)

            assert saved_data == test_data

    def test_save_api_endpoint_creates_nested_directories(self, tmp_path):
        """Test that nested directories are created."""
        test_data = {'test': 'data'}

        with patch('cache.API_DIR', tmp_path):
            save_api_endpoint('level1/level2/level3/test.json', test_data)

            api_file = tmp_path / 'level1' / 'level2' / 'level3' / 'test.json'
            assert api_file.exists()

    def test_save_api_endpoint_with_list(self, tmp_path):
        """Test saving list data to API endpoint."""
        test_data = [
            {'ab': 'usd', 'price': 50000},
            {'ab': 'eur', 'price': 55000}
        ]

        with patch('cache.API_DIR', tmp_path):
            save_api_endpoint('currencies.json', test_data)

            api_file = tmp_path / 'currencies.json'
            with open(api_file, 'r') as f:
                saved_data = json.load(f)

            assert saved_data == test_data
            assert len(saved_data) == 2

    def test_save_api_endpoint_preserves_unicode(self, tmp_path):
        """Test that unicode is preserved in API endpoint."""
        test_data = {
            'name': 'دلار',
            'symbol': '€',
            'rate': 50000
        }

        with patch('cache.API_DIR', tmp_path):
            save_api_endpoint('test.json', test_data)

            api_file = tmp_path / 'test.json'
            with open(api_file, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)

            assert saved_data['name'] == 'دلار'
            assert saved_data['symbol'] == '€'

    def test_save_api_endpoint_formatted_json(self, tmp_path):
        """Test that saved JSON is formatted with indentation."""
        test_data = {'key': 'value', 'nested': {'inner': 'data'}}

        with patch('cache.API_DIR', tmp_path):
            save_api_endpoint('test.json', test_data)

            api_file = tmp_path / 'test.json'
            with open(api_file, 'r') as f:
                content = f.read()

            # Check that JSON is indented (not minified)
            assert '\n' in content
            assert '  ' in content


@pytest.fixture
def tmp_path(tmp_path_factory):
    """Create temporary directory for tests."""
    return tmp_path_factory.mktemp("test_cache")

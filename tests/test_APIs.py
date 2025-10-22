"""Unit tests for APIs.py module."""

import pytest
from APIs import APIs


class TestAPIsEnum:
    """Tests for the APIs enum."""

    def test_hansha_latest_api(self):
        """Test Hansha Latest API configuration."""
        api = APIs.HANSHA_LATEST
        assert api.title == 'Hansha Latest Rates'
        assert api.url == 'https://hansha.online/latest'

    def test_hansha_history_api(self):
        """Test Hansha History API configuration."""
        api = APIs.HANSHA_HISTORY
        assert api.title == 'Hansha History'
        assert api.url == 'https://hansha.online/history'

    def test_crypto_rates_api(self):
        """Test CoinGecko Crypto Rates API configuration."""
        api = APIs.CRYPTO_RATES
        assert api.title == 'CoinGecko Crypto Rates'
        assert 'api.coingecko.com' in api.url
        assert 'vs_currency=usd' in api.url
        assert 'order=market_cap_desc' in api.url
        assert 'per_page=100' in api.url

    def test_bonbast_api(self):
        """Test Bonbast API configuration."""
        api = APIs.BONBAST
        assert api.title == 'Bonbast Currency'
        assert api.url == 'bonbast export'

    def test_enum_value_structure(self):
        """Test that enum values have correct structure."""
        for api in APIs:
            assert 'title' in api.value
            assert 'url' in api.value
            assert isinstance(api.title, str)
            assert isinstance(api.url, str)

    def test_enum_iteration(self):
        """Test iterating over APIs enum."""
        api_list = list(APIs)
        assert len(api_list) == 4
        assert APIs.HANSHA_LATEST in api_list
        assert APIs.HANSHA_HISTORY in api_list
        assert APIs.CRYPTO_RATES in api_list
        assert APIs.BONBAST in api_list

    def test_enum_member_access(self):
        """Test accessing enum members."""
        assert APIs['HANSHA_LATEST'] == APIs.HANSHA_LATEST
        assert APIs['CRYPTO_RATES'] == APIs.CRYPTO_RATES

    def test_enum_properties_are_not_none(self):
        """Test that no enum properties are None or empty."""
        for api in APIs:
            assert api.title is not None
            assert api.url is not None
            assert len(api.title) > 0
            assert len(api.url) > 0

    def test_title_property(self):
        """Test title property returns string."""
        for api in APIs:
            title = api.title
            assert isinstance(title, str)
            assert len(title) > 0

    def test_url_property(self):
        """Test url property returns string."""
        for api in APIs:
            url = api.url
            assert isinstance(url, str)
            assert len(url) > 0

    def test_hansha_urls_are_https(self):
        """Test that Hansha URLs use HTTPS."""
        assert APIs.HANSHA_LATEST.url.startswith('https://')
        assert APIs.HANSHA_HISTORY.url.startswith('https://')

    def test_coingecko_url_is_https(self):
        """Test that CoinGecko URL uses HTTPS."""
        assert APIs.CRYPTO_RATES.url.startswith('https://')

    def test_enum_members_are_unique(self):
        """Test that all enum members have unique values."""
        urls = [api.url for api in APIs]
        titles = [api.title for api in APIs]
        assert len(urls) == len(set(urls))
        assert len(titles) == len(set(titles))

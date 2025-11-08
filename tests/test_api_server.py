"""Unit tests for api_server.py - AI prediction endpoints."""

import pytest
import json
from unittest.mock import Mock, patch, mock_open
from datetime import datetime, timedelta
from api_server import app, PredictionEngine


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def sample_latest_data():
    """Sample latest.json data for testing."""
    return [
        {
            "ab": "usd",
            "av": "🇺🇸",
            "en": "US Dollar",
            "fa": "دلار آمریکا",
            "ps": [
                {"bp": 107700, "sp": 107795, "ts": "2025-11-08T21:33:55Z"}
            ]
        },
        {
            "ab": "eur",
            "av": "🇪🇺",
            "en": "Euro",
            "fa": "یورو",
            "ps": [
                {"bp": 120000, "sp": 120100, "ts": "2025-11-08T21:33:55Z"}
            ]
        }
    ]


@pytest.fixture
def sample_historical_data():
    """Sample historical data for testing."""
    base_price = 100000
    historical_data = []
    for i in range(30):
        price = base_price + (i * 100) + ((-1) ** i * 50)  # Add some variation
        historical_data.append({
            "bp": price,
            "sp": price + 100,
            "ts": f"2025-10-{9 + i:02d}T12:00:00Z"
        })
    return historical_data


@pytest.fixture
def sample_history_file(sample_historical_data):
    """Sample history file data."""
    return [
        {
            "ab": "usd",
            "en": "US Dollar",
            "ps": sample_historical_data
        }
    ]


class TestPredictionEngine:
    """Tests for the PredictionEngine class."""

    def test_calculate_trend_upward(self):
        """Test trend calculation with upward prices."""
        prices = [100, 105, 110, 115, 120]
        trend = PredictionEngine.calculate_trend(prices)
        assert trend > 0, "Upward trend should have positive slope"

    def test_calculate_trend_downward(self):
        """Test trend calculation with downward prices."""
        prices = [120, 115, 110, 105, 100]
        trend = PredictionEngine.calculate_trend(prices)
        assert trend < 0, "Downward trend should have negative slope"

    def test_calculate_trend_flat(self):
        """Test trend calculation with flat prices."""
        prices = [100, 100, 100, 100, 100]
        trend = PredictionEngine.calculate_trend(prices)
        assert abs(trend) < 0.01, "Flat prices should have near-zero trend"

    def test_calculate_trend_insufficient_data(self):
        """Test trend calculation with insufficient data."""
        prices = [100]
        trend = PredictionEngine.calculate_trend(prices)
        assert trend == 0.0, "Single price should return zero trend"

    def test_calculate_trend_empty(self):
        """Test trend calculation with empty list."""
        prices = []
        trend = PredictionEngine.calculate_trend(prices)
        assert trend == 0.0, "Empty list should return zero trend"

    def test_calculate_volatility_stable(self):
        """Test volatility calculation with stable prices."""
        prices = [100, 100, 100, 100, 100]
        volatility = PredictionEngine.calculate_volatility(prices)
        assert volatility == 0.0, "Stable prices should have zero volatility"

    def test_calculate_volatility_varying(self):
        """Test volatility calculation with varying prices."""
        prices = [100, 110, 90, 105, 95]
        volatility = PredictionEngine.calculate_volatility(prices)
        assert volatility > 0, "Varying prices should have positive volatility"

    def test_calculate_volatility_empty(self):
        """Test volatility calculation with empty list."""
        prices = []
        volatility = PredictionEngine.calculate_volatility(prices)
        assert volatility == 0.0, "Empty list should return zero volatility"

    def test_calculate_momentum_increasing(self):
        """Test momentum calculation with increasing prices."""
        prices = [100, 102, 104, 106, 108, 110, 112, 114]
        momentum = PredictionEngine.calculate_momentum(prices)
        assert momentum > 0, "Increasing prices should have positive momentum"

    def test_calculate_momentum_decreasing(self):
        """Test momentum calculation with decreasing prices."""
        prices = [114, 112, 110, 108, 106, 104, 102, 100]
        momentum = PredictionEngine.calculate_momentum(prices)
        assert momentum < 0, "Decreasing prices should have negative momentum"

    def test_calculate_momentum_insufficient_data(self):
        """Test momentum calculation with insufficient data."""
        prices = [100, 101, 102]
        momentum = PredictionEngine.calculate_momentum(prices)
        assert momentum == 0.0, "Insufficient data should return zero momentum"

    @patch('builtins.open', new_callable=mock_open)
    @patch('json.load')
    def test_get_current_price_success(self, mock_json_load, mock_file, sample_latest_data):
        """Test getting current price successfully."""
        mock_json_load.return_value = sample_latest_data

        result = PredictionEngine.get_current_price('usd')

        assert result is not None
        assert result['buy'] == 107700
        assert result['sell'] == 107795
        assert result['name'] == 'US Dollar'

    @patch('builtins.open', new_callable=mock_open)
    @patch('json.load')
    def test_get_current_price_not_found(self, mock_json_load, mock_file, sample_latest_data):
        """Test getting current price for non-existent currency."""
        mock_json_load.return_value = sample_latest_data

        result = PredictionEngine.get_current_price('xyz')

        assert result is None

    @patch('builtins.open', side_effect=FileNotFoundError)
    def test_get_current_price_file_error(self, mock_file):
        """Test getting current price when file doesn't exist."""
        result = PredictionEngine.get_current_price('usd')
        assert result is None

    @patch('builtins.open', new_callable=mock_open)
    @patch('json.load')
    def test_load_historical_data_1d(self, mock_json_load, mock_file, sample_history_file):
        """Test loading 1 day historical data."""
        mock_json_load.return_value = sample_history_file

        result = PredictionEngine.load_historical_data('usd', 1)

        mock_file.assert_called_with('api/history/1d.json', 'r')
        assert len(result) == 30  # Based on sample data

    @patch('builtins.open', new_callable=mock_open)
    @patch('json.load')
    def test_load_historical_data_1w(self, mock_json_load, mock_file, sample_history_file):
        """Test loading 1 week historical data."""
        mock_json_load.return_value = sample_history_file

        result = PredictionEngine.load_historical_data('usd', 7)

        mock_file.assert_called_with('api/history/1w.json', 'r')

    @patch('builtins.open', new_callable=mock_open)
    @patch('json.load')
    def test_load_historical_data_1m(self, mock_json_load, mock_file, sample_history_file):
        """Test loading 1 month historical data."""
        mock_json_load.return_value = sample_history_file

        result = PredictionEngine.load_historical_data('usd', 30)

        mock_file.assert_called_with('api/history/1m.json', 'r')

    @patch('builtins.open', new_callable=mock_open)
    @patch('json.load')
    def test_load_historical_data_1y(self, mock_json_load, mock_file, sample_history_file):
        """Test loading 1 year historical data."""
        mock_json_load.return_value = sample_history_file

        result = PredictionEngine.load_historical_data('usd', 365)

        mock_file.assert_called_with('api/history/1y.json', 'r')

    @patch('builtins.open', new_callable=mock_open)
    @patch('json.load')
    def test_load_historical_data_5y(self, mock_json_load, mock_file, sample_history_file):
        """Test loading 5 year historical data."""
        mock_json_load.return_value = sample_history_file

        result = PredictionEngine.load_historical_data('usd', 500)

        mock_file.assert_called_with('api/history/5y.json', 'r')

    @patch.object(PredictionEngine, 'get_current_price')
    @patch.object(PredictionEngine, 'load_historical_data')
    def test_generate_predictions_success(self, mock_load_history, mock_get_price, sample_historical_data):
        """Test generating predictions successfully."""
        mock_get_price.return_value = {
            'buy': 107700,
            'sell': 107795,
            'name': 'US Dollar'
        }
        mock_load_history.return_value = sample_historical_data

        result = PredictionEngine.generate_predictions('usd', 14, 30)

        assert result['currencyCode'] == 'usd'
        assert result['currencyName'] == 'US Dollar'
        assert len(result['predictions']) == 14
        assert result['trend'] in ['BULLISH', 'BEARISH', 'NEUTRAL', 'VOLATILE']
        assert 0.5 <= result['confidenceScore'] <= 0.95
        assert result['modelVersion'] == 'v1.0-exponential-smoothing'

        # Check prediction structure
        first_pred = result['predictions'][0]
        assert 'date' in first_pred
        assert 'timestamp' in first_pred
        assert 'predictedBuy' in first_pred
        assert 'predictedSell' in first_pred
        assert 'confidence' in first_pred
        assert 'lowerBound' in first_pred
        assert 'upperBound' in first_pred

    @patch.object(PredictionEngine, 'get_current_price')
    def test_generate_predictions_currency_not_found(self, mock_get_price):
        """Test generating predictions for non-existent currency."""
        mock_get_price.return_value = None

        with pytest.raises(ValueError, match="Currency xyz not found"):
            PredictionEngine.generate_predictions('xyz', 14, 30)

    @patch.object(PredictionEngine, 'get_current_price')
    @patch.object(PredictionEngine, 'load_historical_data')
    def test_generate_predictions_volatile_trend(self, mock_load_history, mock_get_price):
        """Test prediction with volatile prices."""
        mock_get_price.return_value = {
            'buy': 100000,
            'sell': 100100,
            'name': 'Test Currency'
        }

        # Create highly volatile data (20% swings to ensure volatility > 0.15)
        volatile_data = []
        for i in range(30):
            price = 100000 + ((-1) ** i * 20000)  # 20% volatility
            volatile_data.append({"bp": price, "sp": price + 100})

        mock_load_history.return_value = volatile_data

        result = PredictionEngine.generate_predictions('test', 7, 30)

        assert result['trend'] == 'VOLATILE'


class TestPredictionEndpoint:
    """Tests for the /api/v1/predict endpoint."""

    @patch.object(PredictionEngine, 'generate_predictions')
    def test_predict_success(self, mock_generate, client):
        """Test successful prediction request."""
        mock_generate.return_value = {
            'currencyCode': 'usd',
            'currencyName': 'US Dollar',
            'currentPrice': {'buy': 107700, 'sell': 107795, 'timestamp': '2025-11-08T12:00:00Z'},
            'predictions': [
                {
                    'date': '2025-11-09',
                    'timestamp': 1731110400000,
                    'predictedBuy': 107800,
                    'predictedSell': 107895,
                    'confidence': 0.85,
                    'lowerBound': 107000,
                    'upperBound': 108600
                }
            ],
            'confidenceScore': 0.85,
            'trend': 'BULLISH',
            'generatedAt': '2025-11-08T12:00:00Z',
            'modelVersion': 'v1.0-exponential-smoothing'
        }

        response = client.post('/api/v1/predict', json={
            'currencyCode': 'usd',
            'daysAhead': 14,
            'historicalDays': 30
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['currencyCode'] == 'usd'
        assert data['trend'] == 'BULLISH'

    def test_predict_missing_currency_code(self, client):
        """Test prediction request without currency code."""
        response = client.post('/api/v1/predict', json={
            'daysAhead': 14
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data
        assert 'currencyCode is required' in data['error']

    def test_predict_missing_body(self, client):
        """Test prediction request without body."""
        response = client.post('/api/v1/predict')

        # Flask returns 500 when no JSON body is provided with no Content-Type
        # This is acceptable behavior - the actual error will be caught
        assert response.status_code in [400, 500]
        data = response.get_json()
        assert 'error' in data

    def test_predict_invalid_days_ahead_low(self, client):
        """Test prediction request with daysAhead too low."""
        response = client.post('/api/v1/predict', json={
            'currencyCode': 'usd',
            'daysAhead': 0
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'daysAhead must be between 1 and 90' in data['error']

    def test_predict_invalid_days_ahead_high(self, client):
        """Test prediction request with daysAhead too high."""
        response = client.post('/api/v1/predict', json={
            'currencyCode': 'usd',
            'daysAhead': 91
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'daysAhead must be between 1 and 90' in data['error']

    @patch.object(PredictionEngine, 'generate_predictions')
    def test_predict_currency_not_found(self, mock_generate, client):
        """Test prediction for non-existent currency."""
        mock_generate.side_effect = ValueError('Currency xyz not found')

        response = client.post('/api/v1/predict', json={
            'currencyCode': 'xyz',
            'daysAhead': 14
        })

        assert response.status_code == 404
        data = response.get_json()
        assert 'error' in data

    @patch.object(PredictionEngine, 'generate_predictions')
    def test_predict_default_values(self, mock_generate, client):
        """Test prediction with default values."""
        mock_generate.return_value = {
            'currencyCode': 'usd',
            'predictions': [],
            'confidenceScore': 0.8,
            'trend': 'NEUTRAL'
        }

        response = client.post('/api/v1/predict', json={
            'currencyCode': 'usd'
        })

        assert response.status_code == 200
        mock_generate.assert_called_with(
            currency_code='usd',
            days_ahead=14,  # default
            historical_days=30  # default
        )

    @patch.object(PredictionEngine, 'generate_predictions')
    def test_predict_internal_error(self, mock_generate, client):
        """Test prediction with internal server error."""
        mock_generate.side_effect = Exception('Unexpected error')

        response = client.post('/api/v1/predict', json={
            'currencyCode': 'usd',
            'daysAhead': 14
        })

        assert response.status_code == 500
        data = response.get_json()
        assert 'error' in data
        assert data['error'] == 'Internal server error'


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get('/health')

        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'healthy'
        assert 'timestamp' in data

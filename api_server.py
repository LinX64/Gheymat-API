from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json
import math
import os

app = Flask(__name__)
CORS(app)

class PredictionEngine:
    """AI prediction engine using exponential smoothing and trend analysis"""

    @staticmethod
    def load_historical_data(currency_code: str, historical_days: int) -> List[Dict]:
        """Load historical data based on requested days"""
        history_file = None

        if historical_days <= 1:
            history_file = 'api/history/1d.json'
        elif historical_days <= 7:
            history_file = 'api/history/1w.json'
        elif historical_days <= 30:
            history_file = 'api/history/1m.json'
        elif historical_days <= 365:
            history_file = 'api/history/1y.json'
        else:
            history_file = 'api/history/5y.json'

        try:
            with open(history_file, 'r') as f:
                history_data = json.load(f)

            # Find currency in history
            for currency in history_data:
                if currency.get('ab', '').lower() == currency_code.lower():
                    return currency.get('ps', [])

            return []
        except Exception as e:
            print(f"Error loading historical data: {e}")
            return []

    @staticmethod
    def get_current_price(currency_code: str) -> Optional[Dict]:
        """Get current price from latest.json"""
        try:
            with open('api/latest.json', 'r') as f:
                latest_data = json.load(f)

            for currency in latest_data:
                if currency.get('ab', '').lower() == currency_code.lower():
                    prices = currency.get('ps', [])
                    if prices:
                        return {
                            'buy': prices[0].get('bp', 0),
                            'sell': prices[0].get('sp', 0),
                            'name': currency.get('en', currency_code.upper())
                        }
            return None
        except Exception as e:
            print(f"Error loading current price: {e}")
            return None

    @staticmethod
    def calculate_trend(prices: List[float]) -> float:
        """Calculate trend using linear regression"""
        if len(prices) < 2:
            return 0.0

        n = len(prices)
        sum_x = sum(range(n))
        sum_y = sum(prices)
        sum_xy = sum(i * price for i, price in enumerate(prices))
        sum_xx = sum(i * i for i in range(n))

        if n * sum_xx - sum_x * sum_x == 0:
            return 0.0

        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_xx - sum_x * sum_x)
        avg = sum_y / n if n > 0 else 0

        return slope / avg if avg != 0 else 0.0

    @staticmethod
    def calculate_volatility(prices: List[float]) -> float:
        """Calculate volatility using standard deviation"""
        if not prices:
            return 0.0

        mean = sum(prices) / len(prices)
        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        std_dev = math.sqrt(variance)

        return std_dev / mean if mean != 0 else 0.0

    @staticmethod
    def calculate_momentum(prices: List[float]) -> float:
        """Calculate momentum (recent vs historical average)"""
        if len(prices) < 4:
            return 0.0

        recent_size = min(len(prices) // 4, 7)
        recent_prices = prices[-recent_size:]
        older_prices = prices[:-recent_size]

        if not older_prices:
            return 0.0

        recent_avg = sum(recent_prices) / len(recent_prices)
        older_avg = sum(older_prices) / len(older_prices)

        return (recent_avg - older_avg) / older_avg if older_avg != 0 else 0.0

    @classmethod
    def generate_predictions(cls, currency_code: str, days_ahead: int, historical_days: int) -> Dict:
        """Generate AI predictions for a currency"""

        # Load data
        historical_data = cls.load_historical_data(currency_code, historical_days)
        current_price_data = cls.get_current_price(currency_code)

        if not current_price_data:
            raise ValueError(f"Currency {currency_code} not found")

        current_buy = current_price_data['buy']
        current_sell = current_price_data['sell']
        currency_name = current_price_data['name']

        # Analyze historical data
        buy_prices = [p.get('bp', 0) for p in historical_data if p.get('bp')]

        trend = cls.calculate_trend(buy_prices) if buy_prices else 0.0
        volatility = cls.calculate_volatility(buy_prices) if buy_prices else 0.0
        momentum = cls.calculate_momentum(buy_prices) if buy_prices else 0.0

        # Generate predictions
        alpha = 0.3
        trend_adjustment = (trend + momentum) / 2.0

        predictions = []
        last_buy = current_buy
        last_sell = current_sell

        for day_offset in range(1, days_ahead + 1):
            prediction_date = datetime.now() + timedelta(days=day_offset)

            # Apply exponential smoothing with trend
            trend_factor = 1.0 + (trend_adjustment * (day_offset / 30.0))
            predicted_buy = last_buy * trend_factor
            predicted_sell = last_sell * trend_factor

            # Calculate confidence
            time_decay = 1.0 - (day_offset / (days_ahead * 1.5))
            volatility_penalty = 1.0 - min(volatility, 0.5)
            confidence = max(0.5, min(0.95, 0.85 * time_decay * volatility_penalty))

            # Calculate bounds
            bound_range = predicted_buy * volatility * (1.0 + day_offset * 0.1)
            lower_bound = predicted_buy - bound_range
            upper_bound = predicted_buy + bound_range

            predictions.append({
                'date': prediction_date.strftime('%Y-%m-%d'),
                'timestamp': int(prediction_date.timestamp() * 1000),
                'predictedBuy': int(predicted_buy),
                'predictedSell': int(predicted_sell),
                'confidence': round(confidence, 3),
                'lowerBound': int(lower_bound),
                'upperBound': int(upper_bound)
            })

            # Update for next iteration
            last_buy = alpha * predicted_buy + (1 - alpha) * last_buy
            last_sell = alpha * predicted_sell + (1 - alpha) * last_sell

        # Determine trend
        combined_trend = trend + momentum
        if volatility > 0.15:
            prediction_trend = 'VOLATILE'
        elif combined_trend > 0.01:
            prediction_trend = 'BULLISH'
        elif combined_trend < -0.01:
            prediction_trend = 'BEARISH'
        else:
            prediction_trend = 'NEUTRAL'

        # Calculate overall confidence
        data_confidence = min(1.0, len(buy_prices) / 100.0) if buy_prices else 0.5
        volatility_confidence = 1.0 - min(volatility, 0.5)
        time_confidence = 1.0 - min(0.5, days_ahead / 100.0)
        overall_confidence = (data_confidence * 0.3 + volatility_confidence * 0.4 + time_confidence * 0.3)
        overall_confidence = max(0.5, min(0.95, overall_confidence))

        return {
            'currencyCode': currency_code,
            'currencyName': currency_name,
            'currentPrice': {
                'buy': current_buy,
                'sell': current_sell,
                'timestamp': datetime.now().isoformat() + 'Z'
            },
            'predictions': predictions,
            'confidenceScore': round(overall_confidence, 3),
            'trend': prediction_trend,
            'generatedAt': datetime.now().isoformat() + 'Z',
            'modelVersion': 'v1.0-exponential-smoothing'
        }


@app.route('/api/v1/predict', methods=['POST'])
def predict():
    """AI prediction endpoint for paid users"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'Request body required'}), 400

        currency_code = data.get('currencyCode')
        days_ahead = data.get('daysAhead', 14)
        historical_days = data.get('historicalDays', 30)

        if not currency_code:
            return jsonify({'error': 'currencyCode is required'}), 400

        if days_ahead < 1 or days_ahead > 90:
            return jsonify({'error': 'daysAhead must be between 1 and 90'}), 400

        # Generate predictions
        result = PredictionEngine.generate_predictions(
            currency_code=currency_code,
            days_ahead=days_ahead,
            historical_days=historical_days
        )

        return jsonify(result), 200

    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        print(f"Prediction error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()}), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)

#!/usr/bin/env python3
"""
Generate static AI prediction files for all currencies.
This script creates pre-computed predictions that can be served as static JSON files.
"""

import json
import os
from datetime import datetime
from typing import List, Dict
from api_server import PredictionEngine


def get_available_currencies() -> List[Dict]:
    """Get list of all available currencies from latest.json."""
    try:
        with open('api/latest.json', 'r') as f:
            currencies = json.load(f)
        return currencies
    except Exception as e:
        print(f"Error loading currencies: {e}")
        return []


def generate_prediction_for_currency(currency_code: str, days_ahead: int, historical_days: int) -> Dict:
    """Generate prediction for a single currency."""
    try:
        prediction = PredictionEngine.generate_predictions(
            currency_code=currency_code,
            days_ahead=days_ahead,
            historical_days=historical_days
        )
        return {
            'success': True,
            'data': prediction
        }
    except ValueError as e:
        print(f"  ⚠️  {currency_code.upper()}: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
    except Exception as e:
        print(f"  ❌ {currency_code.upper()}: Unexpected error - {str(e)}")
        return {
            'success': False,
            'error': 'Internal server error'
        }


def generate_all_predictions():
    """Generate predictions for all currencies with different time ranges."""
    print("=" * 70)
    print("AI PREDICTION GENERATOR")
    print("=" * 70)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Create predictions directory
    predictions_dir = 'api/predictions'
    os.makedirs(predictions_dir, exist_ok=True)

    # Get all currencies
    currencies = get_available_currencies()
    if not currencies:
        print("❌ No currencies found!")
        return

    print(f"Found {len(currencies)} currencies")
    print()

    # Prediction configurations
    configs = [
        {'name': 'short', 'days_ahead': 7, 'historical_days': 30},
        {'name': 'medium', 'days_ahead': 14, 'historical_days': 60},
        {'name': 'long', 'days_ahead': 30, 'historical_days': 90},
    ]

    stats = {
        'total_currencies': len(currencies),
        'successful': 0,
        'failed': 0,
        'generated_files': []
    }

    # Generate predictions for each currency and configuration
    for config in configs:
        print(f"Generating {config['name'].upper()} predictions ({config['days_ahead']} days)...")
        print("-" * 70)

        config_predictions = []

        for currency in currencies:
            currency_code = currency.get('ab', '').lower()
            if not currency_code:
                continue

            result = generate_prediction_for_currency(
                currency_code=currency_code,
                days_ahead=config['days_ahead'],
                historical_days=config['historical_days']
            )

            if result['success']:
                config_predictions.append({
                    'currencyCode': currency_code,
                    'prediction': result['data']
                })
                stats['successful'] += 1
                print(f"  ✅ {currency_code.upper()}")
            else:
                stats['failed'] += 1

        # Save predictions for this configuration
        output_file = f"{predictions_dir}/{config['name']}.json"
        with open(output_file, 'w') as f:
            json.dump({
                'generatedAt': datetime.now().isoformat() + 'Z',
                'daysAhead': config['days_ahead'],
                'historicalDays': config['historical_days'],
                'totalCurrencies': len(config_predictions),
                'predictions': config_predictions
            }, f, indent=2)

        stats['generated_files'].append(output_file)
        print(f"  💾 Saved {len(config_predictions)} predictions to {output_file}")
        print()

    # Generate index file
    index_file = f"{predictions_dir}/index.json"
    with open(index_file, 'w') as f:
        json.dump({
            'generatedAt': datetime.now().isoformat() + 'Z',
            'availableConfigurations': [
                {
                    'name': config['name'],
                    'daysAhead': config['days_ahead'],
                    'historicalDays': config['historical_days'],
                    'endpoint': f"predictions/{config['name']}.json"
                }
                for config in configs
            ],
            'stats': {
                'totalCurrencies': stats['total_currencies'],
                'successfulPredictions': stats['successful'],
                'failedPredictions': stats['failed']
            }
        }, f, indent=2)

    stats['generated_files'].append(index_file)
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total currencies: {stats['total_currencies']}")
    print(f"Successful predictions: {stats['successful']}")
    print(f"Failed predictions: {stats['failed']}")
    print(f"Files generated: {len(stats['generated_files'])}")
    print()
    print("Generated files:")
    for file in stats['generated_files']:
        file_size = os.path.getsize(file) / 1024  # Convert to KB
        print(f"  - {file} ({file_size:.2f} KB)")
    print()
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)


if __name__ == '__main__':
    generate_all_predictions()

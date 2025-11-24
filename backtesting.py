"""
Backtesting Module for Currency Prediction Accuracy Validation
Validates predictions against actual historical data to measure accuracy
"""

import json
import math
from typing import List, Dict, Any, Tuple
from datetime import datetime, timedelta
from collections import defaultdict


class PredictionBacktester:
    """Backtest prediction models against historical data"""

    @staticmethod
    def load_historical_data(currency_code: str, history_file: str = 'api/history/all.json') -> List[Dict]:
        """Load historical data for backtesting"""
        try:
            with open(history_file, 'r') as f:
                history_data = json.load(f)

            for currency in history_data:
                if currency.get('ab', '').lower() == currency_code.lower():
                    return currency.get('ps', [])
            return []
        except Exception as e:
            print(f"Error loading historical data: {e}")
            return []

    @staticmethod
    def calculate_accuracy_metrics(actual_prices: List[float],
                                   predicted_prices: List[float]) -> Dict[str, float]:
        """
        Calculate comprehensive accuracy metrics:
        - MAE (Mean Absolute Error)
        - RMSE (Root Mean Square Error)
        - MAPE (Mean Absolute Percentage Error)
        - Directional Accuracy (trend prediction accuracy)
        - R-squared (coefficient of determination)
        """
        if not actual_prices or not predicted_prices or len(actual_prices) != len(predicted_prices):
            return {
                'mae': 0.0,
                'rmse': 0.0,
                'mape': 0.0,
                'directional_accuracy': 0.0,
                'r_squared': 0.0,
                'accuracy_percentage': 0.0,
                'error': 'Invalid data'
            }

        n = len(actual_prices)

        # MAE - Mean Absolute Error
        mae = sum(abs(a - p) for a, p in zip(actual_prices, predicted_prices)) / n

        # RMSE - Root Mean Square Error
        mse = sum((a - p) ** 2 for a, p in zip(actual_prices, predicted_prices)) / n
        rmse = math.sqrt(mse)

        # MAPE - Mean Absolute Percentage Error (convert to percentage)
        mape_values = [abs((a - p) / a) * 100 for a, p in zip(actual_prices, predicted_prices) if a != 0]
        mape = sum(mape_values) / len(mape_values) if mape_values else 0.0

        # Directional Accuracy (did we predict the trend correctly?)
        correct_directions = 0
        for i in range(1, n):
            actual_direction = actual_prices[i] - actual_prices[i-1]
            predicted_direction = predicted_prices[i] - predicted_prices[i-1]
            if (actual_direction > 0 and predicted_direction > 0) or \
               (actual_direction < 0 and predicted_direction < 0) or \
               (actual_direction == 0 and predicted_direction == 0):
                correct_directions += 1

        directional_accuracy = (correct_directions / (n - 1) * 100) if n > 1 else 0.0

        # R-squared (coefficient of determination)
        mean_actual = sum(actual_prices) / n
        ss_total = sum((a - mean_actual) ** 2 for a in actual_prices)
        ss_residual = sum((a - p) ** 2 for a, p in zip(actual_prices, predicted_prices))

        r_squared = 1 - (ss_residual / ss_total) if ss_total != 0 else 0.0
        r_squared = max(0.0, r_squared)  # R-squared can be negative for very bad fits

        # Overall accuracy percentage (100% - MAPE)
        accuracy_percentage = max(0.0, 100.0 - mape)

        return {
            'mae': round(mae, 2),
            'rmse': round(rmse, 2),
            'mape': round(mape, 2),
            'directional_accuracy': round(directional_accuracy, 2),
            'r_squared': round(r_squared, 4),
            'accuracy_percentage': round(accuracy_percentage, 2),
            'samples': n
        }

    @staticmethod
    def walk_forward_validation(currency_code: str,
                                prediction_days: int = 7,
                                test_periods: int = 10,
                                use_full_history: bool = True) -> Dict[str, Any]:
        """
        Perform walk-forward validation:
        - Train on historical data
        - Predict N days ahead
        - Compare with actual data
        - Move forward and repeat
        """
        from api_server import AdvancedPredictionEngine

        print(f"\n{'='*70}")
        print(f"WALK-FORWARD VALIDATION: {currency_code.upper()}")
        print(f"{'='*70}")
        print(f"Prediction days: {prediction_days}")
        print(f"Test periods: {test_periods}")
        print(f"Full history: {use_full_history}")
        print()

        # Load historical data
        historical_data = PredictionBacktester.load_historical_data(currency_code)
        if len(historical_data) < 100:
            return {
                'error': f'Insufficient historical data for {currency_code}',
                'data_points': len(historical_data)
            }

        buy_prices = [p.get('bp', 0) for p in historical_data if p.get('bp')]
        if len(buy_prices) < 100:
            return {
                'error': f'Insufficient price data for {currency_code}',
                'price_points': len(buy_prices)
            }

        # Prepare test periods
        all_predictions = []
        all_actuals = []
        test_results = []

        # Use the last portion of data for testing
        test_start_index = len(buy_prices) - (test_periods * prediction_days) - 60

        if test_start_index < 60:
            test_start_index = 60

        for period_idx in range(test_periods):
            current_index = test_start_index + (period_idx * prediction_days)

            if current_index + prediction_days >= len(buy_prices):
                break

            # Training data up to current point
            training_data = buy_prices[:current_index]

            # Actual future prices
            actual_future = buy_prices[current_index:current_index + prediction_days]

            if len(actual_future) < prediction_days:
                break

            try:
                # Train model and generate predictions
                engine = AdvancedPredictionEngine()
                model = engine.train_ml_model(training_data, 'ensemble')

                if model:
                    predicted_future = engine.generate_ml_predictions(model, training_data, prediction_days)
                else:
                    # Fallback to trend-based prediction
                    predicted_future = []
                    last_price = training_data[-1]
                    # Simple trend calculation
                    recent_trend = (training_data[-1] - training_data[-30]) / training_data[-30] if len(training_data) >= 30 else 0
                    for i in range(prediction_days):
                        pred = last_price * (1 + recent_trend * (i + 1) / 30)
                        predicted_future.append(pred)

                if len(predicted_future) == prediction_days:
                    # Calculate metrics for this period
                    period_metrics = PredictionBacktester.calculate_accuracy_metrics(
                        actual_future,
                        predicted_future
                    )

                    test_results.append({
                        'period': period_idx + 1,
                        'training_size': len(training_data),
                        'metrics': period_metrics,
                        'start_price': training_data[-1],
                        'end_actual': actual_future[-1],
                        'end_predicted': predicted_future[-1]
                    })

                    all_predictions.extend(predicted_future)
                    all_actuals.extend(actual_future)

                    print(f"Period {period_idx + 1}/{test_periods}: Accuracy={period_metrics['accuracy_percentage']:.2f}%, MAPE={period_metrics['mape']:.2f}%")

            except Exception as e:
                print(f"  Error in period {period_idx + 1}: {e}")
                continue

        # Calculate overall metrics
        if all_predictions and all_actuals:
            overall_metrics = PredictionBacktester.calculate_accuracy_metrics(all_actuals, all_predictions)

            # Calculate statistics across periods
            accuracy_scores = [r['metrics']['accuracy_percentage'] for r in test_results]
            mape_scores = [r['metrics']['mape'] for r in test_results]

            avg_accuracy = sum(accuracy_scores) / len(accuracy_scores) if accuracy_scores else 0
            std_accuracy = math.sqrt(sum((a - avg_accuracy) ** 2 for a in accuracy_scores) / len(accuracy_scores)) if accuracy_scores else 0

            print(f"\n{'='*70}")
            print(f"VALIDATION RESULTS")
            print(f"{'='*70}")
            print(f"Overall Accuracy: {overall_metrics['accuracy_percentage']:.2f}%")
            print(f"Average Accuracy: {avg_accuracy:.2f}% ± {std_accuracy:.2f}%")
            print(f"Overall MAPE: {overall_metrics['mape']:.2f}%")
            print(f"Directional Accuracy: {overall_metrics['directional_accuracy']:.2f}%")
            print(f"R-squared: {overall_metrics['r_squared']:.4f}")
            print(f"{'='*70}\n")

            return {
                'currency': currency_code.upper(),
                'overall_metrics': overall_metrics,
                'average_accuracy': round(avg_accuracy, 2),
                'std_accuracy': round(std_accuracy, 2),
                'periods_tested': len(test_results),
                'period_results': test_results,
                'meets_95_target': overall_metrics['accuracy_percentage'] >= 95.0,
                'meets_98_target': overall_metrics['accuracy_percentage'] >= 98.0
            }
        else:
            return {
                'error': 'No valid predictions generated',
                'currency': currency_code.upper()
            }

    @staticmethod
    def validate_multiple_currencies(currency_codes: List[str],
                                     prediction_days: int = 7,
                                     test_periods: int = 10) -> Dict[str, Any]:
        """Validate predictions for multiple currencies"""
        print(f"\n{'='*70}")
        print(f"MULTI-CURRENCY VALIDATION")
        print(f"{'='*70}\n")

        results = {}
        summary = {
            'total_currencies': len(currency_codes),
            'successful': 0,
            'failed': 0,
            'meets_95_target': 0,
            'meets_98_target': 0,
            'average_accuracy': 0.0
        }

        for currency in currency_codes:
            result = PredictionBacktester.walk_forward_validation(
                currency,
                prediction_days=prediction_days,
                test_periods=test_periods
            )

            if 'error' not in result:
                results[currency.upper()] = result
                summary['successful'] += 1

                if result.get('meets_95_target'):
                    summary['meets_95_target'] += 1
                if result.get('meets_98_target'):
                    summary['meets_98_target'] += 1
            else:
                results[currency.upper()] = result
                summary['failed'] += 1

        # Calculate overall average accuracy
        successful_results = [r for r in results.values() if 'overall_metrics' in r]
        if successful_results:
            summary['average_accuracy'] = round(
                sum(r['overall_metrics']['accuracy_percentage'] for r in successful_results) / len(successful_results),
                2
            )

        print(f"\n{'='*70}")
        print(f"VALIDATION SUMMARY")
        print(f"{'='*70}")
        print(f"Total currencies tested: {summary['total_currencies']}")
        print(f"Successful validations: {summary['successful']}")
        print(f"Failed validations: {summary['failed']}")
        print(f"Meeting 95% target: {summary['meets_95_target']}")
        print(f"Meeting 98% target: {summary['meets_98_target']}")
        print(f"Average accuracy: {summary['average_accuracy']:.2f}%")
        print(f"{'='*70}\n")

        return {
            'summary': summary,
            'results': results,
            'timestamp': datetime.now().isoformat()
        }


if __name__ == '__main__':
    # Test with major currencies
    test_currencies = ['usd', 'eur', 'gbp', 'aed']
    results = PredictionBacktester.validate_multiple_currencies(
        test_currencies,
        prediction_days=7,
        test_periods=5
    )

    # Save results
    with open('api/backtest_results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Results saved to api/backtest_results.json")

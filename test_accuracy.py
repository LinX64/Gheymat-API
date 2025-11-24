import json
import sys
sys.path.insert(0, '/Users/mohsen/CurrencyCapPortal')

try:
    from api_server import AdvancedPredictionEngine
    from backtesting import PredictionBacktester

    print("=" * 70)
    print("TESTING ENHANCED PREDICTION SYSTEM")
    print("Target Accuracy: 95-98%")
    print("=" * 70)
    print()

    print("Testing prediction generation for USD...")
    try:
        result = AdvancedPredictionEngine.generate_predictions(
            currency_code='usd',
            days_ahead=7,
            use_full_history=True,
            use_ml=True
        )

        print(f"\nPrediction Results:")
        print(f"  Currency: {result['currencyCode']}")
        print(f"  Confidence Score: {result['confidenceScore']:.3f} ({result['confidenceScore']*100:.1f}%)")
        print(f"  Trend: {result['trend']}")
        print(f"  Models Used: {', '.join(result['modelInfo']['modelsUsed'])}")
        print(f"  Prediction Weights: {result['modelInfo']['predictionWeights']}")
        print(f"  Historical Data Points: {result['modelInfo']['historicalDataPoints']}")
        print(f"  Target Accuracy: {result['modelInfo']['targetAccuracy']}")
        print(f"  Architecture: {result['modelInfo']['architecture']}")
        print(f"\nFirst 3 Day Predictions:")
        for i, pred in enumerate(result['predictions'][:3], 1):
            print(f"    Day {i}: {pred['predictedBuy']:,} (confidence: {pred['confidence']:.3f})")

        if result['confidenceScore'] >= 0.95:
            print(f"\n✓ Target confidence of 95-98% ACHIEVED: {result['confidenceScore']:.1%}")
        else:
            print(f"\n✗ Target confidence of 95-98% NOT reached: {result['confidenceScore']:.1%}")

    except Exception as e:
        print(f"Error generating predictions: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 70)
    print("Running Backtesting Validation...")
    print("=" * 70)

    try:
        backtest_result = PredictionBacktester.walk_forward_validation(
            currency_code='usd',
            prediction_days=7,
            test_periods=3,
            use_full_history=True
        )

        if 'overall_metrics' in backtest_result:
            print(f"\nBacktesting Results:")
            print(f"  Overall Accuracy: {backtest_result['overall_metrics']['accuracy_percentage']:.2f}%")
            print(f"  Average Accuracy: {backtest_result['average_accuracy']:.2f}%")
            print(f"  MAPE: {backtest_result['overall_metrics']['mape']:.2f}%")
            print(f"  R-squared: {backtest_result['overall_metrics']['r_squared']:.4f}")
            print(f"  Directional Accuracy: {backtest_result['overall_metrics']['directional_accuracy']:.2f}%")

            if backtest_result.get('meets_95_target'):
                print(f"\n✓ 95% accuracy target ACHIEVED in backtesting")
            else:
                print(f"\n✗ 95% accuracy target not reached: {backtest_result['overall_metrics']['accuracy_percentage']:.2f}%")

    except Exception as e:
        print(f"Error running backtesting: {e}")

except ImportError as e:
    print(f"Import error: {e}")
    print("Please ensure all dependencies are installed in your virtual environment")
    print("Run: source .venv/bin/activate && pip install -r requirements.txt")

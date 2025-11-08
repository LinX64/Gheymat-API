#!/usr/bin/env python3
"""Test script for AI prediction endpoint"""

import requests
import json

def test_prediction_endpoint():
    """Test the AI prediction endpoint"""

    url = "http://localhost:5000/api/v1/predict"

    # Test USD prediction
    payload = {
        "currencyCode": "usd",
        "daysAhead": 14,
        "historicalDays": 30
    }

    print("Testing AI Prediction Endpoint...")
    print(f"Request: {json.dumps(payload, indent=2)}")

    try:
        response = requests.post(url, json=payload)

        print(f"\nStatus Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")

        if response.status_code == 200:
            data = response.json()
            print("\n✅ SUCCESS!")
            print(f"Currency: {data['currencyName']}")
            print(f"Current Buy: {data['currentPrice']['buy']:,} Rials")
            print(f"Current Sell: {data['currentPrice']['sell']:,} Rials")
            print(f"Trend: {data['trend']}")
            print(f"Confidence: {data['confidenceScore'] * 100:.1f}%")
            print(f"Predictions: {len(data['predictions'])} days")
            print(f"\nFirst prediction:")
            first_pred = data['predictions'][0]
            print(f"  Date: {first_pred['date']}")
            print(f"  Buy: {first_pred['predictedBuy']:,} Rials")
            print(f"  Sell: {first_pred['predictedSell']:,} Rials")
            print(f"  Confidence: {first_pred['confidence'] * 100:.1f}%")
        else:
            print(f"\n❌ FAILED: {response.json()}")

    except requests.exceptions.ConnectionError:
        print("\n❌ Connection Error - Is the server running?")
        print("Start the server with: python3 api_server.py")
    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    test_prediction_endpoint()

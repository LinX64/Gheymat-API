# AI Predictions - Quick Start Guide

## Using Static Predictions (Recommended)

### Fetch Predictions via HTTP

```bash
# Get prediction index
curl https://linx64.github.io/CurrencyCapPortal/predictions/index.json

# Get short-term predictions (7 days)
curl https://linx64.github.io/CurrencyCapPortal/predictions/short.json

# Get medium-term predictions (14 days)
curl https://linx64.github.io/CurrencyCapPortal/predictions/medium.json

# Get long-term predictions (30 days)
curl https://linx64.github.io/CurrencyCapPortal/predictions/long.json
```

### JavaScript Example

```javascript
// Fetch and display USD predictions
async function getUSDPredictions() {
  const response = await fetch(
    'https://linx64.github.io/CurrencyCapPortal/predictions/short.json'
  );
  const data = await response.json();

  // Find USD predictions
  const usdPrediction = data.predictions.find(
    p => p.currencyCode === 'usd'
  );

  console.log('Currency:', usdPrediction.prediction.currencyName);
  console.log('Current Buy Price:', usdPrediction.prediction.currentPrice.buy);
  console.log('Trend:', usdPrediction.prediction.trend);
  console.log('Confidence:', (usdPrediction.prediction.confidenceScore * 100).toFixed(1) + '%');

  // Show first prediction
  const firstDay = usdPrediction.prediction.predictions[0];
  console.log('\nTomorrow:');
  console.log('  Date:', firstDay.date);
  console.log('  Predicted Buy:', firstDay.predictedBuy);
  console.log('  Range:', firstDay.lowerBound, '-', firstDay.upperBound);
}

getUSDPredictions();
```

### Python Example

```python
import requests

# Fetch short-term predictions
response = requests.get(
    'https://linx64.github.io/CurrencyCapPortal/predictions/short.json'
)
data = response.json()

# Find USD predictions
usd = next(p for p in data['predictions'] if p['currencyCode'] == 'usd')
prediction = usd['prediction']

print(f"Currency: {prediction['currencyName']}")
print(f"Current Buy: {prediction['currentPrice']['buy']:,} Rials")
print(f"Trend: {prediction['trend']}")
print(f"Confidence: {prediction['confidenceScore']*100:.1f}%")

# Show first day prediction
first_day = prediction['predictions'][0]
print(f"\n{first_day['date']}:")
print(f"  Predicted Buy: {first_day['predictedBuy']:,} Rials")
print(f"  Range: {first_day['lowerBound']:,} - {first_day['upperBound']:,}")
```

---

## Running Dynamic API (Development)

### Start Server

```bash
# Install dependencies
make install
# or
pip install -r requirements.txt

# Start server
python3 api_server.py
```

Server runs at: `http://localhost:5000`

### Test Endpoint

```bash
# Using curl
curl -X POST http://localhost:5000/api/v1/predict \
  -H "Content-Type: application/json" \
  -d '{"currencyCode": "usd", "daysAhead": 14}'

# Using test script
python3 test_prediction.py

# Health check
curl http://localhost:5000/health
```

---

## Generating Predictions Locally

```bash
# Generate all prediction files
make predictions

# View output
ls -lh api/predictions/

# Check a specific prediction
cat api/predictions/index.json | python3 -m json.tool
```

Generated files:
- `api/predictions/short.json` - 7 day predictions
- `api/predictions/medium.json` - 14 day predictions
- `api/predictions/long.json` - 30 day predictions
- `api/predictions/index.json` - Metadata

---

## Testing

```bash
# Run all tests
make test

# Test predictions only
make test-predictions

# Verbose output
pytest tests/test_api_server.py -v
```

---

## GitHub Actions (Automatic)

Predictions are automatically:
- **Generated every hour** via GitHub Actions
- **Committed to repository** (master branch)
- **Deployed to GitHub Pages** at `https://linx64.github.io/CurrencyCapPortal/`

Manual trigger:
```bash
# Via GitHub UI: Actions → Generate AI Predictions → Run workflow
```

---

## Understanding the Response

```json
{
  "currencyCode": "usd",
  "currencyName": "US Dollar",
  "trend": "BULLISH",          // BULLISH, BEARISH, NEUTRAL, or VOLATILE
  "confidenceScore": 0.85,     // 0.5 to 0.95 (50% to 95%)
  "predictions": [
    {
      "date": "2025-11-09",
      "predictedBuy": 107800,   // Predicted buy price
      "predictedSell": 107895,  // Predicted sell price
      "confidence": 0.85,       // Confidence for this day
      "lowerBound": 107000,     // Minimum expected price
      "upperBound": 108600      // Maximum expected price
    }
  ]
}
```

**Trend Meanings:**
- `BULLISH` - Prices expected to rise
- `BEARISH` - Prices expected to fall
- `NEUTRAL` - Stable, no significant change
- `VOLATILE` - High uncertainty, large price swings

---

## Available Currencies

42 currencies supported:
- **Fiat:** USD, EUR, GBP, CHF, CAD, AUD, JPY, CNY, INR, TRY, RUB, and more
- **Crypto:** BTC, ETH, XRP, BCH, LTC, BNB, USDT
- **Gold:** AZADI, EMAMI, HALF, QUARTER, GERAMI, GRAM, MITHQAL

---

## Need Help?

- Full documentation: `PREDICTIONS.md`
- Run tests: `make test-predictions`
- Check logs: GitHub Actions → Generate AI Predictions workflow
- Report issues: https://github.com/LinX64/CurrencyCapPortal/issues

---

**Auto-Update Schedule:** Every hour via GitHub Actions
**Base URL:** https://linx64.github.io/CurrencyCapPortal/
**Model Version:** v1.0-exponential-smoothing

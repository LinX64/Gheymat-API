# AI Predictions Feature Documentation

## Overview

The AI Predictions feature provides machine learning-based currency price forecasts using exponential smoothing, trend analysis, and momentum indicators. Predictions are available as both a **dynamic API** and **static JSON files**.

---

## Static Predictions (Recommended for Production)

Pre-generated predictions updated every hour via GitHub Actions and served via GitHub Pages.

### Available Endpoints

Base URL: `https://linx64.github.io/CurrencyCapPortal/predictions/`

#### Index Endpoint
```
GET /predictions/index.json
```

Returns metadata about available prediction configurations.

**Response:**
```json
{
  "generatedAt": "2025-11-08T23:33:46Z",
  "availableConfigurations": [
    {
      "name": "short",
      "daysAhead": 7,
      "historicalDays": 30,
      "endpoint": "predictions/short.json"
    },
    {
      "name": "medium",
      "daysAhead": 14,
      "historicalDays": 60,
      "endpoint": "predictions/medium.json"
    },
    {
      "name": "long",
      "daysAhead": 30,
      "historicalDays": 90,
      "endpoint": "predictions/long.json"
    }
  ],
  "stats": {
    "totalCurrencies": 43,
    "successfulPredictions": 126,
    "failedPredictions": 3
  }
}
```

#### Prediction Files

| Configuration | Days Ahead | Historical Data | Endpoint |
|--------------|------------|-----------------|----------|
| Short-term   | 7 days     | 30 days        | `/predictions/short.json` |
| Medium-term  | 14 days    | 60 days        | `/predictions/medium.json` |
| Long-term    | 30 days    | 90 days        | `/predictions/long.json` |

### Usage Example

```javascript
// Fetch short-term predictions
fetch('https://linx64.github.io/CurrencyCapPortal/predictions/short.json')
  .then(response => response.json())
  .then(data => {
    const usdPrediction = data.predictions.find(p => p.currencyCode === 'usd');
    console.log('USD Predictions:', usdPrediction.prediction);
  });
```

### Response Format

```json
{
  "generatedAt": "2025-11-08T23:33:46Z",
  "daysAhead": 7,
  "historicalDays": 30,
  "totalCurrencies": 42,
  "predictions": [
    {
      "currencyCode": "usd",
      "prediction": {
        "currencyCode": "usd",
        "currencyName": "US Dollar",
        "currentPrice": {
          "buy": 107700,
          "sell": 107795,
          "timestamp": "2025-11-08T23:33:46Z"
        },
        "predictions": [
          {
            "date": "2025-11-09",
            "timestamp": 1731110400000,
            "predictedBuy": 107800,
            "predictedSell": 107895,
            "confidence": 0.85,
            "lowerBound": 107000,
            "upperBound": 108600
          }
          // ... more daily predictions
        ],
        "confidenceScore": 0.85,
        "trend": "BULLISH",
        "generatedAt": "2025-11-08T23:33:46Z",
        "modelVersion": "v1.0-exponential-smoothing"
      }
    }
    // ... more currencies
  ]
}
```

---

## Dynamic API (For Development)

Run a Flask API server locally for real-time predictions.

### Starting the Server

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
python3 api_server.py
```

Server runs on `http://localhost:5000`

### Endpoints

#### Prediction Endpoint
```
POST /api/v1/predict
Content-Type: application/json
```

**Request Body:**
```json
{
  "currencyCode": "usd",
  "daysAhead": 14,
  "historicalDays": 30
}
```

**Parameters:**
- `currencyCode` (required): Currency code (e.g., "usd", "eur", "btc")
- `daysAhead` (optional): Number of days to predict (1-90, default: 14)
- `historicalDays` (optional): Days of historical data to analyze (default: 30)

**Response:**
```json
{
  "currencyCode": "usd",
  "currencyName": "US Dollar",
  "currentPrice": {
    "buy": 107700,
    "sell": 107795,
    "timestamp": "2025-11-08T23:33:46Z"
  },
  "predictions": [
    {
      "date": "2025-11-09",
      "timestamp": 1731110400000,
      "predictedBuy": 107800,
      "predictedSell": 107895,
      "confidence": 0.85,
      "lowerBound": 107000,
      "upperBound": 108600
    }
  ],
  "confidenceScore": 0.85,
  "trend": "BULLISH",
  "generatedAt": "2025-11-08T23:33:46Z",
  "modelVersion": "v1.0-exponential-smoothing"
}
```

**Trend Values:**
- `BULLISH`: Upward trend (combined trend > 0.01)
- `BEARISH`: Downward trend (combined trend < -0.01)
- `NEUTRAL`: Stable prices
- `VOLATILE`: High volatility (> 15%)

#### Health Check
```
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-11-08T23:33:46Z"
}
```

### Testing the API

```bash
# Using curl
curl -X POST http://localhost:5000/api/v1/predict \
  -H "Content-Type: application/json" \
  -d '{
    "currencyCode": "usd",
    "daysAhead": 14,
    "historicalDays": 30
  }'

# Using the test script
python3 test_prediction.py
```

---

## Prediction Algorithm

The AI prediction engine uses multiple indicators:

### 1. Trend Analysis (Linear Regression)
- Calculates price movement direction
- Formula: `slope = (n * Σ(xy) - Σx * Σy) / (n * Σ(x²) - (Σx)²)`

### 2. Volatility Measurement
- Standard deviation of price changes
- Higher volatility = lower confidence
- Formula: `volatility = σ / mean`

### 3. Momentum Indicator
- Recent price changes vs historical average
- Formula: `momentum = (recent_avg - older_avg) / older_avg`

### 4. Exponential Smoothing
- Smooths out short-term fluctuations
- Alpha parameter: 0.3 (30% weight to new data)
- Formula: `predicted = α * trend_prediction + (1-α) * previous`

### 5. Confidence Scoring
Confidence is calculated based on:
- **Data availability**: More historical data = higher confidence
- **Volatility**: Lower volatility = higher confidence
- **Time decay**: Near-term predictions = higher confidence
- Range: 0.5 (50%) to 0.95 (95%)

---

## Development

### Generate Predictions Locally

```bash
# Using make
make predictions

# Or directly
python3 generate_predictions.py
```

This creates three prediction files:
- `api/predictions/short.json` (~97 KB)
- `api/predictions/medium.json` (~173 KB)
- `api/predictions/long.json` (~347 KB)
- `api/predictions/index.json` (~1 KB)

### Run Tests

```bash
# Test prediction engine
make test-predictions

# Or with pytest
pytest tests/test_api_server.py -v
```

**Test Coverage:**
- Trend calculation (upward, downward, flat)
- Volatility measurement
- Momentum analysis
- Historical data loading
- Prediction generation
- API endpoint validation
- Error handling

### GitHub Actions

Two workflows automatically maintain predictions:

#### 1. Generate Predictions Workflow
**File:** `.github/workflows/generate-predictions.yml`

**Triggers:**
- Every hour (cron schedule)
- Manual trigger (workflow_dispatch)
- Push to master with relevant file changes

**Actions:**
- Generates predictions for all currencies
- Commits files to repository
- Deploys to GitHub Pages

#### 2. Test Workflow
**File:** `.github/workflows/test.yml`

**Triggers:**
- Pull requests to master

**Actions:**
- Runs all unit tests including prediction tests

---

## Error Handling

### API Errors

| Status Code | Error | Description |
|-------------|-------|-------------|
| 400 | Bad Request | Missing or invalid parameters |
| 404 | Not Found | Currency not found |
| 500 | Internal Server Error | Unexpected error |

**Error Response Format:**
```json
{
  "error": "Currency xyz not found"
}
```

### Static File Errors

If a currency fails prediction generation:
- It's logged in the generation output
- Other currencies continue processing
- Stats include failed count

---

## Deployment Options

### Option 1: Static Files (Current Setup)
- **Platform:** GitHub Pages
- **Cost:** Free
- **Update Frequency:** Every hour via GitHub Actions
- **URL:** `https://linx64.github.io/CurrencyCapPortal/predictions/`
- **Best for:** Production use, high traffic

### Option 2: Dynamic API (Development)
- **Platform:** Local/Render/Railway
- **Cost:** Free tier available
- **Update Frequency:** Real-time
- **Best for:** Custom prediction parameters

### Option 3: Hybrid Approach (Recommended)
- Serve static predictions via GitHub Pages for common use cases
- Deploy dynamic API for custom/on-demand predictions
- Best balance of cost, performance, and flexibility

---

## Limitations

1. **Historical Data:** Predictions quality depends on available historical data
2. **Market Events:** Cannot predict sudden market shocks or news events
3. **Accuracy:** Past performance does not guarantee future results
4. **Confidence Decay:** Long-term predictions have lower confidence
5. **Update Frequency:** Static predictions update hourly, not real-time

---

## Support

- **Tests:** 31 unit tests covering all prediction functionality
- **Issues:** Report bugs at [GitHub Issues](https://github.com/LinX64/CurrencyCapPortal/issues)
- **Documentation:** This file and inline code comments

---

## License

See repository LICENSE file.

---

**Last Updated:** 2025-11-08
**Model Version:** v1.0-exponential-smoothing

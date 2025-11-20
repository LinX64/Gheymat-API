# API Testing Guide

This guide explains how to test the CurrencyCap Portal APIs locally and on Google Cloud Run.

## Prerequisites

- Python 3.10+
- Docker (for containerized testing)
- curl or Postman (for API testing)
- Google Cloud SDK (for Cloud Run deployment)

## Testing Locally

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the Flask Server

```bash
python api_server.py
```

The server will start on `http://localhost:8080` (or port specified by PORT env var).

### 3. Test Health Endpoint

```bash
curl http://localhost:8080/health
```

**Expected Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-11-20T21:39:04.123456"
}
```

### 4. Test Prediction Endpoint

```bash
curl -X POST http://localhost:8080/api/v1/predict \
  -H "Content-Type: application/json" \
  -d '{
    "currencyCode": "usd",
    "daysAhead": 14,
    "historicalDays": 30
  }'
```

**Expected Response:**
```json
{
  "currencyCode": "usd",
  "currencyName": "US Dollar",
  "currentPrice": {
    "buy": 70500,
    "sell": 70600,
    "timestamp": "2025-11-20T21:39:04.123456Z"
  },
  "predictions": [
    {
      "date": "2025-11-21",
      "timestamp": 1732147200000,
      "predictedBuy": 70520,
      "predictedSell": 70620,
      "confidence": 0.850,
      "lowerBound": 69500,
      "upperBound": 71500
    }
    // ... more predictions
  ],
  "confidenceScore": 0.825,
  "trend": "BULLISH",
  "generatedAt": "2025-11-20T21:39:04.123456Z",
  "modelVersion": "v1.0-exponential-smoothing"
}
```

### 5. Test Different Currencies

Available currencies (check `api/latest.json` for full list):
- `usd` - US Dollar
- `eur` - Euro
- `gbp` - British Pound
- `try` - Turkish Lira
- `aed` - UAE Dirham
- And more...

```bash
curl -X POST http://localhost:8080/api/v1/predict \
  -H "Content-Type: application/json" \
  -d '{
    "currencyCode": "eur",
    "daysAhead": 7,
    "historicalDays": 30
  }'
```

### 6. Test Error Handling

**Missing Currency Code:**
```bash
curl -X POST http://localhost:8080/api/v1/predict \
  -H "Content-Type: application/json" \
  -d '{
    "daysAhead": 14
  }'
```

**Expected:** 400 Bad Request

**Invalid Days Ahead:**
```bash
curl -X POST http://localhost:8080/api/v1/predict \
  -H "Content-Type: application/json" \
  -d '{
    "currencyCode": "usd",
    "daysAhead": 100
  }'
```

**Expected:** 400 Bad Request (max 90 days)

**Unknown Currency:**
```bash
curl -X POST http://localhost:8080/api/v1/predict \
  -H "Content-Type: application/json" \
  -d '{
    "currencyCode": "xyz",
    "daysAhead": 14
  }'
```

**Expected:** 404 Not Found

## Testing with Docker

### 1. Build Docker Image

```bash
docker build -t currencycap-portal .
```

### 2. Run Container

```bash
docker run -p 8080:8080 currencycap-portal
```

### 3. Test Endpoints

Use the same curl commands as above, targeting `http://localhost:8080`.

### 4. Run with Environment Variables

```bash
docker run -p 9000:9000 -e PORT=9000 currencycap-portal
```

Then test on `http://localhost:9000`.

## Testing on Google Cloud Run

### 1. Build and Deploy

```bash
# Set your project ID
export PROJECT_ID=your-gcp-project-id

# Build using Cloud Build
gcloud builds submit --config cloudbuild.yaml

# Or manually:
docker build -t gcr.io/$PROJECT_ID/currencycap-portal .
docker push gcr.io/$PROJECT_ID/currencycap-portal

gcloud run deploy currencycap-portal \
  --image gcr.io/$PROJECT_ID/currencycap-portal \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --max-instances 10
```

### 2. Get Service URL

```bash
gcloud run services describe currencycap-portal \
  --platform managed \
  --region us-central1 \
  --format 'value(status.url)'
```

Example output: `https://currencycap-portal-xxxxx-uc.a.run.app`

### 3. Test Health Check

```bash
curl https://currencycap-portal-xxxxx-uc.a.run.app/health
```

### 4. Test Predictions

```bash
curl -X POST https://currencycap-portal-xxxxx-uc.a.run.app/api/v1/predict \
  -H "Content-Type: application/json" \
  -d '{
    "currencyCode": "usd",
    "daysAhead": 14,
    "historicalDays": 30
  }'
```

### 5. Monitor Logs

```bash
gcloud run services logs read currencycap-portal \
  --platform managed \
  --region us-central1 \
  --limit 50
```

### 6. Check Metrics

View in Google Cloud Console:
- https://console.cloud.google.com/run
- Select your service
- Click "METRICS" tab

## Performance Testing

### Load Testing with Apache Bench

```bash
# Install Apache Bench
sudo apt-get install apache2-utils

# Test health endpoint (100 requests, 10 concurrent)
ab -n 100 -c 10 http://localhost:8080/health

# Test prediction endpoint
ab -n 50 -c 5 -p request.json -T application/json http://localhost:8080/api/v1/predict
```

Create `request.json`:
```json
{
  "currencyCode": "usd",
  "daysAhead": 14,
  "historicalDays": 30
}
```

## Automated Testing

### Run Unit Tests

```bash
pytest tests/ -v
```

### Test Coverage

```bash
pytest --cov=api_server tests/
```

## Troubleshooting

### Port Already in Use

```bash
# Find process using port 8080
lsof -i :8080

# Kill process
kill -9 <PID>
```

### Missing Data Files

Ensure these files exist:
- `api/latest.json`
- `api/history/1d.json`
- `api/history/1w.json`
- `api/history/1m.json`
- `api/history/1y.json`
- `api/history/5y.json`

Run the data update script:
```bash
python update_apis.py
```

### Docker Build Issues

```bash
# Clean build cache
docker system prune -a

# Rebuild without cache
docker build --no-cache -t currencycap-portal .
```

### Cloud Run Deployment Issues

**Authentication Error:**
```bash
gcloud auth login
gcloud config set project your-project-id
```

**Permission Denied:**
```bash
gcloud projects add-iam-policy-binding your-project-id \
  --member="user:your-email@example.com" \
  --role="roles/run.admin"
```

**Container Fails to Start:**
- Check logs: `gcloud run services logs read currencycap-portal`
- Verify PORT environment variable is used correctly
- Ensure all data files are included in the container

## API Request Examples (Postman/Insomnia)

### Health Check

```
GET http://localhost:8080/health
```

### Short-term Prediction (7 days)

```
POST http://localhost:8080/api/v1/predict
Content-Type: application/json

{
  "currencyCode": "usd",
  "daysAhead": 7,
  "historicalDays": 30
}
```

### Medium-term Prediction (14 days)

```
POST http://localhost:8080/api/v1/predict
Content-Type: application/json

{
  "currencyCode": "eur",
  "daysAhead": 14,
  "historicalDays": 60
}
```

### Long-term Prediction (30 days)

```
POST http://localhost:8080/api/v1/predict
Content-Type: application/json

{
  "currencyCode": "gbp",
  "daysAhead": 30,
  "historicalDays": 90
}
```

## Notes

- The API uses **statistical methods** (exponential smoothing, trend analysis) for predictions
- ML models in `api/predictions/models/` are **not currently loaded** (future enhancement)
- Predictions are generated on-demand with configurable timeframes
- Static predictions are pre-generated via GitHub Actions in `api/predictions/`
- CORS is enabled for cross-origin requests
- All timestamps are in ISO 8601 format with UTC timezone

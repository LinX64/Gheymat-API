# Google Cloud Run Deployment Guide

Complete guide for deploying CurrencyCap Portal to Google Cloud Run.

## Prerequisites

1. **Google Cloud Account** with billing enabled
2. **gcloud CLI** installed ([Installation Guide](https://cloud.google.com/sdk/docs/install))
3. **Docker** installed (for local testing)
4. **Git** (for version control)

## Quick Start

### Option 1: Automated Setup (Recommended)

Run the setup script to configure everything automatically:

```bash
# 1. Authenticate with Google Cloud
gcloud auth login

# 2. Set your project ID
gcloud config set project YOUR_PROJECT_ID

# 3. Run the setup script
./setup-gcloud.sh
```

The script will:
- ✅ Enable required APIs (Cloud Build, Cloud Run, Artifact Registry)
- ✅ Create Artifact Registry repository
- ✅ Configure Docker authentication
- ✅ Set up Cloud Build permissions

### Option 2: Manual Setup

If you prefer manual setup or the script fails, follow these steps:

#### Step 1: Enable Required APIs

```bash
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable artifactregistry.googleapis.com
```

#### Step 2: Create Artifact Registry Repository

```bash
gcloud artifacts repositories create currencycap-repo \
  --repository-format=docker \
  --location=us-central1 \
  --description="CurrencyCap Portal Docker images"
```

#### Step 3: Configure Docker Authentication

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
```

#### Step 4: Grant Cloud Build Permissions

```bash
PROJECT_ID=$(gcloud config get-value project)

# Grant Cloud Run Admin role
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_ID}@cloudbuild.gserviceaccount.com" \
  --role="roles/run.admin"

# Grant Service Account User role
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_ID}@cloudbuild.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

## Deployment

### Deploy via Cloud Build (Recommended)

This uses the `cloudbuild.yaml` configuration:

```bash
gcloud builds submit --config cloudbuild.yaml
```

This will:
1. Build the Docker image
2. Push to Artifact Registry with version tags
3. Deploy to Cloud Run automatically

### Deploy Manually

#### Build and Push Image

```bash
PROJECT_ID=$(gcloud config get-value project)

# Build image
docker build -t us-central1-docker.pkg.dev/$PROJECT_ID/currencycap-repo/currencycap-portal:latest .

# Push to Artifact Registry
docker push us-central1-docker.pkg.dev/$PROJECT_ID/currencycap-repo/currencycap-portal:latest
```

#### Deploy to Cloud Run

```bash
gcloud run deploy currencycap-portal \
  --image=us-central1-docker.pkg.dev/$PROJECT_ID/currencycap-repo/currencycap-portal:latest \
  --platform=managed \
  --region=us-central1 \
  --allow-unauthenticated \
  --memory=1Gi \
  --cpu=1 \
  --max-instances=10 \
  --port=8080
```

## Post-Deployment

### Get Service URL

```bash
gcloud run services describe currencycap-portal \
  --platform=managed \
  --region=us-central1 \
  --format='value(status.url)'
```

Example output: `https://currencycap-portal-abc123-uc.a.run.app`

### Test the Deployment

```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe currencycap-portal \
  --platform=managed \
  --region=us-central1 \
  --format='value(status.url)')

# Test health endpoint
curl $SERVICE_URL/health

# Test prediction API
curl -X POST $SERVICE_URL/api/v1/predict \
  -H "Content-Type: application/json" \
  -d '{
    "currencyCode": "usd",
    "daysAhead": 14,
    "historicalDays": 30
  }'
```

## Monitoring and Logs

### View Logs

```bash
# Real-time logs
gcloud run services logs tail currencycap-portal --region=us-central1

# Last 50 entries
gcloud run services logs read currencycap-portal \
  --region=us-central1 \
  --limit=50
```

### View Metrics

Access metrics in Google Cloud Console:
1. Go to https://console.cloud.google.com/run
2. Select `currencycap-portal` service
3. Click on **METRICS** tab

Key metrics to monitor:
- Request count
- Request latency
- Container CPU utilization
- Container memory utilization
- Billable container time

### View Build History

```bash
gcloud builds list --limit=10
```

## Configuration

### Environment Variables

Add environment variables to Cloud Run:

```bash
gcloud run services update currencycap-portal \
  --region=us-central1 \
  --update-env-vars="API_KEY=your-api-key,DEBUG=false"
```

Or via cloudbuild.yaml:

```yaml
- name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
  entrypoint: gcloud
  args:
    - 'run'
    - 'deploy'
    - 'currencycap-portal'
    - '--set-env-vars=API_KEY=your-api-key'
```

### Update Resource Limits

```bash
# Update memory
gcloud run services update currencycap-portal \
  --region=us-central1 \
  --memory=2Gi

# Update CPU
gcloud run services update currencycap-portal \
  --region=us-central1 \
  --cpu=2

# Update max instances
gcloud run services update currencycap-portal \
  --region=us-central1 \
  --max-instances=20
```

### Add Custom Domain

```bash
# Map custom domain
gcloud run domain-mappings create \
  --service=currencycap-portal \
  --domain=api.yourdomain.com \
  --region=us-central1
```

Follow DNS configuration instructions provided by the command.

## CI/CD with GitHub Actions

### Setup GitHub Actions Deployment

1. **Create Service Account**:
```bash
PROJECT_ID=$(gcloud config get-value project)

gcloud iam service-accounts create github-actions \
  --display-name="GitHub Actions"

# Grant necessary roles
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/storage.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"
```

2. **Create Service Account Key**:
```bash
gcloud iam service-accounts keys create key.json \
  --iam-account=github-actions@${PROJECT_ID}.iam.gserviceaccount.com
```

3. **Add GitHub Secret**:
- Go to your GitHub repository
- Settings → Secrets and variables → Actions
- Add secret: `GCP_SA_KEY` with contents of `key.json`

4. **Create GitHub Action** (`.github/workflows/deploy-cloud-run.yml`):
```yaml
name: Deploy to Cloud Run

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v3

      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v1
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}

      - name: Set up Cloud SDK
        uses: google-github-actions/setup-gcloud@v1

      - name: Build and Deploy
        run: |
          gcloud builds submit --config cloudbuild.yaml
```

## Troubleshooting

### Error: "gcr.io repo does not exist"

**Solution**: Use Artifact Registry instead (already configured in `cloudbuild.yaml`):
- Run `./setup-gcloud.sh` to create the repository
- Or manually: `gcloud artifacts repositories create currencycap-repo --repository-format=docker --location=us-central1`

### Error: "Permission denied"

**Solution**: Grant Cloud Build the necessary permissions:
```bash
PROJECT_ID=$(gcloud config get-value project)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_ID}@cloudbuild.gserviceaccount.com" \
  --role="roles/run.admin"
```

### Error: "Service could not be started"

**Check logs**:
```bash
gcloud run services logs read currencycap-portal --region=us-central1 --limit=50
```

**Common causes**:
- Missing `api/latest.json` or history files (run `python update_apis.py` before building)
- Port configuration incorrect (ensure `PORT` env var is used)
- Application crashes on startup

### Error: "Container failed to start"

**Verify locally**:
```bash
docker build -t test-image .
docker run -p 8080:8080 test-image
curl http://localhost:8080/health
```

### Build Timeout

If builds are timing out:
```yaml
# Add to cloudbuild.yaml options
options:
  machineType: 'E2_HIGHCPU_8'
  timeout: '1200s'  # 20 minutes
```

## Cost Optimization

### Free Tier

Cloud Run free tier includes:
- 2 million requests per month
- 360,000 GB-seconds of memory
- 180,000 vCPU-seconds

### Reduce Costs

1. **Set minimum instances to 0**:
```bash
gcloud run services update currencycap-portal \
  --region=us-central1 \
  --min-instances=0
```

2. **Reduce memory allocation**:
```bash
gcloud run services update currencycap-portal \
  --region=us-central1 \
  --memory=512Mi
```

3. **Set request timeout**:
```bash
gcloud run services update currencycap-portal \
  --region=us-central1 \
  --timeout=60
```

## Security Best Practices

### 1. Use Secret Manager

Store sensitive data in Secret Manager:
```bash
# Create secret
echo -n "your-api-key" | gcloud secrets create api-key --data-file=-

# Grant Cloud Run access
gcloud secrets add-iam-policy-binding api-key \
  --member="serviceAccount:${PROJECT_ID}@appspot.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# Update service to use secret
gcloud run services update currencycap-portal \
  --region=us-central1 \
  --update-secrets=API_KEY=api-key:latest
```

### 2. Enable Binary Authorization

```bash
gcloud container binauthz policy import policy.yaml
```

### 3. Use VPC Connector (for private resources)

```bash
gcloud compute networks vpc-access connectors create currencycap-connector \
  --region=us-central1 \
  --network=default \
  --range=10.8.0.0/28

gcloud run services update currencycap-portal \
  --region=us-central1 \
  --vpc-connector=currencycap-connector
```

### 4. Restrict Ingress

```bash
# Allow only internal traffic
gcloud run services update currencycap-portal \
  --region=us-central1 \
  --ingress=internal

# Allow internal and Cloud Load Balancing
gcloud run services update currencycap-portal \
  --region=us-central1 \
  --ingress=internal-and-cloud-load-balancing
```

## Rollback

### Rollback to Previous Revision

```bash
# List revisions
gcloud run revisions list --service=currencycap-portal --region=us-central1

# Rollback to specific revision
gcloud run services update-traffic currencycap-portal \
  --region=us-central1 \
  --to-revisions=currencycap-portal-00001-abc=100
```

## Cleanup

### Delete Service

```bash
gcloud run services delete currencycap-portal --region=us-central1
```

### Delete Artifact Registry Repository

```bash
gcloud artifacts repositories delete currencycap-repo --location=us-central1
```

### Delete Docker Images

```bash
# List images
gcloud artifacts docker images list us-central1-docker.pkg.dev/PROJECT_ID/currencycap-repo/currencycap-portal

# Delete specific image
gcloud artifacts docker images delete \
  us-central1-docker.pkg.dev/PROJECT_ID/currencycap-repo/currencycap-portal:TAG
```

## Additional Resources

- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Cloud Build Documentation](https://cloud.google.com/build/docs)
- [Artifact Registry Documentation](https://cloud.google.com/artifact-registry/docs)
- [Best Practices for Cloud Run](https://cloud.google.com/run/docs/best-practices)
- [Pricing Calculator](https://cloud.google.com/products/calculator)

## Support

For issues:
1. Check logs: `gcloud run services logs tail currencycap-portal --region=us-central1`
2. Review documentation: See `API_TESTING.md` for API testing
3. Check Cloud Run status: https://status.cloud.google.com/
4. Contact support: https://cloud.google.com/support

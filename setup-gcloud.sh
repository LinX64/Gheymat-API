#!/bin/bash

# Google Cloud Setup Script for CurrencyCap Portal
# This script enables required APIs and creates necessary resources

set -e  # Exit on error

echo "==================================="
echo "CurrencyCap Portal - GCP Setup"
echo "==================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}Error: gcloud CLI is not installed${NC}"
    echo "Install it from: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Get current project ID
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)

if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}Error: No GCP project set${NC}"
    echo "Run: gcloud config set project YOUR_PROJECT_ID"
    exit 1
fi

echo -e "${GREEN}Using project: $PROJECT_ID${NC}"
echo ""

# Variables
REGION="us-central1"
REPO_NAME="currencycap-repo"
SERVICE_NAME="currencycap-portal"

echo "Configuration:"
echo "  Region: $REGION"
echo "  Repository: $REPO_NAME"
echo "  Service: $SERVICE_NAME"
echo ""

# Function to check if API is enabled
check_api() {
    local api=$1
    if gcloud services list --enabled --filter="name:$api" --format="value(name)" | grep -q "$api"; then
        echo -e "${GREEN}✓${NC} $api is enabled"
        return 0
    else
        echo -e "${YELLOW}✗${NC} $api is not enabled"
        return 1
    fi
}

# Function to enable API
enable_api() {
    local api=$1
    echo -e "${YELLOW}Enabling $api...${NC}"
    gcloud services enable "$api" --project="$PROJECT_ID"
    echo -e "${GREEN}✓${NC} $api enabled"
}

echo "Step 1: Checking and enabling required APIs..."
echo "-----------------------------------------------"

APIS=(
    "cloudbuild.googleapis.com"
    "run.googleapis.com"
    "artifactregistry.googleapis.com"
    "containerregistry.googleapis.com"
)

for api in "${APIS[@]}"; do
    if ! check_api "$api"; then
        enable_api "$api"
    fi
done

echo ""
echo "Step 2: Creating Artifact Registry repository..."
echo "-------------------------------------------------"

# Check if repository exists
if gcloud artifacts repositories describe "$REPO_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" &>/dev/null; then
    echo -e "${GREEN}✓${NC} Repository '$REPO_NAME' already exists"
else
    echo -e "${YELLOW}Creating repository '$REPO_NAME'...${NC}"
    gcloud artifacts repositories create "$REPO_NAME" \
        --repository-format=docker \
        --location="$REGION" \
        --description="CurrencyCap Portal Docker images" \
        --project="$PROJECT_ID"
    echo -e "${GREEN}✓${NC} Repository created successfully"
fi

echo ""
echo "Step 3: Configuring Docker authentication..."
echo "---------------------------------------------"

gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
echo -e "${GREEN}✓${NC} Docker authentication configured"

echo ""
echo "Step 4: Setting up Cloud Build permissions..."
echo "----------------------------------------------"

# Get Cloud Build service account
BUILD_SA="${PROJECT_ID}@cloudbuild.gserviceaccount.com"

# Grant Cloud Run Admin role
echo "Granting Cloud Run Admin role to Cloud Build..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$BUILD_SA" \
    --role="roles/run.admin" \
    --condition=None \
    --quiet || true

# Grant Service Account User role
echo "Granting Service Account User role to Cloud Build..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$BUILD_SA" \
    --role="roles/iam.serviceAccountUser" \
    --condition=None \
    --quiet || true

echo -e "${GREEN}✓${NC} Cloud Build permissions configured"

echo ""
echo "==================================="
echo -e "${GREEN}Setup Complete!${NC}"
echo "==================================="
echo ""
echo "Next steps:"
echo "  1. Deploy using: gcloud builds submit --config cloudbuild.yaml"
echo "  2. Or trigger from GitHub (if connected)"
echo ""
echo "Your service will be available at:"
echo "  https://$SERVICE_NAME-xxxxx-uc.a.run.app"
echo ""
echo "To view your Artifact Registry:"
echo "  gcloud artifacts repositories list --location=$REGION"
echo ""
echo "To view Cloud Run services:"
echo "  gcloud run services list --region=$REGION"
echo ""

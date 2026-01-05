# RAWL 9001 POC - PR Regression Review

A Cloud Function that fetches Pull Requests from Azure DevOps, sends them to Gemini (Vertex AI) for regression-focused review of AEM frontend components, and automatically comments or rejects PRs based on severity.

## Features

- Fetches PR metadata and full file contents from Azure DevOps
- Sends both "before" and "after" versions to Gemini for comparison
- Generates a regression-focused review targeting AEM/HTL/JS/CSS
- Stores reviews in Cloud Storage with date partitioning (`yyyy/mm/dd`)
- **Auto-comments** on PRs with blocking or warning findings
- **Auto-rejects** PRs with blocking severity issues

## Severity Actions

| Severity | PR Comment | PR Rejection | Storage |
|----------|------------|--------------|---------|
| blocking | ✅ | ✅ | ✅ |
| warning | ✅ | ❌ | ✅ |
| info | ❌ | ❌ | ✅ |

## Build & Deploy

### Prerequisites

- GCP project created
- `gcloud` CLI installed
- Azure DevOps PAT with required permissions (see below)

### Step 1: Authenticate with GCP

```bash
# Login to GCP
gcloud auth login

# Set your project
gcloud config set project YOUR_PROJECT_ID

# Verify
gcloud config get-value project
```

### Step 2: Enable Required APIs

```bash
gcloud services enable \
  cloudfunctions.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com
```

### Step 3: Create Secrets

```bash
# Create Azure DevOps PAT secret
echo -n "your-azure-pat" | gcloud secrets create azure-devops-pat --data-file=-

# Create API key for the function
echo -n "your-api-key" | gcloud secrets create pr-review-api-key --data-file=-

# or update
echo -n "your-new-api-key" | gcloud secrets versions add pr-review-api-key --data-file=-

# Grant Cloud Functions access to secrets
gcloud secrets add-iam-policy-binding azure-devops-pat \
  --member="serviceAccount:889854265330-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding pr-review-api-key \
  --member="serviceAccount:889854265330-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### Step 4: Create Storage Bucket

```bash
gcloud storage buckets create gs://YOUR_BUCKET_NAME --location=us-central1
```

### Step 5: Deploy Cloud Function

```bash
gcloud functions deploy pr-regression-review \
  --gen2 \
  --runtime=python312 \
  --region=us-central1 \
  --source=. \
  --entry-point=review_pr \
  --trigger-http \
  --allow-unauthenticated \
  --memory=512MB \
  --timeout=300s \
  --set-env-vars="GCS_BUCKET=rawl9001,AZURE_DEVOPS_ORG=batdigital,AZURE_DEVOPS_PROJECT=Consumer%20Platforms,AZURE_DEVOPS_REPO=AEM-Platform-Core,VERTEX_PROJECT=rawl-extractor,VERTEX_LOCATION=us-central1" \
  --set-secrets="AZURE_DEVOPS_PAT=azure-devops-pat:latest,API_KEY=pr-review-api-key:latest"
```

### Step 6: Verify Deployment

```bash
# Get the function URL
gcloud functions describe pr-regression-review --region=us-central1 --format="value(serviceConfig.uri)"

# Test the function
curl -X POST "$(gcloud functions describe pr-regression-review --region=us-central1 --format='value(serviceConfig.uri)')" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{"pr_id": 12345}'
```

### Redeploying After Changes

After modifying the cloud function code (e.g., `main.py`, `requirements.txt`), you can quickly redeploy using the deployment script:

#### Option 1: Using the Deployment Script (Recommended)

The `deploy.sh` script automates the deployment process with built-in validation:

```bash
./deploy.sh
```

The script will:
- ✅ Verify gcloud authentication and project configuration
- ✅ Check that required files exist (main.py, requirements.txt)
- ✅ Deploy the function with existing environment variables and secrets
- ✅ Display the function URL and useful commands

**Prerequisites:**
- gcloud CLI installed and authenticated (`gcloud auth login`)
- GCP project configured (`gcloud config set project YOUR_PROJECT_ID`)
- Initial setup completed (secrets, storage bucket, APIs enabled - see steps 1-4 above)

**Make the script executable (first time only):**
```bash
chmod +x deploy.sh
```

#### Option 2: Manual Deployment

If you prefer to deploy manually or need to override specific settings:

```bash
gcloud functions deploy pr-regression-review \
  --gen2 \
  --runtime=python312 \
  --region=us-central1 \
  --source=. \
  --entry-point=review_pr
```

> **Note:** Environment variables and secrets persist between deployments unless explicitly changed. The deployment script reuses all existing configuration automatically.

## Usage

### HTTP Request

```bash
curl -X POST https://REGION-PROJECT_ID.cloudfunctions.net/pr-regression-review \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{"pr_id": 12345}'
```

### Response

```json
{
  "pr_id": 12345,
  "title": "PR title here",
  "files_changed": 5,
  "max_severity": "blocking",
  "has_blocking": true,
  "has_warning": false,
  "action_taken": "rejected",
  "commented": true,
  "storage_path": "gs://bucket/reviews/2026/01/01/pr-12345-143022-review.md",
  "review_preview": "First 500 chars..."
}
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `API_KEY` | Yes | API key for authenticating requests |
| `GCS_BUCKET` | Yes | Cloud Storage bucket for reviews |
| `AZURE_DEVOPS_PAT` | Yes | Azure DevOps Personal Access Token |
| `AZURE_DEVOPS_ORG` | Yes | Azure DevOps organization name |
| `AZURE_DEVOPS_PROJECT` | Yes | Azure DevOps project name |
| `AZURE_DEVOPS_REPO` | Yes | Repository name or ID |
| `VERTEX_PROJECT` | Yes | GCP project ID for Vertex AI |
| `VERTEX_LOCATION` | No | GCP region (default: `us-central1`) |

## Azure DevOps PAT Permissions

Your PAT needs:
- **Code (Read)** - To fetch file contents
- **Pull Request Threads (Read & Write)** - To post comments
- **Pull Request (Read & Write)** - To fetch PR metadata and vote/reject

## Review Focus Areas

The Gemini prompt detects:

| Risk Type | Examples |
|-----------|----------|
| Dialog Elimination | Removed AEM dialogs, restructured author interfaces |
| Function Removal | Deleted public JS functions other components may call |
| Behavior Changes | Modified logic affecting existing features |
| API Stability | Changed data-attributes, CSS classes, JS interfaces |
| HTL Contract Changes | Modified Sling Model properties, template parameters |
| CSS Breaking Changes | Renamed/removed classes, changed specificity |

## Local Development

### Running Locally with Functions Framework

The Cloud Functions Framework allows you to run and debug your function locally before deploying.

#### 1. Install Dependencies

```bash
pip3 install -r requirements.txt
```

#### 2. Set Environment Variables

Option A: Use a `.env` file (recommended for development):

```bash
# Copy the example and fill in your values
cp env.example .env
# Edit .env with your actual credentials
```

Option B: Export directly in your shell:

```bash
export API_KEY="test-key"
export GCS_BUCKET="your-bucket"
export AZURE_DEVOPS_PAT="your-pat"
export AZURE_DEVOPS_ORG="your-org"
export AZURE_DEVOPS_PROJECT="your-project"
export AZURE_DEVOPS_REPO="your-repo"
export VERTEX_PROJECT="your-gcp-project"
export VERTEX_LOCATION="us-central1"
```

#### 3. Start the Local Server

```bash
# Run with Python module execution (most reliable)
python3 -m functions_framework --target=review_pr --debug --port=8080

# Or if functions-framework is in your PATH
source .env
functions-framework --target=review_pr --debug --port=8080
```

The server will start on `http://localhost:8080` with:
- ✅ Debug mode enabled (auto-reload on file changes)
- ✅ Detailed logging
- ✅ Flask debugger active

#### 4. Test the Function

```bash
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key" \
  -d '{"pr_id": 12345}'
```

### Debugging with Cursor/VS Code

A `.vscode/launch.json` configuration is included for debugging:

1. Open **Run and Debug** panel (⌘+Shift+D / Ctrl+Shift+D)
2. Select **"Debug Cloud Function (Local)"**
3. Press **F5** to start debugging
4. Set breakpoints in `main.py`
5. Send a request with curl
6. Debug interactively!

The debugger configuration automatically:
- Loads environment variables from `.env`
- Attaches to the local server
- Allows stepping through code and inspecting variables

### Tips

- **Auto-reload**: With `--debug`, the server restarts when you edit files
- **Logging**: Check the console for detailed request/response logs
- **Network access**: Use `http://0.0.0.0:8080` to test from other devices on your network
- **Stop server**: Press `Ctrl+C` in the terminal

## Pub/Sub Dead Letter Queue (DLQ) Configuration

For production deployments, configure a Dead Letter Queue to capture failed messages after retry attempts are exhausted. This prevents infinite retry loops and allows manual inspection of failures.

### Step 1: Create Dead Letter Topic and Subscription

```bash
# Create dead letter topic
gcloud pubsub topics create pr-review-dlq

# Create subscription to inspect failed messages
gcloud pubsub subscriptions create pr-review-dlq-sub \
  --topic=pr-review-dlq \
  --ack-deadline=60
```

### Step 2: Configure Main Subscription with DLQ

```bash
# Update your existing subscription to use the DLQ
gcloud pubsub subscriptions update pr-review-sub \
  --dead-letter-topic=pr-review-dlq \
  --max-delivery-attempts=5
```

### Step 3: Grant Required Permissions

The Pub/Sub service account needs permissions to publish to the DLQ:

```bash
# Get your project number
PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")

# Grant publisher role on DLQ topic
gcloud pubsub topics add-iam-policy-binding pr-review-dlq \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

# Grant subscriber role on main subscription (for acknowledgment)
gcloud pubsub subscriptions add-iam-policy-binding pr-review-sub \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role="roles/pubsub.subscriber"
```

### How It Works

1. **Retryable errors** (500s, timeouts): Pub/Sub retries up to `max-delivery-attempts` (5)
2. **Non-retryable errors** (401, 403, 404): Function acknowledges immediately; message goes to DLQ after max attempts
3. **Failed messages** include metadata: `CloudPubSubDeadLetterSourceDeliveryCount`, `CloudPubSubDeadLetterSourceSubscription`

### Monitoring Failed Messages

```bash
# Pull messages from DLQ for inspection
gcloud pubsub subscriptions pull pr-review-dlq-sub --limit=10 --auto-ack

# View without acknowledging
gcloud pubsub subscriptions pull pr-review-dlq-sub --limit=10
```

### Retry Behavior Summary

| Error Type | HTTP Code | Retries | Final Destination |
|------------|-----------|---------|-------------------|
| Auth failure | 401, 403 | 0 (immediate fail) | DLQ |
| Not found | 404 | 0 (immediate fail) | DLQ |
| Server error | 500, 502, 503 | Up to 5 | DLQ if all fail |
| Timeout | - | Up to 5 | DLQ if all fail |
| Gemini error | - | Up to 3 (app-level) | Marked failed in GCS |

## Limitations

- Large PRs with many files may hit Gemini token limits
- Binary files are skipped automatically
- Timeout set to 300s (5 min) — very large PRs may need adjustment

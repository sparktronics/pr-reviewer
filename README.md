# RAWL 9001 POC - PR Regression Review

A lightweight script that fetches Pull Requests from Azure DevOps and sends them to Gemini (Vertex AI) for regression-focused review of AEM frontend components.

**Note:** Uses the new Google GenAI SDK (`google-genai`) which replaces the deprecated `google-cloud-aiplatform` SDK.

## Features

- Fetches PR metadata and full file contents from Azure DevOps
- Sends both "before" and "after" versions to Gemini for comparison
- Generates a regression-focused review targeting AEM/HTL/JS/CSS
- Outputs a structured markdown report (<200 lines)

## Setup

### 1. Install Dependencies

```bash
pip3 install -r requirements.txt
```

**Note:** The script uses `google-genai>=1.37.0`, which is the new SDK replacing the deprecated `google-cloud-aiplatform`.

### 2. Configure Environment Variables

You need to set these environment variables before running the script:

**Option 1: Using .env file (Recommended):**
```bash
# Copy the example file
cp env.example .env

# Edit .env with your actual values
nano .env

# The script will automatically load .env when it runs!
```

**Option 2: Quick Setup (current session only):**
```bash
export AZURE_DEVOPS_PAT="your-pat-token"
export AZURE_DEVOPS_ORG="your-org"
export AZURE_DEVOPS_PROJECT="your-project"
export AZURE_DEVOPS_REPO="your-repo"
export VERTEX_PROJECT="rawl-extractor"
export VERTEX_LOCATION="europe-west1"
```

**Option 3: Interactive Setup:**
```bash
source setup-env.sh
```

For detailed setup instructions, including how to get an Azure DevOps PAT, see [SETUP.md](SETUP.md).

### 3. GCP Authentication

Ensure you're authenticated with GCP and have set the quota project:

```bash
gcloud auth application-default login --project=your-gcp-project
```

This creates Application Default Credentials (ADC) that the Google GenAI SDK will use automatically.

## Usage

```bash
python pr_regression_review.py <PR_ID>
```

Example:

```bash
python pr_regression_review.py 1234
```

This will:
1. Fetch PR #1234 from Azure DevOps
2. Get all changed files with full content
3. Send to Gemini for regression analysis
4. Save review to `pr-1234-review.md`
5. Print review to stdout

## Output

The script generates a markdown file with:

- **Summary** - Brief description of changes
- **Regression Risk Assessment** - High/Medium/Low categorized risks
- **Recommended Test Coverage** - Specific scenarios to validate
- **Detailed Findings** - File-by-file analysis following the RAWL rule format

## Review Focus Areas

The Gemini prompt is tuned to detect:

| Risk Type | Examples |
|-----------|----------|
| Dialog Elimination | Removed AEM dialogs, restructured author interfaces |
| Function Removal | Deleted public JS functions other components may call |
| Behavior Changes | Modified logic affecting existing features |
| API Stability | Changed data-attributes, CSS classes, JS interfaces |
| HTL Contract Changes | Modified Sling Model properties, template parameters |
| CSS Breaking Changes | Renamed/removed classes, changed specificity |

## Azure DevOps PAT Permissions

Your PAT needs:
- **Code (Read)** - To fetch file contents
- **Pull Request (Read)** - To fetch PR metadata and changes

## Limitations

- Processes all changed files (no filtering by extension yet)
- Large PRs with many files may hit token limits
- Binary files are skipped automatically by the API

#!/usr/bin/env python3
"""
RAWL 9001 POC - PR Regression Review Cloud Function

HTTP Cloud Function that fetches a Pull Request from Azure DevOps, sends it to
Gemini (Vertex AI) for regression-focused review, stores the result in Cloud Storage,
and optionally comments/rejects the PR based on severity.

Environment Variables:
    API_KEY               - API key for authenticating requests
    GCS_BUCKET            - Cloud Storage bucket for storing reviews
    AZURE_DEVOPS_PAT      - Personal Access Token
    AZURE_DEVOPS_ORG      - Organization name
    AZURE_DEVOPS_PROJECT  - Project name  
    AZURE_DEVOPS_REPO     - Repository name (or ID)
    VERTEX_PROJECT        - GCP Project ID
    VERTEX_LOCATION       - GCP Region (default: us-central1)
    PUBSUB_TOPIC          - Pub/Sub topic for webhook messages (default: pr-review-trigger)

Entry Points:
    review_pr          - HTTP endpoint for synchronous PR review
    review_pr_pubsub   - Pub/Sub triggered async PR review (with idempotency)
    receive_webhook    - HTTP webhook receiver that publishes to Pub/Sub
"""

import os
import json
import logging
import time
import requests
from contextlib import contextmanager
from datetime import datetime, timezone

import base64

import functions_framework
from cloudevents.http import CloudEvent
from google import genai
from google.cloud import storage
from google.cloud import pubsub_v1
from google.api_core.exceptions import PreconditionFailed


# =============================================================================
# Timing Utilities for External Operations
# =============================================================================

@contextmanager
def timed_operation():
    """Context manager that tracks operation timing.
    
    Yields a callable that returns elapsed milliseconds since context entry.
    Use for external API calls and storage operations only.
    
    Example:
        with timed_operation() as elapsed:
            response = requests.get(url)
            logger.info(f"Request completed in {elapsed():.0f}ms")
    """
    start_time = time.time()
    yield lambda: (time.time() - start_time) * 1000


# =============================================================================
# Logging Configuration
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

def load_config() -> tuple[dict, list]:
    """Load configuration from environment variables.
    
    Returns:
        tuple: (config dict, list of missing required vars)
    """
    required = [
        "API_KEY",
        "GCS_BUCKET",
        "AZURE_DEVOPS_PAT",
        "AZURE_DEVOPS_ORG", 
        "AZURE_DEVOPS_PROJECT",
        "AZURE_DEVOPS_REPO",
        "VERTEX_PROJECT",
    ]
    
    config = {}
    missing = []
    
    for var in required:
        value = os.environ.get(var)
        if not value:
            missing.append(var)
        config[var] = value
    
    # Optional with default
    config["VERTEX_LOCATION"] = os.environ.get("VERTEX_LOCATION", "us-central1")
    
    return config, missing


# =============================================================================
# Azure DevOps API Client
# =============================================================================

class AzureDevOpsClient:
    """Simple client for Azure DevOps REST API."""
    
    API_VERSION = "7.1-preview"
    
    def __init__(self, org: str, project: str, repo: str, pat: str):
        self.org = org
        self.project = project
        self.base_url = f"https://dev.azure.com/{org}/{project}/_apis"
        self.repo = repo
        self.auth = ("", pat)  # Basic auth with empty username
    
    def _request(self, method: str, endpoint: str, data: dict = None, extra_params: dict = None) -> dict:
        """Make HTTP request to Azure DevOps API with timing.
        
        Args:
            method: HTTP method (GET, POST, PUT)
            endpoint: API endpoint path
            data: Request body for POST/PUT requests
            extra_params: Additional query parameters (merged with api-version)
            
        Returns:
            Response JSON as dict
        """
        url = f"{self.base_url}{endpoint}"
        params = extra_params.copy() if extra_params else {}
        params["api-version"] = self.API_VERSION
        headers = {"Content-Type": "application/json"} if method in ("POST", "PUT") else None
        
        logger.info(f"[ADO {method}] {endpoint}")
        if data:
            logger.debug(f"[ADO {method}] Payload keys: {list(data.keys())}")
        
        start_time = time.time()
        try:
            response = requests.request(
                method, url, auth=self.auth, params=params, headers=headers, json=data
            )
            elapsed = (time.time() - start_time) * 1000
            
            logger.info(f"[ADO {method}] {endpoint} | Status: {response.status_code} | {elapsed:.0f}ms")
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            elapsed = (time.time() - start_time) * 1000
            logger.error(f"[ADO {method}] {endpoint} | FAILED | Status: {e.response.status_code} | {elapsed:.0f}ms")
            logger.error(f"[ADO {method}] Error response: {e.response.text[:500]}")
            raise
    
    def _get(self, endpoint: str, params: dict = None) -> dict:
        """Make GET request to Azure DevOps API."""
        return self._request("GET", endpoint, extra_params=params)
    
    def _post(self, endpoint: str, data: dict) -> dict:
        """Make POST request to Azure DevOps API."""
        return self._request("POST", endpoint, data=data)
    
    def _put(self, endpoint: str, data: dict) -> dict:
        """Make PUT request to Azure DevOps API."""
        return self._request("PUT", endpoint, data=data)
    
    def get_pull_request(self, pr_id: int) -> dict:
        """Fetch PR metadata."""
        return self._get(f"/git/repositories/{self.repo}/pullrequests/{pr_id}")
    
    def get_pr_iterations(self, pr_id: int) -> list:
        """Get PR iterations (each push creates a new iteration)."""
        result = self._get(f"/git/repositories/{self.repo}/pullrequests/{pr_id}/iterations")
        return result.get("value", [])
    
    def get_pr_changes(self, pr_id: int, iteration_id: int = None) -> list:
        """Get changed files in a PR iteration."""
        if iteration_id is None:
            iterations = self.get_pr_iterations(pr_id)
            if not iterations:
                return []
            iteration_id = iterations[-1]["id"]  # Latest iteration
        
        result = self._get(
            f"/git/repositories/{self.repo}/pullrequests/{pr_id}/iterations/{iteration_id}/changes"
        )
        return result.get("changeEntries", [])
    
    def get_file_content(self, path: str, commit_id: str) -> str:
        """Fetch file content at a specific commit."""
        url = f"{self.base_url}/git/repositories/{self.repo}/items"
        params = {
            "path": path,
            "versionDescriptor.version": commit_id,
            "versionDescriptor.versionType": "commit",
            "api-version": self.API_VERSION,
        }
        
        logger.debug(f"[ADO FILE] Fetching: {path} @ {commit_id[:8]}")
        
        with timed_operation() as elapsed:
            try:
                response = requests.get(url, auth=self.auth, params=params)
                response.raise_for_status()
                logger.debug(f"[ADO FILE] {path} | {len(response.text)} bytes | {elapsed():.0f}ms")
                return response.text
            except requests.HTTPError as e:
                logger.debug(f"[ADO FILE] {path} | Not found (status {e.response.status_code}) | {elapsed():.0f}ms")
                return None  # File might not exist in this version
    
    def get_pr_diff(self, pr_id: int) -> list:
        """
        Get full diff for a PR with file contents from both source and target.
        Returns list of dicts with path, change_type, source_content, target_content.
        """
        logger.info(f"[ADO] Fetching full diff for PR #{pr_id}")
        
        with timed_operation() as elapsed:
            pr = self.get_pull_request(pr_id)
            source_commit = pr["lastMergeSourceCommit"]["commitId"]
            target_commit = pr["lastMergeTargetCommit"]["commitId"]
            logger.info(f"[ADO] PR commits: source={source_commit[:8]} target={target_commit[:8]}")
            
            changes = self.get_pr_changes(pr_id)
            logger.info(f"[ADO] Found {len(changes)} changed items in PR")
            
            file_diffs = []
            files_processed = 0
            for change in changes:
                item = change.get("item", {})
                path = item.get("path", "")
                change_type = change.get("changeType", "unknown")
                
                # Skip folders
                if item.get("isFolder"):
                    logger.debug(f"[ADO] Skipping folder: {path}")
                    continue
                
                # Get content from both versions
                source_content = self.get_file_content(path, source_commit)
                target_content = self.get_file_content(path, target_commit)
                
                file_diffs.append({
                    "path": path,
                    "change_type": change_type,
                    "source_content": source_content,  # New version (PR branch)
                    "target_content": target_content,  # Old version (target branch)
                })
                files_processed += 1
            
            logger.info(f"[ADO] Diff complete: {files_processed} files | {elapsed():.0f}ms total")
            
            return file_diffs
    
    def post_pr_comment(self, pr_id: int, content: str) -> dict:
        """Post a comment thread on a PR.
        
        Args:
            pr_id: Pull request ID
            content: Markdown content for the comment
            
        Returns:
            API response dict
        """
        data = {
            "comments": [
                {
                    "parentCommentId": 0,
                    "content": content,
                    "commentType": 1,  # Text comment
                }
            ],
            "status": 1,  # Active
        }
        return self._post(f"/git/repositories/{self.repo}/pullrequests/{pr_id}/threads", data)
    
    def reject_pr(self, pr_id: int, reviewer_id: str) -> dict:
        """Reject a PR by voting -10 (reject).
        
        Args:
            pr_id: Pull request ID
            reviewer_id: The reviewer's identity ID (usually the PAT owner's ID)
            
        Returns:
            API response dict
        """
        # Vote values: 10=approved, 5=approved with suggestions, 0=no vote, -5=waiting, -10=rejected
        data = {"vote": -10}
        return self._put(
            f"/git/repositories/{self.repo}/pullrequests/{pr_id}/reviewers/{reviewer_id}",
            data
        )
    
    def get_current_user_id(self) -> str:
        """Get the current user's ID (PAT owner) from Azure DevOps.
        
        Returns:
            User's identity ID string
        """
        # Use the connection data endpoint to get current user info
        url = f"https://dev.azure.com/{self.org}/_apis/connectionData"
        params = {"api-version": self.API_VERSION}
        
        logger.info("[ADO] Fetching current user identity")
        
        with timed_operation() as elapsed:
            try:
                response = requests.get(url, auth=self.auth, params=params)
                response.raise_for_status()
                data = response.json()
                
                user_id = data["authenticatedUser"]["id"]
                user_name = data["authenticatedUser"].get("providerDisplayName", "unknown")
                logger.info(f"[ADO] Current user: {user_name} (id={user_id[:8]}...) | {elapsed():.0f}ms")
                
                return user_id
            except requests.HTTPError as e:
                logger.error(f"[ADO] Failed to get user identity | Status: {e.response.status_code} | {elapsed():.0f}ms")
                raise


# =============================================================================
# Cloud Storage
# =============================================================================

def save_to_storage(bucket_name: str, pr_id: int, review: str) -> str:
    """Save review to Cloud Storage with date partitioning.
    
    Args:
        bucket_name: GCS bucket name
        pr_id: Pull request ID
        review: Markdown review content
        
    Returns:
        Full GCS path (gs://bucket/path)
    """
    logger.info(f"[GCS] Saving review for PR #{pr_id} to bucket: {bucket_name}")
    logger.debug(f"[GCS] Review content size: {len(review)} chars")
    
    with timed_operation() as elapsed:
        try:
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            
            # Date partitioning: yyyy/mm/dd
            now = datetime.now(timezone.utc)
            date_path = now.strftime("%Y/%m/%d")
            timestamp = now.strftime("%H%M%S")
            
            blob_path = f"reviews/{date_path}/pr-{pr_id}-{timestamp}-review.md"
            blob = bucket.blob(blob_path)
            
            blob.upload_from_string(review, content_type="text/markdown")
            
            full_path = f"gs://{bucket_name}/{blob_path}"
            logger.info(f"[GCS] Upload complete: {blob_path} | {len(review)} bytes | {elapsed():.0f}ms")
            
            return full_path
        except Exception as e:
            logger.error(f"[GCS] Upload FAILED | {elapsed():.0f}ms | Error: {str(e)}")
            raise


# =============================================================================
# Idempotency - Prevent duplicate processing via GCS markers
# =============================================================================

def check_and_claim_processing(bucket_name: str, pr_id: int, commit_sha: str) -> bool:
    """
    Check if this PR+commit has been processed. If not, claim it atomically.
    
    Uses GCS conditional writes (if_generation_match=0) to ensure only one
    instance can claim processing for a given PR+commit combination.
    
    Args:
        bucket_name: GCS bucket name
        pr_id: Pull request ID
        commit_sha: The commit SHA being reviewed
        
    Returns:
        True if we should process (we claimed it)
        False if already processed or claimed by another instance
    """
    logger.info(f"[IDEMPOTENCY] Checking marker for PR #{pr_id} @ {commit_sha[:8]}")
    
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(f"idempotency/pr-{pr_id}-{commit_sha}.json")
    
    # Check if already processed
    if blob.exists():
        logger.info(f"[IDEMPOTENCY] PR #{pr_id} @ {commit_sha[:8]} already processed - SKIPPING")
        return False
    
    # Try to claim it atomically
    # if_generation_match=0 means "only succeed if file doesn't exist"
    marker = {
        "pr_id": pr_id,
        "commit_sha": commit_sha,
        "claimed_at": datetime.now(timezone.utc).isoformat(),
        "status": "processing"
    }
    
    try:
        blob.upload_from_string(
            json.dumps(marker, indent=2),
            content_type="application/json",
            if_generation_match=0  # Atomic: fails if file exists
        )
        logger.info(f"[IDEMPOTENCY] Claimed processing for PR #{pr_id} @ {commit_sha[:8]}")
        return True
    except PreconditionFailed:
        logger.info(f"[IDEMPOTENCY] Race condition - another instance claimed PR #{pr_id} @ {commit_sha[:8]} - SKIPPING")
        return False


def update_marker_completed(bucket_name: str, pr_id: int, commit_sha: str,
                            max_severity: str, commented: bool) -> None:
    """
    Update the idempotency marker after successful processing.
    
    Args:
        bucket_name: GCS bucket name
        pr_id: Pull request ID
        commit_sha: The commit SHA that was reviewed
        max_severity: The maximum severity found in the review
        commented: Whether a comment was posted to the PR
    """
    logger.info(f"[IDEMPOTENCY] Updating marker for PR #{pr_id} @ {commit_sha[:8]} -> completed")
    
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(f"idempotency/pr-{pr_id}-{commit_sha}.json")
    
    marker = {
        "pr_id": pr_id,
        "commit_sha": commit_sha,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "max_severity": max_severity,
        "commented": commented
    }
    
    blob.upload_from_string(
        json.dumps(marker, indent=2),
        content_type="application/json"
    )
    logger.info(f"[IDEMPOTENCY] Marker updated: severity={max_severity}, commented={commented}")


def delete_marker(bucket_name: str, pr_id: int, commit_sha: str) -> None:
    """
    Delete an idempotency marker (used on processing failure to allow retry).
    
    Args:
        bucket_name: GCS bucket name
        pr_id: Pull request ID
        commit_sha: The commit SHA
    """
    logger.info(f"[IDEMPOTENCY] Deleting marker for PR #{pr_id} @ {commit_sha[:8]} (allowing retry)")
    
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(f"idempotency/pr-{pr_id}-{commit_sha}.json")
    
    try:
        blob.delete()
        logger.info(f"[IDEMPOTENCY] Marker deleted for PR #{pr_id} @ {commit_sha[:8]}")
    except Exception as e:
        logger.warning(f"[IDEMPOTENCY] Failed to delete marker: {e}")


# =============================================================================
# Severity Detection
# =============================================================================

def get_max_severity(review: str) -> str:
    """Determine the highest severity found in the review.
    
    Args:
        review: Markdown review content
        
    Returns:
        One of: "blocking", "warning", "info"
    """
    if "**Severity:** blocking" in review:
        return "blocking"
    elif "**Severity:** warning" in review:
        return "warning"
    return "info"


# =============================================================================
# Gemini Review Prompt
# =============================================================================

SYSTEM_PROMPT = """You are a senior AEM frontend developer conducting a regression-focused code review.

Your expertise covers:
- AEM 6.5 components and dialogs
- HTL (Sightly) templating
- Vanilla JavaScript (no frameworks)
- CSS styling
- HTML structure accessibility 

## Review Focus: Regression Testing for AEM Frontend Components

Analyze the pull request changes for potential regressions that could break existing functionality:

1. **Dialog Elimination**: Removed or restructured AEM dialogs that authors depend on
2. **Function Removal**: Deleted public functions or methods that other components may call
3. **Behavior Changes**: Modified logic that changes how existing features work
4. **API Stability**: Changes to data-attributes, CSS classes, or JS interfaces that consumers rely on
5. **HTL Contract Changes**: Modified Sling Model properties, template parameters, or data structures
6. **CSS Breaking Changes**: Renamed/removed classes, changed specificity, or removed styles
7. **HTML Structure Changes**: Modified HTML structure, properties that are passed to the javascript that do not include default values, prefer using java model  or layout that affects page rendering

## Output Format

Generate a markdown review report with these sections:

# PR Review: {PR Title}

**PR #{id}** | Author: {author} | {date}

## Summary
Brief description of what this PR changes (2-3 sentences).

## Regression Risk Assessment

### 🔴 High Risk
List breaking changes that will cause immediate failures. Each item should explain:
- What changed
- What will break
- Who is affected

### 🟡 Medium Risk
List changes that could cause issues depending on usage. Include:
- The risky change
- Potential impact
- Conditions under which it breaks

### 🟢 Low Risk
List changes that are unlikely to cause regressions but warrant awareness.

## Recommended Test Coverage
Specific test scenarios that should be validated before merge:
1. {scenario with expected behavior}
2. {scenario with expected behavior}
...

## Detailed Findings

For each significant finding, use this format:

### Finding: {Brief description}

**Severity:** blocking | warning | info
**Applies to:** {file path}
**Category:** security | aem | frontend | testing

{Explanation of the issue in plain sentences}

#### Before
```{language}
{old code}
```

#### After
```{language}
{new code}
```

#### Why This Matters
{Brief explanation for junior developers}

---

## Guidelines

- Be specific about file paths and line references
- Prioritize findings by regression risk, not code style
- Focus on what could break in production, not cosmetic issues
- If no significant risks found, say so clearly
- Keep the report under 200 lines total
- Do not invent issues - only report actual concerns from the diff
"""


def build_review_prompt(pr: dict, file_diffs: list) -> str:
    """Build the prompt with PR context and file diffs."""
    
    prompt_parts = [
        f"# Pull Request to Review\n",
        f"**Title:** {pr.get('title', 'Untitled')}",
        f"**ID:** {pr.get('pullRequestId')}",
        f"**Author:** {pr.get('createdBy', {}).get('displayName', 'Unknown')}",
        f"**Description:**\n{pr.get('description', 'No description provided.')}\n",
        f"**Source Branch:** {pr.get('sourceRefName', '').replace('refs/heads/', '')}",
        f"**Target Branch:** {pr.get('targetRefName', '').replace('refs/heads/', '')}\n",
        "---\n",
        "# File Changes\n",
    ]
    
    for diff in file_diffs:
        path = diff["path"]
        change_type = diff["change_type"]
        
        prompt_parts.append(f"## {path}")
        prompt_parts.append(f"**Change Type:** {change_type}\n")
        
        if change_type in ("delete", "delete, sourceRename"):
            prompt_parts.append("### Deleted Content (TARGET - being removed):")
            prompt_parts.append(f"```\n{diff['target_content'] or '(empty)'}\n```\n")
        
        elif change_type in ("add",):
            prompt_parts.append("### Added Content (SOURCE - new file):")
            prompt_parts.append(f"```\n{diff['source_content'] or '(empty)'}\n```\n")
        
        else:  # edit, rename, etc.
            prompt_parts.append("### Before (TARGET - current version):")
            prompt_parts.append(f"```\n{diff['target_content'] or '(file did not exist)'}\n```\n")
            prompt_parts.append("### After (SOURCE - proposed changes):")
            prompt_parts.append(f"```\n{diff['source_content'] or '(file will be deleted)'}\n```\n")
        
        prompt_parts.append("---\n")
    
    prompt_parts.append("\nPlease provide your regression-focused review.")
    
    return "\n".join(prompt_parts)


# =============================================================================
# Vertex AI / Gemini
# =============================================================================

def call_gemini(config: dict, prompt: str) -> str:
    """Send prompt to Gemini via Vertex AI and return response."""
    
    model_name = "gemini-2.5-pro"
    project = config["VERTEX_PROJECT"]
    location = config["VERTEX_LOCATION"]
    
    logger.info(f"[GEMINI] Calling Vertex AI | Model: {model_name} | Project: {project} | Location: {location}")
    logger.info(f"[GEMINI] Prompt size: {len(prompt)} chars | System prompt: {len(SYSTEM_PROMPT)} chars")
    logger.debug(f"[GEMINI] Config: max_output_tokens=8192, temperature=0.2")
    
    with timed_operation() as elapsed:
        try:
            # Initialize the GenAI client for Vertex AI
            client = genai.Client(
                vertexai=True,
                project=project,
                location=location,
            )
            
            logger.debug(f"[GEMINI] Client initialized in {elapsed():.0f}ms")
            
            # Generate content with system instruction
            generate_start = time.time()
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "max_output_tokens": 8192,
                    "temperature": 0.2,  # Lower for more focused analysis
                },
            )
            
            generate_time = (time.time() - generate_start) * 1000
            response_size = len(response.text) if response.text else 0
            
            logger.info(f"[GEMINI] Response received | {response_size} chars | Generate: {generate_time:.0f}ms | Total: {elapsed():.0f}ms")
            
            # Log usage metadata if available
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage = response.usage_metadata
                logger.info(f"[GEMINI] Tokens - Input: {getattr(usage, 'prompt_token_count', 'N/A')} | Output: {getattr(usage, 'candidates_token_count', 'N/A')}")
            
            return response.text
            
        except Exception as e:
            logger.error(f"[GEMINI] API call FAILED | {elapsed():.0f}ms | Error type: {type(e).__name__}")
            logger.error(f"[GEMINI] Error details: {str(e)}")
            raise


# =============================================================================
# HTTP Cloud Function Entry Point
# =============================================================================

def make_response(data: dict, status: int = 200) -> tuple:
    """Create a JSON response tuple."""
    return (json.dumps(data), status, {"Content-Type": "application/json"})


@functions_framework.http
def review_pr(request):
    """HTTP Cloud Function entry point for PR regression review.
    
    Request:
        POST with JSON body: {"pr_id": 12345}
        Header: X-API-Key: <your-api-key>
        
    Response:
        JSON with review results and actions taken
    """
    with timed_operation() as elapsed:
        logger.info("=" * 60)
        logger.info("[REQUEST] PR Review function invoked")
        logger.info(f"[REQUEST] Method: {request.method} | Path: {request.path}")
        
        # Load config
        config, missing = load_config()
        if missing:
            logger.error(f"[CONFIG] Missing required environment variables: {missing}")
            return make_response(
                {"error": f"Missing config: {', '.join(missing)}"}, 500
            )
        logger.info("[CONFIG] All required environment variables loaded")
        
        # Validate API key
        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key != config["API_KEY"]:
            logger.warning("[AUTH] Invalid or missing API key")
            return make_response({"error": "Invalid or missing API key"}, 401)
        logger.info("[AUTH] API key validated")
        
        # Parse request
        try:
            request_json = request.get_json(silent=True)
            if not request_json:
                logger.warning("[REQUEST] Empty or invalid JSON body")
                return make_response({"error": "Request body must be JSON"}, 400)
            
            pr_id = request_json.get("pr_id")
            if not pr_id:
                logger.warning("[REQUEST] Missing pr_id in request body")
                return make_response({"error": "Missing required field: pr_id"}, 400)
            
            pr_id = int(pr_id)
            logger.info(f"[REQUEST] Processing PR #{pr_id}")
        except (ValueError, TypeError) as e:
            logger.error(f"[REQUEST] Invalid pr_id format: {e}")
            return make_response({"error": f"Invalid pr_id: {e}"}, 400)
        
        # Initialize Azure DevOps client
        logger.info(f"[ADO] Initializing client | Org: {config['AZURE_DEVOPS_ORG']} | Project: {config['AZURE_DEVOPS_PROJECT']} | Repo: {config['AZURE_DEVOPS_REPO']}")
        ado = AzureDevOpsClient(
            org=config["AZURE_DEVOPS_ORG"],
            project=config["AZURE_DEVOPS_PROJECT"],
            repo=config["AZURE_DEVOPS_REPO"],
            pat=config["AZURE_DEVOPS_PAT"],
        )
        
        try:
            # Fetch PR data
            logger.info(f"[FLOW] Step 1/5: Fetching PR metadata")
            pr = ado.get_pull_request(pr_id)
            pr_title = pr.get("title", "Untitled")
            pr_author = pr.get("createdBy", {}).get("displayName", "Unknown")
            logger.info(f"[FLOW] PR: '{pr_title}' by {pr_author}")
            
            # Fetch file diffs
            logger.info(f"[FLOW] Step 2/5: Fetching file diffs")
            file_diffs = ado.get_pr_diff(pr_id)
            
            if not file_diffs:
                logger.info(f"[FLOW] No file changes found | Total time: {elapsed():.0f}ms")
                return make_response({
                    "pr_id": pr_id,
                    "title": pr_title,
                    "message": "No file changes found in this PR",
                    "has_blocking": False,
                    "has_warning": False,
                    "action_taken": None,
                    "commented": False,
                    "storage_path": None,
                })
            
            logger.info(f"[FLOW] Found {len(file_diffs)} files to review")
            for diff in file_diffs:
                logger.debug(f"[FLOW]   - {diff['path']} ({diff['change_type']})")
            
            # Build prompt and call Gemini
            logger.info(f"[FLOW] Step 3/5: Building prompt and calling Gemini")
            prompt = build_review_prompt(pr, file_diffs)
            logger.info(f"[FLOW] Prompt built: {len(prompt)} chars")
            
            review = call_gemini(config, prompt)
            
            # Determine severity
            logger.info(f"[FLOW] Step 4/5: Analyzing severity")
            max_severity = get_max_severity(review)
            has_blocking = max_severity == "blocking"
            has_warning = max_severity == "warning"
            logger.info(f"[FLOW] Severity assessment: {max_severity.upper()} | blocking={has_blocking} | warning={has_warning}")
            
            # Save to Cloud Storage
            logger.info(f"[FLOW] Step 5/5: Saving to Cloud Storage")
            storage_path = save_to_storage(config["GCS_BUCKET"], pr_id, review)
            
            # Take action based on severity
            commented = False
            action_taken = None
            
            if has_blocking or has_warning:
                logger.info(f"[ACTION] Posting review comment to PR #{pr_id}")
                # Post comment with full review
                comment_header = "##  Automated Regression Review\n\n"
                if has_blocking:
                    comment_header += "⛔ **Sorry Dave, I can't merge you this time. This PR has been automatically rejected due to blocking issues.**\n\n"
                else:
                    comment_header += "⚠️ **Warning: This PR has potential issues that should be reviewed.**\n\n"
                
                comment_header += f"📁 Full review saved to: `{storage_path}`\n\n---\n\n"
                
                ado.post_pr_comment(pr_id, comment_header + review)
                commented = True
                logger.info(f"[ACTION] Comment posted successfully")
                
                if has_blocking:
                    # Reject the PR
                    logger.info(f"[ACTION] Rejecting PR due to blocking issues")
                    user_id = ado.get_current_user_id()
                    ado.reject_pr(pr_id, user_id)
                    action_taken = "rejected"
                    logger.info(f"[ACTION] PR #{pr_id} rejected")
                else:
                    action_taken = "commented"
            else:
                logger.info(f"[ACTION] No issues found - no action taken on PR")
            
            logger.info(f"[COMPLETE] PR #{pr_id} review finished | Severity: {max_severity} | Action: {action_taken or 'none'} | Total time: {elapsed():.0f}ms")
            logger.info("=" * 60)
            
            return make_response({
                "pr_id": pr_id,
                "title": pr_title,
                "files_changed": len(file_diffs),
                "max_severity": max_severity,
                "has_blocking": has_blocking,
                "has_warning": has_warning,
                "action_taken": action_taken,
                "commented": commented,
                "storage_path": storage_path,
                "review_preview": review[:500] + "..." if len(review) > 500 else review,
            })
            
        except requests.HTTPError as e:
            logger.error(f"[ERROR] Azure DevOps API error | Status: {e.response.status_code} | {elapsed():.0f}ms")
            logger.error(f"[ERROR] Response body: {e.response.text[:500]}")
            return make_response({
                "error": f"Azure DevOps API error: {e.response.status_code} - {e.response.text}"
            }, 502)
        except Exception as e:
            logger.error(f"[ERROR] Internal error | Type: {type(e).__name__} | {elapsed():.0f}ms")
            logger.error(f"[ERROR] Details: {str(e)}", exc_info=True)
            return make_response({"error": f"Internal error: {str(e)}"}, 500)


# =============================================================================
# Pub/Sub Cloud Function Entry Point (with Idempotency)
# =============================================================================

@functions_framework.cloud_event
def review_pr_pubsub(cloud_event: CloudEvent) -> None:
    """
    Pub/Sub triggered Cloud Function entry point for PR regression review.
    
    Includes idempotency handling to prevent duplicate processing when
    Pub/Sub delivers the same message multiple times (at-least-once delivery).
    
    Pub/Sub Message Format:
        {
            "pr_id": 12345,
            "commit_sha": "abc123def...",  // Optional: provided by webhook receiver
            "received_at": "2026-01-03T10:30:00Z",
            "source": "azure-devops-pipeline"
        }
        
    The function will:
    1. Parse the PR ID and optional commit_sha from the Pub/Sub message
    2. Fetch PR metadata (use commit_sha from message if provided)
    3. Check idempotency marker (skip if already processed)
    4. Process the PR review
    5. Update the marker on completion
    """
    with timed_operation() as elapsed:
        logger.info("=" * 60)
        logger.info("[PUBSUB] PR Review function invoked via Pub/Sub")
        
        # Load config
        config, missing = load_config()
        if missing:
            logger.error(f"[CONFIG] Missing required environment variables: {missing}")
            # Don't raise - acknowledge message to prevent infinite retries on config errors
            return
        logger.info("[CONFIG] All required environment variables loaded")
        
        # Parse Pub/Sub message
        try:
            message_data = cloud_event.data.get("message", {}).get("data", "")
            if message_data:
                decoded = base64.b64decode(message_data).decode("utf-8")
                message = json.loads(decoded)
            else:
                logger.error("[PUBSUB] Empty message data")
                return
            
            pr_id = message.get("pr_id")
            if not pr_id:
                logger.error("[PUBSUB] Missing pr_id in message")
                return
            
            pr_id = int(pr_id)
            
            # Extract commit_sha from message (provided by webhook receiver)
            message_commit_sha = message.get("commit_sha")
            if message_commit_sha:
                logger.info(f"[PUBSUB] Processing PR #{pr_id} @ {message_commit_sha[:8]} (from message)")
            else:
                logger.info(f"[PUBSUB] Processing PR #{pr_id} (commit_sha will be fetched from ADO)")
            
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            logger.error(f"[PUBSUB] Failed to parse message: {e}")
            return  # Acknowledge to prevent retries on malformed messages
        
        # Initialize Azure DevOps client
        logger.info(f"[ADO] Initializing client | Org: {config['AZURE_DEVOPS_ORG']} | Project: {config['AZURE_DEVOPS_PROJECT']}")
        ado = AzureDevOpsClient(
            org=config["AZURE_DEVOPS_ORG"],
            project=config["AZURE_DEVOPS_PROJECT"],
            repo=config["AZURE_DEVOPS_REPO"],
            pat=config["AZURE_DEVOPS_PAT"],
        )
        
        commit_sha = None
        
        try:
            # Fetch PR metadata
            logger.info(f"[FLOW] Step 1/6: Fetching PR metadata")
            pr = ado.get_pull_request(pr_id)
            pr_title = pr.get("title", "Untitled")
            pr_author = pr.get("createdBy", {}).get("displayName", "Unknown")
            
            # Use commit_sha from message if provided, otherwise fetch from PR metadata
            if message_commit_sha:
                commit_sha = message_commit_sha
                logger.info(f"[FLOW] Using commit_sha from message: {commit_sha[:8]}")
            else:
                commit_sha = pr["lastMergeSourceCommit"]["commitId"]
                logger.info(f"[FLOW] Fetched commit_sha from ADO: {commit_sha[:8]}")
            
            logger.info(f"[FLOW] PR: '{pr_title}' by {pr_author} @ commit {commit_sha[:8]}")
            
            # Idempotency check
            logger.info(f"[FLOW] Step 2/6: Checking idempotency")
            bucket_name = config["GCS_BUCKET"]
            if not check_and_claim_processing(bucket_name, pr_id, commit_sha):
                logger.info(f"[COMPLETE] PR #{pr_id} @ {commit_sha[:8]} already processed | {elapsed():.0f}ms")
                logger.info("=" * 60)
                return  # Already processed - acknowledge and exit
            
            # Fetch file diffs
            logger.info(f"[FLOW] Step 3/6: Fetching file diffs")
            file_diffs = ado.get_pr_diff(pr_id)
            
            if not file_diffs:
                logger.info(f"[FLOW] No file changes found")
                update_marker_completed(bucket_name, pr_id, commit_sha, "info", False)
                logger.info(f"[COMPLETE] PR #{pr_id} - no files to review | {elapsed():.0f}ms")
                logger.info("=" * 60)
                return
            
            logger.info(f"[FLOW] Found {len(file_diffs)} files to review")
            
            # Build prompt and call Gemini
            logger.info(f"[FLOW] Step 4/6: Building prompt and calling Gemini")
            prompt = build_review_prompt(pr, file_diffs)
            logger.info(f"[FLOW] Prompt built: {len(prompt)} chars")
            
            review = call_gemini(config, prompt)
            
            # Determine severity
            logger.info(f"[FLOW] Step 5/6: Analyzing severity")
            max_severity = get_max_severity(review)
            has_blocking = max_severity == "blocking"
            has_warning = max_severity == "warning"
            logger.info(f"[FLOW] Severity: {max_severity.upper()}")
            
            # Save to Cloud Storage
            logger.info(f"[FLOW] Step 6/6: Saving to Cloud Storage and taking action")
            storage_path = save_to_storage(bucket_name, pr_id, review)
            
            # Take action based on severity
            commented = False
            
            if has_blocking or has_warning:
                logger.info(f"[ACTION] Posting review comment to PR #{pr_id}")
                comment_header = "## 🤖 Automated Regression Review\n\n"
                if has_blocking:
                    comment_header += "⛔ **Sorry Dave, I can't merge you this time. This PR has been automatically rejected due to blocking issues.**\n\n"
                else:
                    comment_header += "⚠️ **Warning: This PR has potential issues that should be reviewed.**\n\n"
                
                comment_header += f"📁 Full review saved to: `{storage_path}`\n\n---\n\n"
                
                ado.post_pr_comment(pr_id, comment_header + review)
                commented = True
                logger.info(f"[ACTION] Comment posted successfully")
                
                if has_blocking:
                    logger.info(f"[ACTION] Rejecting PR due to blocking issues")
                    user_id = ado.get_current_user_id()
                    ado.reject_pr(pr_id, user_id)
                    logger.info(f"[ACTION] PR #{pr_id} rejected")
            
            # Update idempotency marker with completion status
            update_marker_completed(bucket_name, pr_id, commit_sha, max_severity, commented)
            
            logger.info(f"[COMPLETE] PR #{pr_id} @ {commit_sha[:8]} review finished | Severity: {max_severity} | {elapsed():.0f}ms")
            logger.info("=" * 60)
            
        except requests.HTTPError as e:
            logger.error(f"[ERROR] Azure DevOps API error | Status: {e.response.status_code} | {elapsed():.0f}ms")
            # Delete marker to allow retry
            if commit_sha:
                delete_marker(config["GCS_BUCKET"], pr_id, commit_sha)
            raise  # Re-raise to trigger Pub/Sub retry
            
        except Exception as e:
            logger.error(f"[ERROR] Internal error | Type: {type(e).__name__} | {elapsed():.0f}ms")
            logger.error(f"[ERROR] Details: {str(e)}", exc_info=True)
            # Delete marker to allow retry
            if commit_sha:
                delete_marker(config["GCS_BUCKET"], pr_id, commit_sha)
            raise  # Re-raise to trigger Pub/Sub retry


# =============================================================================
# Webhook Receiver Cloud Function Entry Point
# =============================================================================

def load_webhook_config() -> tuple[dict, list]:
    """Load minimal configuration for webhook receiver.
    
    Returns:
        tuple: (config dict, list of missing required vars)
    """
    required = ["API_KEY", "VERTEX_PROJECT"]
    
    config = {}
    missing = []
    
    for var in required:
        value = os.environ.get(var)
        if not value:
            missing.append(var)
        config[var] = value
    
    # Optional with default
    config["PUBSUB_TOPIC"] = os.environ.get("PUBSUB_TOPIC", "pr-review-trigger")
    
    return config, missing


@functions_framework.http
def receive_webhook(request):
    """
    HTTP webhook receiver for Azure DevOps pipeline.
    
    Validates the request and publishes a message to Pub/Sub for async processing.
    This decouples the webhook acknowledgment from the actual PR review processing.
    
    Request Format:
        POST /
        Content-Type: application/json
        X-API-Key: <api-key>
        
        {
            "pr_id": 357462,
            "commit_sha": "abc123def456789..."
        }
    
    Response (202 Accepted):
        {
            "status": "queued",
            "message_id": "1234567890",
            "pr_id": 357462,
            "commit_sha": "abc123de"
        }
    """
    with timed_operation() as elapsed:
        logger.info("=" * 60)
        logger.info("[WEBHOOK] PR Review webhook received")
        
        # Load minimal config (only need API_KEY and PUBSUB_TOPIC)
        config, missing = load_webhook_config()
        if missing:
            logger.error(f"[CONFIG] Missing required environment variables: {missing}")
            return {"error": f"Server configuration error: missing {missing}"}, 500
        
        # Validate API key
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            logger.warning("[AUTH] Missing X-API-Key header")
            return {"error": "Missing X-API-Key header"}, 401
        
        if api_key != config["API_KEY"]:
            logger.warning("[AUTH] Invalid API key")
            return {"error": "Invalid API key"}, 401
        
        logger.info("[AUTH] API key validated")
        
        # Parse JSON body
        try:
            data = request.get_json(force=True)
        except Exception as e:
            logger.error(f"[PARSE] Invalid JSON body: {e}")
            return {"error": "Invalid JSON body"}, 400
        
        if not data:
            logger.error("[PARSE] Empty request body")
            return {"error": "Empty request body"}, 400
        
        # Validate required fields
        pr_id = data.get("pr_id")
        commit_sha = data.get("commit_sha")
        
        if not pr_id:
            logger.error("[PARSE] Missing pr_id in request")
            return {"error": "Missing required field: pr_id"}, 400
        
        if not commit_sha:
            logger.error("[PARSE] Missing commit_sha in request")
            return {"error": "Missing required field: commit_sha"}, 400
        
        # Validate types
        try:
            pr_id = int(pr_id)
        except (ValueError, TypeError):
            logger.error(f"[PARSE] Invalid pr_id: {pr_id}")
            return {"error": "pr_id must be an integer"}, 400
        
        if not isinstance(commit_sha, str) or len(commit_sha) < 7:
            logger.error(f"[PARSE] Invalid commit_sha: {commit_sha}")
            return {"error": "commit_sha must be a string of at least 7 characters"}, 400
        
        logger.info(f"[WEBHOOK] PR #{pr_id} @ {commit_sha[:8]}")
        
        # Build Pub/Sub message
        message = {
            "pr_id": pr_id,
            "commit_sha": commit_sha,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "source": "azure-devops-pipeline"
        }
        
        # Publish to Pub/Sub
        try:
            publisher = pubsub_v1.PublisherClient()
            topic_path = publisher.topic_path(config["VERTEX_PROJECT"], config["PUBSUB_TOPIC"])
            
            message_bytes = json.dumps(message).encode("utf-8")
            
            with timed_operation() as pubsub_elapsed:
                future = publisher.publish(topic_path, message_bytes)
                message_id = future.result(timeout=30)
            
            logger.info(f"[PUBSUB] Published message {message_id} to {config['PUBSUB_TOPIC']} | {pubsub_elapsed():.0f}ms")
            
        except Exception as e:
            logger.error(f"[PUBSUB] Failed to publish message: {e}")
            return {"error": f"Failed to queue message: {str(e)}"}, 500
        
        logger.info(f"[COMPLETE] Webhook processed | PR #{pr_id} queued | {elapsed():.0f}ms")
        logger.info("=" * 60)
        
        return {
            "status": "queued",
            "message_id": message_id,
            "pr_id": pr_id,
            "commit_sha": commit_sha[:8]
        }, 202

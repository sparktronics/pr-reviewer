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
"""

import os
import json
import requests
from datetime import datetime, timezone

import functions_framework
from google import genai
from google.cloud import storage


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
    
    def _get(self, endpoint: str, params: dict = None) -> dict:
        """Make GET request to Azure DevOps API."""
        url = f"{self.base_url}{endpoint}"
        params = params or {}
        params["api-version"] = self.API_VERSION
        
        response = requests.get(url, auth=self.auth, params=params)
        response.raise_for_status()
        return response.json()
    
    def _post(self, endpoint: str, data: dict) -> dict:
        """Make POST request to Azure DevOps API."""
        url = f"{self.base_url}{endpoint}"
        params = {"api-version": self.API_VERSION}
        headers = {"Content-Type": "application/json"}
        
        response = requests.post(
            url, auth=self.auth, params=params, headers=headers, json=data
        )
        response.raise_for_status()
        return response.json()
    
    def _put(self, endpoint: str, data: dict) -> dict:
        """Make PUT request to Azure DevOps API."""
        url = f"{self.base_url}{endpoint}"
        params = {"api-version": self.API_VERSION}
        headers = {"Content-Type": "application/json"}
        
        response = requests.put(
            url, auth=self.auth, params=params, headers=headers, json=data
        )
        response.raise_for_status()
        return response.json()
    
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
        try:
            url = f"{self.base_url}/git/repositories/{self.repo}/items"
            params = {
                "path": path,
                "versionDescriptor.version": commit_id,
                "versionDescriptor.versionType": "commit",
                "api-version": self.API_VERSION,
            }
            response = requests.get(url, auth=self.auth, params=params)
            response.raise_for_status()
            return response.text
        except requests.HTTPError:
            return None  # File might not exist in this version
    
    def get_pr_diff(self, pr_id: int) -> list:
        """
        Get full diff for a PR with file contents from both source and target.
        Returns list of dicts with path, change_type, source_content, target_content.
        """
        pr = self.get_pull_request(pr_id)
        source_commit = pr["lastMergeSourceCommit"]["commitId"]
        target_commit = pr["lastMergeTargetCommit"]["commitId"]
        
        changes = self.get_pr_changes(pr_id)
        
        file_diffs = []
        for change in changes:
            item = change.get("item", {})
            path = item.get("path", "")
            change_type = change.get("changeType", "unknown")
            
            # Skip folders
            if item.get("isFolder"):
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
        
        response = requests.get(url, auth=self.auth, params=params)
        response.raise_for_status()
        data = response.json()
        
        return data["authenticatedUser"]["id"]


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
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    
    # Date partitioning: yyyy/mm/dd
    now = datetime.now(timezone.utc)
    date_path = now.strftime("%Y/%m/%d")
    timestamp = now.strftime("%H%M%S")
    
    blob_path = f"reviews/{date_path}/pr-{pr_id}-{timestamp}-review.md"
    blob = bucket.blob(blob_path)
    
    blob.upload_from_string(review, content_type="text/markdown")
    
    return f"gs://{bucket_name}/{blob_path}"


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
- HTML structure and accessibility

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
    
    # Initialize the GenAI client for Vertex AI
    client = genai.Client(
        vertexai=True,
        project=config["VERTEX_PROJECT"],
        location=config["VERTEX_LOCATION"],
    )
    
    # Generate content with system instruction
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=prompt,
        config={
            "system_instruction": SYSTEM_PROMPT,
            "max_output_tokens": 8192,
            "temperature": 0.2,  # Lower for more focused analysis
        },
    )
    
    return response.text


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
    # Load config
    config, missing = load_config()
    if missing:
        return make_response(
            {"error": f"Missing config: {', '.join(missing)}"}, 500
        )
    
    # Validate API key
    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key != config["API_KEY"]:
        return make_response({"error": "Invalid or missing API key"}, 401)
    
    # Parse request
    try:
        request_json = request.get_json(silent=True)
        if not request_json:
            return make_response({"error": "Request body must be JSON"}, 400)
        
        pr_id = request_json.get("pr_id")
        if not pr_id:
            return make_response({"error": "Missing required field: pr_id"}, 400)
        
        pr_id = int(pr_id)
    except (ValueError, TypeError) as e:
        return make_response({"error": f"Invalid pr_id: {e}"}, 400)
    
    # Initialize Azure DevOps client
    ado = AzureDevOpsClient(
        org=config["AZURE_DEVOPS_ORG"],
        project=config["AZURE_DEVOPS_PROJECT"],
        repo=config["AZURE_DEVOPS_REPO"],
        pat=config["AZURE_DEVOPS_PAT"],
    )
    
    try:
        # Fetch PR data
        pr = ado.get_pull_request(pr_id)
        pr_title = pr.get("title", "Untitled")
        
        # Fetch file diffs
        file_diffs = ado.get_pr_diff(pr_id)
        
        if not file_diffs:
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
        
        # Build prompt and call Gemini
        prompt = build_review_prompt(pr, file_diffs)
        review = call_gemini(config, prompt)
        
        # Determine severity
        max_severity = get_max_severity(review)
        has_blocking = max_severity == "blocking"
        has_warning = max_severity == "warning"
        
        # Save to Cloud Storage
        storage_path = save_to_storage(config["GCS_BUCKET"], pr_id, review)
        
        # Take action based on severity
        commented = False
        action_taken = None
        
        if has_blocking or has_warning:
            # Post comment with full review
            comment_header = "## 🤖 Automated Regression Review\n\n"
            if has_blocking:
                comment_header += "⛔ **This PR has been automatically rejected due to blocking issues.**\n\n"
            else:
                comment_header += "⚠️ **Warning: This PR has potential issues that should be reviewed.**\n\n"
            
            comment_header += f"📁 Full review saved to: `{storage_path}`\n\n---\n\n"
            
            ado.post_pr_comment(pr_id, comment_header + review)
            commented = True
            
            if has_blocking:
                # Reject the PR
                user_id = ado.get_current_user_id()
                ado.reject_pr(pr_id, user_id)
                action_taken = "rejected"
            else:
                action_taken = "commented"
        
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
        return make_response({
            "error": f"Azure DevOps API error: {e.response.status_code} - {e.response.text}"
        }, 502)
    except Exception as e:
        return make_response({"error": f"Internal error: {str(e)}"}, 500)

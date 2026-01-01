#!/usr/bin/env python3
"""
RAWL 9001 POC - PR Regression Review Script

Fetches a Pull Request from Azure DevOps and sends it to Gemini (Vertex AI)
for regression-focused review of AEM frontend components.
Uses the new Google GenAI SDK (google-genai).

Environment Variables:
    AZURE_DEVOPS_PAT      - Personal Access Token
    AZURE_DEVOPS_ORG      - Organization name
    AZURE_DEVOPS_PROJECT  - Project name  
    AZURE_DEVOPS_REPO     - Repository name (or ID)
    VERTEX_PROJECT        - GCP Project ID
    VERTEX_LOCATION       - GCP Region (default: us-central1)
"""

import os
import sys
import base64
import requests
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file (if it exists)
load_dotenv()

from google import genai


# =============================================================================
# Configuration
# =============================================================================

def load_config() -> dict:
    """Load configuration from environment variables."""
    required = [
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
    
    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)
    
    # Optional with default
    config["VERTEX_LOCATION"] = os.environ.get("VERTEX_LOCATION", "us-central1")
    
    return config


# =============================================================================
# Azure DevOps API Client
# =============================================================================

class AzureDevOpsClient:
    """Simple client for Azure DevOps REST API."""
    
    API_VERSION = "7.1"
    
    def __init__(self, org: str, project: str, repo: str, pat: str):
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
# Main
# =============================================================================

def main():
    if len(sys.argv) != 2:
        print("Usage: python pr_regression_review.py <PR_ID>")
        print("Example: python pr_regression_review.py 1234")
        sys.exit(1)
    
    try:
        pr_id = int(sys.argv[1])
    except ValueError:
        print(f"Error: PR_ID must be an integer, got '{sys.argv[1]}'")
        sys.exit(1)
    
    print(f"🔍 RAWL 9001 POC - PR Regression Review")
    print(f"=" * 40)
    
    # Load config
    config = load_config()
    print(f"✓ Config loaded")
    
    # Initialize Azure DevOps client
    ado = AzureDevOpsClient(
        org=config["AZURE_DEVOPS_ORG"],
        project=config["AZURE_DEVOPS_PROJECT"],
        repo=config["AZURE_DEVOPS_REPO"],
        pat=config["AZURE_DEVOPS_PAT"],
    )
    
    # Fetch PR data
    print(f"⏳ Fetching PR #{pr_id} from Azure DevOps...")
    pr = ado.get_pull_request(pr_id)
    print(f"✓ PR: {pr.get('title', 'Untitled')}")
    
    # Fetch file diffs
    print(f"⏳ Fetching file changes...")
    file_diffs = ado.get_pr_diff(pr_id)
    print(f"✓ Found {len(file_diffs)} changed files")
    
    if not file_diffs:
        print("⚠️  No file changes found in this PR")
        sys.exit(0)
    
    # Build prompt
    prompt = build_review_prompt(pr, file_diffs)
    
    # Call Gemini
    print(f"⏳ Sending to Gemini for review...")
    review = call_gemini(config, prompt)
    print(f"✓ Review generated")
    
    # Write output
    output_file = f"pr-{pr_id}-review.md"
    with open(output_file, "w") as f:
        f.write(review)
    
    print(f"=" * 40)
    print(f"✅ Review saved to: {output_file}")
    
    # Also print to stdout
    print(f"\n{review}")


if __name__ == "__main__":
    main()

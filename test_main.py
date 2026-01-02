"""Unit tests for main.py - PR Regression Review Cloud Function.

Run with: pytest test_main.py -v
"""

import pytest
from unittest.mock import MagicMock, patch

from main import (
    AzureDevOpsClient,
    save_to_storage,
    get_max_severity,
    build_review_prompt,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def ado_client():
    """Create an AzureDevOpsClient instance for testing."""
    return AzureDevOpsClient(
        org="test-org",
        project="test-project",
        repo="test-repo",
        pat="fake-pat-token",
    )


@pytest.fixture
def sample_pr():
    """Sample PR metadata response."""
    return {
        "pullRequestId": 12345,
        "title": "Add new feature",
        "description": "This PR adds a new feature to the component.",
        "createdBy": {"displayName": "John Doe"},
        "sourceRefName": "refs/heads/feature/new-feature",
        "targetRefName": "refs/heads/main",
        "lastMergeSourceCommit": {"commitId": "abc123def456"},
        "lastMergeTargetCommit": {"commitId": "789xyz000111"},
    }


@pytest.fixture
def sample_file_diffs():
    """Sample file diffs for prompt building."""
    return [
        {
            "path": "/src/component.js",
            "change_type": "edit",
            "source_content": "function newCode() { return true; }",
            "target_content": "function oldCode() { return false; }",
        },
        {
            "path": "/src/styles.css",
            "change_type": "add",
            "source_content": ".new-class { color: red; }",
            "target_content": None,
        },
    ]


# =============================================================================
# AzureDevOpsClient Tests
# =============================================================================

class TestAzureDevOpsClientRequest:
    """Tests for AzureDevOpsClient._request method."""

    def test_request_get_success(self, ado_client, mocker):
        """GET request returns JSON response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 1, "name": "test"}
        
        mock_request = mocker.patch("main.requests.request", return_value=mock_response)
        
        result = ado_client._get("/test/endpoint")
        
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[0][0] == "GET"
        assert "/test/endpoint" in call_args[0][1]
        assert result == {"id": 1, "name": "test"}

    def test_request_post_success(self, ado_client, mocker):
        """POST request sends payload and returns JSON."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"created": True}
        
        mock_request = mocker.patch("main.requests.request", return_value=mock_response)
        
        payload = {"content": "test data"}
        result = ado_client._post("/test/endpoint", payload)
        
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[1]["json"] == payload
        assert result == {"created": True}

    def test_request_put_success(self, ado_client, mocker):
        """PUT request sends payload and returns JSON."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"updated": True}
        
        mock_request = mocker.patch("main.requests.request", return_value=mock_response)
        
        payload = {"vote": -10}
        result = ado_client._put("/test/endpoint", payload)
        
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[0][0] == "PUT"
        assert call_args[1]["json"] == payload
        assert result == {"updated": True}


class TestAzureDevOpsClientMethods:
    """Tests for AzureDevOpsClient high-level methods."""

    def test_get_pull_request(self, ado_client, sample_pr, mocker):
        """get_pull_request fetches PR metadata."""
        mocker.patch.object(ado_client, "_get", return_value=sample_pr)
        
        result = ado_client.get_pull_request(12345)
        
        ado_client._get.assert_called_once_with("/git/repositories/test-repo/pullrequests/12345")
        assert result["pullRequestId"] == 12345
        assert result["title"] == "Add new feature"

    def test_get_file_content(self, ado_client, mocker):
        """get_file_content fetches file at specific commit."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "file content here"
        
        mocker.patch("main.requests.get", return_value=mock_response)
        
        result = ado_client.get_file_content("/src/file.js", "abc123")
        
        assert result == "file content here"

    def test_get_pr_diff(self, ado_client, sample_pr, mocker):
        """get_pr_diff aggregates file contents from source and target."""
        mocker.patch.object(ado_client, "get_pull_request", return_value=sample_pr)
        mocker.patch.object(ado_client, "get_pr_changes", return_value=[
            {
                "item": {"path": "/src/test.js", "isFolder": False},
                "changeType": "edit",
            }
        ])
        mocker.patch.object(
            ado_client, 
            "get_file_content", 
            side_effect=["new content", "old content"]
        )
        
        result = ado_client.get_pr_diff(12345)
        
        assert len(result) == 1
        assert result[0]["path"] == "/src/test.js"
        assert result[0]["change_type"] == "edit"
        assert result[0]["source_content"] == "new content"
        assert result[0]["target_content"] == "old content"


# =============================================================================
# Cloud Storage Tests
# =============================================================================

class TestSaveToStorage:
    """Tests for save_to_storage function."""

    def test_save_to_storage_success(self, mocker):
        """save_to_storage uploads review to GCS bucket."""
        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        
        mock_client = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        
        mocker.patch("main.storage.Client", return_value=mock_client)
        
        review_content = "# Review\n\nThis is a test review."
        result = save_to_storage("test-bucket", 12345, review_content)
        
        # Verify bucket was accessed
        mock_client.bucket.assert_called_once_with("test-bucket")
        
        # Verify blob was created with correct path pattern
        blob_call = mock_bucket.blob.call_args[0][0]
        assert blob_call.startswith("reviews/")
        assert "pr-12345" in blob_call
        assert blob_call.endswith("-review.md")
        
        # Verify upload was called
        mock_blob.upload_from_string.assert_called_once_with(
            review_content, 
            content_type="text/markdown"
        )
        
        # Verify return path format
        assert result.startswith("gs://test-bucket/reviews/")


# =============================================================================
# Pure Logic Tests
# =============================================================================

class TestGetMaxSeverity:
    """Tests for get_max_severity function."""

    def test_get_max_severity_blocking(self):
        """Returns 'blocking' when blocking severity found."""
        review = """
        # Review
        
        ### Finding: Critical issue
        **Severity:** blocking
        
        This is a blocking issue.
        """
        assert get_max_severity(review) == "blocking"

    def test_get_max_severity_warning(self):
        """Returns 'warning' when warning severity found (no blocking)."""
        review = """
        # Review
        
        ### Finding: Potential issue
        **Severity:** warning
        
        This could cause problems.
        """
        assert get_max_severity(review) == "warning"

    def test_get_max_severity_info(self):
        """Returns 'info' when no blocking or warning found."""
        review = """
        # Review
        
        ### Finding: Minor note
        **Severity:** info
        
        Just an observation.
        """
        assert get_max_severity(review) == "info"

    def test_get_max_severity_blocking_takes_precedence(self):
        """Returns 'blocking' even when warning is also present."""
        review = """
        # Review
        
        ### Finding: Warning issue
        **Severity:** warning
        
        ### Finding: Critical issue
        **Severity:** blocking
        """
        assert get_max_severity(review) == "blocking"

    def test_get_max_severity_empty_review(self):
        """Returns 'info' for empty review."""
        assert get_max_severity("") == "info"


class TestBuildReviewPrompt:
    """Tests for build_review_prompt function."""

    def test_build_review_prompt(self, sample_pr, sample_file_diffs):
        """build_review_prompt constructs prompt with PR context and diffs."""
        prompt = build_review_prompt(sample_pr, sample_file_diffs)
        
        # Check PR metadata is included
        assert "Add new feature" in prompt
        assert "12345" in prompt
        assert "John Doe" in prompt
        assert "feature/new-feature" in prompt
        assert "main" in prompt
        
        # Check file paths are included
        assert "/src/component.js" in prompt
        assert "/src/styles.css" in prompt
        
        # Check change types are included
        assert "edit" in prompt
        assert "add" in prompt
        
        # Check file contents are included
        assert "function newCode()" in prompt
        assert "function oldCode()" in prompt
        assert ".new-class" in prompt

    def test_build_review_prompt_with_description(self, sample_pr, sample_file_diffs):
        """build_review_prompt includes PR description."""
        prompt = build_review_prompt(sample_pr, sample_file_diffs)
        
        assert "This PR adds a new feature to the component." in prompt

    def test_build_review_prompt_ends_with_instruction(self, sample_pr, sample_file_diffs):
        """build_review_prompt ends with review instruction."""
        prompt = build_review_prompt(sample_pr, sample_file_diffs)
        
        assert prompt.strip().endswith("Please provide your regression-focused review.")


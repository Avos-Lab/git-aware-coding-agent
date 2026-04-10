"""GitHub REST API client for fetching PRs, issues, comments, and reviews.

Provides paginated listing with date filtering, rate limit handling,
and typed error mapping. Uses httpx sync client with tenacity retry
for transient 5xx errors.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from avos_cli.exceptions import (
    AuthError,
    ConfigurationNotInitializedError,
    RateLimitError,
    ResourceNotFoundError,
    UpstreamUnavailableError,
)
from avos_cli.utils.dotenv_load import load_layers
from avos_cli.utils.logger import get_logger

_log = get_logger("github_client")

_API_BASE = "https://api.github.com"
_dotenv_loaded_for_github = False


def _ensure_dotenv_for_github() -> None:
    """Load layered ``.env`` once so ``GITHUB_TOKEN`` from repo root is visible."""
    global _dotenv_loaded_for_github
    if not _dotenv_loaded_for_github:
        load_layers()
        _dotenv_loaded_for_github = True
_TIMEOUT = 30.0
_MAX_RETRIES = 3
_MAX_PAGES = 100


class _RetryableGitHubError(Exception):
    """Internal marker for transient GitHub API errors."""


class GitHubClient:
    """HTTP client for the GitHub REST API.

    Provides PR/issue listing, detail fetching, and repo validation
    with pagination, rate limit handling, and typed error mapping.

    Args:
        token: GitHub personal access token. If omitted, uses ``GITHUB_TOKEN``
            from the environment after loading layered ``.env`` files (including
            the repository root ``.env``). Pass ``""`` explicitly to require a
            non-empty token and ignore the environment.
    """

    def __init__(self, token: str | None = None) -> None:
        _ensure_dotenv_for_github()
        resolved = (
            os.environ.get("GITHUB_TOKEN", "").strip()
            if token is None
            else token.strip()
        )
        if not resolved:
            raise AuthError("GitHub token is required", service="GitHub")
        self._token = resolved
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {resolved}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=_TIMEOUT,
        )

    def list_pull_requests(
        self,
        owner: str,
        repo: str,
        since_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """List pull requests for a repository.

        Args:
            owner: Repository owner.
            repo: Repository name.
            since_date: Optional ISO date for lower-bound filtering.

        Returns:
            List of PR data dicts.
        """
        params: dict[str, str | int] = {
            "state": "all",
            "sort": "updated",
            "direction": "desc",
            "per_page": 100,
        }
        if since_date:
            params["since"] = since_date

        url = f"{_API_BASE}/repos/{owner}/{repo}/pulls"
        return self._paginate(url, params)

    def get_pr_details(
        self, owner: str, repo: str, pr_number: int
    ) -> dict[str, Any]:
        """Fetch detailed PR data including comments, reviews, and files.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.

        Returns:
            Dict with PR data, comments, reviews, and files.
        """
        base = f"{_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}"
        pr_data = self._get(base)
        comments = self._paginate(f"{base}/comments", {})
        reviews = self._paginate(f"{base}/reviews", {})
        files = self._paginate(f"{base}/files", {})

        pr_data["comments"] = comments
        pr_data["reviews"] = reviews
        pr_data["files"] = files
        return pr_data

    def list_issues(
        self,
        owner: str,
        repo: str,
        since_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """List issues (excluding PRs) for a repository.

        Args:
            owner: Repository owner.
            repo: Repository name.
            since_date: Optional ISO date for lower-bound filtering.

        Returns:
            List of issue data dicts (PRs filtered out).
        """
        params: dict[str, str | int] = {
            "state": "all",
            "sort": "updated",
            "direction": "desc",
            "per_page": 100,
        }
        if since_date:
            params["since"] = since_date

        url = f"{_API_BASE}/repos/{owner}/{repo}/issues"
        all_items = self._paginate(url, params)
        return [item for item in all_items if not item.get("pull_request")]

    def get_issue_details(
        self, owner: str, repo: str, issue_number: int
    ) -> dict[str, Any]:
        """Fetch detailed issue data including comments.

        Args:
            owner: Repository owner.
            repo: Repository name.
            issue_number: Issue number.

        Returns:
            Dict with issue data and comments.
        """
        base = f"{_API_BASE}/repos/{owner}/{repo}/issues/{issue_number}"
        issue_data = self._get(base)
        comments = self._paginate(f"{base}/comments", {})
        issue_data["comments"] = comments
        return issue_data

    def get_repo_metadata(self, owner: str, repo: str) -> dict[str, Any]:
        """Fetch repository metadata.

        Args:
            owner: Repository owner.
            repo: Repository name.

        Returns:
            Dict with repository metadata.
        """
        url = f"{_API_BASE}/repos/{owner}/{repo}"
        return self._get(url)

    def validate_repo(self, owner: str, repo: str) -> bool:
        """Check if a repository exists and is accessible.

        Args:
            owner: Repository owner.
            repo: Repository name.

        Returns:
            True if accessible, False if 404.
        """
        url = f"{_API_BASE}/repos/{owner}/{repo}"
        try:
            self._get(url)
            return True
        except ResourceNotFoundError:
            return False

    def get_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """Fetch the unified diff for a pull request.

        Uses the GitHub diff media type to get raw unified diff output.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.

        Returns:
            Raw unified diff text.

        Raises:
            ResourceNotFoundError: If the PR does not exist.
        """
        url = f"{_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}"
        response = self._request_with_retry_diff(url)
        self._check_response(response)
        return response.text

    def list_pr_commits(self, owner: str, repo: str, pr_number: int) -> list[str]:
        """List all commit SHAs in a pull request.

        Fetches the full list of commits (with pagination) and extracts
        the SHA for each commit.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.

        Returns:
            List of full 40-character commit SHAs.

        Raises:
            ResourceNotFoundError: If the PR does not exist.
        """
        url = f"{_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/commits"
        commits = self._paginate(url, {})
        return [commit["sha"] for commit in commits]

    def get_commit(self, owner: str, repo: str, commit_ref: str) -> dict[str, Any]:
        """Fetch a single commit as JSON (includes full SHA).

        Args:
            owner: Repository owner.
            repo: Repository name.
            commit_ref: Commit SHA (short or full), branch, or tag.

        Returns:
            GitHub commit object dict.

        Raises:
            ResourceNotFoundError: If the commit does not exist.
        """
        url = f"{_API_BASE}/repos/{owner}/{repo}/commits/{commit_ref}"
        return self._get(url)

    def get_commit_diff(self, owner: str, repo: str, commit_ref: str) -> str:
        """Fetch the unified diff for a commit (parent..commit).

        Uses the GitHub diff media type on the commits endpoint. No local
        git is required.

        Args:
            owner: Repository owner.
            repo: Repository name.
            commit_ref: Commit SHA (short or full), branch, or tag.

        Returns:
            Raw unified diff text.

        Raises:
            ResourceNotFoundError: If the commit does not exist.
        """
        url = f"{_API_BASE}/repos/{owner}/{repo}/commits/{commit_ref}"
        response = self._request_with_retry_diff(url)
        self._check_response(response)
        return response.text

    @retry(
        retry=retry_if_exception_type(_RetryableGitHubError),
        stop=stop_after_attempt(_MAX_RETRIES),
        wait=wait_exponential(multiplier=0.5, min=0.1, max=10),
        reraise=True,
    )
    def _request_with_retry_diff(self, url: str) -> httpx.Response:
        """Execute GET with diff Accept header and retry on 5xx errors."""
        try:
            response = self._client.get(
                url,
                headers={"Accept": "application/vnd.github.v3.diff"},
            )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise _RetryableGitHubError(str(e)) from e

        if response.status_code >= 500:
            raise _RetryableGitHubError(f"HTTP {response.status_code}")

        return response

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a GET request with error handling."""
        response = self._request_with_retry(url, params)
        self._check_response(response)
        result: dict[str, Any] = response.json()
        return result

    def _paginate(
        self, url: str, params: dict[str, str | int]
    ) -> list[dict[str, Any]]:
        """Follow pagination via Link headers up to MAX_PAGES.

        Args:
            url: Initial request URL.
            params: Query parameters for the first page.

        Returns:
            Aggregated list of all items across pages.
        """
        all_items: list[dict[str, Any]] = []
        current_url: str | None = url
        current_params: dict[str, str | int] | None = params
        page_count = 0

        while current_url and page_count < _MAX_PAGES:
            response = self._request_with_retry(current_url, current_params)
            self._check_response(response)
            self._check_rate_limit(response)

            data = response.json()
            if isinstance(data, list):
                all_items.extend(data)
            else:
                all_items.append(data)

            current_url = self._next_page_url(response)
            current_params = None
            page_count += 1

        return all_items

    @retry(
        retry=retry_if_exception_type(_RetryableGitHubError),
        stop=stop_after_attempt(_MAX_RETRIES),
        wait=wait_exponential(multiplier=0.5, min=0.1, max=10),
        reraise=True,
    )
    def _request_with_retry(
        self, url: str, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        """Execute GET with retry on 5xx errors."""
        try:
            response = self._client.get(url, params=params)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise _RetryableGitHubError(str(e)) from e

        if response.status_code >= 500:
            raise _RetryableGitHubError(f"HTTP {response.status_code}")

        return response

    def _check_response(self, response: httpx.Response) -> None:
        """Map HTTP error codes to typed exceptions."""
        if response.status_code in (401, 403):
            msg = response.json().get("message", "Authentication failed")
            raise AuthError(msg, service="GitHub")
        if response.status_code == 404:
            raise ResourceNotFoundError(
                f"GitHub resource not found: {response.url}"
            )
        if response.status_code >= 400:
            raise UpstreamUnavailableError(
                f"GitHub API error: HTTP {response.status_code}"
            )

    def _check_rate_limit(self, response: httpx.Response) -> None:
        """Log rate limit status and pause if exhausted."""
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset_ts = response.headers.get("X-RateLimit-Reset")

        if remaining is not None and int(remaining) == 0 and reset_ts:
            wait_seconds = max(0, int(reset_ts) - int(time.time()))
            if wait_seconds > 0:
                _log.warning("GitHub rate limit exhausted, waiting %ds", wait_seconds)
                raise RateLimitError(
                    "GitHub API rate limit exhausted",
                    retry_after=float(wait_seconds),
                )

    def _next_page_url(self, response: httpx.Response) -> str | None:
        """Parse the 'next' URL from the Link header."""
        link_header = response.headers.get("link", "")
        if not link_header:
            return None
        match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
        return match.group(1) if match else None


def github_client_for_repo(repo_root: Path) -> GitHubClient:
    """Build ``GitHubClient`` from connected config and/or environment (memory only).

    Uses the same secret sources users already configured: optional
    ``github_token`` on :class:`~avos_cli.models.config.RepoConfig` (file plus
    env overlay from :func:`~avos_cli.config.manager.load_config`, never
    re-persisted here), then ``GITHUB_TOKEN`` after layered ``.env`` load.

    Args:
        repo_root: Git root containing ``.avos/config.json`` when connected.

    Returns:
        Authenticated client.

    Raises:
        AuthError: If no non-empty token is available.
    """
    from avos_cli.config.manager import load_config

    try:
        cfg = load_config(repo_root)
    except ConfigurationNotInitializedError:
        return GitHubClient()
    if cfg.github_token is not None:
        token_value = cfg.github_token.get_secret_value().strip()
        if token_value:
            return GitHubClient(token=token_value)
    return GitHubClient()

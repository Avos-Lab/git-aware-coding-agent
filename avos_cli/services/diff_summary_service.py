"""Diff summary service for git diff analysis.

Uses the REPLY_MODEL to summarize git diffs via the git_diff_agent.md
prompt template. Summaries are held in-memory only and discarded after
being injected into artifact content.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from avos_cli.models.diff import DiffResult, DiffStatus
from avos_cli.utils.logger import get_logger

_log = get_logger("diff_summary_service")

_AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"
_GIT_DIFF_AGENT_PATH = _AGENTS_DIR / "git_diff_agent.md"

_MAX_TOKENS = 1500
_TEMPERATURE = 0.1
_REQUEST_TIMEOUT = 60.0


class DiffSummaryService:
    """Summarizes git diffs using REPLY_MODEL via git_diff_agent.md prompt.

    Takes resolved DiffResult objects, sends each diff to the LLM for
    summarization, and returns a mapping of canonical_id to summary string.
    Summaries are in-memory only -- no files written to disk.

    Args:
        api_key: API key for the reply model.
        api_url: Endpoint URL (OpenAI-compatible chat completions).
        model: Model identifier.
    """

    def __init__(self, api_key: str, api_url: str, model: str) -> None:
        self._api_key = api_key
        self._api_url = api_url.rstrip("/")
        self._model = model
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        self._prompt_template: str | None = None

    def summarize_diffs(self, results: list[DiffResult]) -> dict[str, str]:
        """Summarize resolved diffs using the git_diff_agent prompt.

        Args:
            results: List of DiffResult objects from DiffResolver.

        Returns:
            Dict mapping canonical_id to summary string for each successfully
            summarized diff. Unresolved, suppressed, or failed diffs are skipped.
        """
        summaries: dict[str, str] = {}

        for result in results:
            if result.status != DiffStatus.RESOLVED:
                continue

            if result.diff_text is None or not result.diff_text.strip():
                continue

            summary = self._summarize_single(result.canonical_id, result.diff_text)
            if summary:
                summaries[result.canonical_id] = summary

        return summaries

    def _summarize_single(self, canonical_id: str, diff_text: str) -> str | None:
        """Summarize a single diff via LLM call.

        Args:
            canonical_id: The canonical ID for logging.
            diff_text: The raw git diff text.

        Returns:
            Summary string, or None on failure.
        """
        prompt = self._load_prompt(diff_text)
        if not prompt:
            _log.warning("Failed to load git_diff_agent prompt for %s", canonical_id)
            return None

        try:
            body = {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": _MAX_TOKENS,
                "temperature": _TEMPERATURE,
            }
            response = self._client.post(self._api_url, json=body)
            response.raise_for_status()
            data = response.json()

            choices = data.get("choices", [])
            if not choices:
                _log.warning("Empty choices in response for %s", canonical_id)
                return None

            content = choices[0].get("message", {}).get("content")
            if not content:
                _log.warning("No content in response for %s", canonical_id)
                return None

            return str(content).strip()

        except httpx.HTTPStatusError as e:
            _log.warning("HTTP error summarizing %s: %s", canonical_id, e)
            return None
        except httpx.TimeoutException as e:
            _log.warning("Timeout summarizing %s: %s", canonical_id, e)
            return None
        except Exception as e:
            _log.warning("Error summarizing %s: %s", canonical_id, e)
            return None

    def _load_prompt(self, diff_text: str) -> str:
        """Load and format the git_diff_agent prompt template.

        Args:
            diff_text: The raw git diff to insert into the template.

        Returns:
            Formatted prompt string, or empty string on failure.
        """
        if self._prompt_template is None:
            if not _GIT_DIFF_AGENT_PATH.exists():
                _log.warning("git_diff_agent.md not found at %s", _GIT_DIFF_AGENT_PATH)
                return ""
            self._prompt_template = _GIT_DIFF_AGENT_PATH.read_text(encoding="utf-8")

        return self._prompt_template.format(git_diff=diff_text)

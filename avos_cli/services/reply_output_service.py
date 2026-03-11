"""Reply output service for ask/history command decoration.

Uses a user-configurable model (via env) to produce clean ANSWER/EVIDENCE
(ask) or TIMELINE/SUMMARY (history) output. Falls back to regex-based
dumb formatter when the reply agent is unavailable or fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from avos_cli.utils.logger import get_logger

_log = get_logger("reply_output_service")

_MAX_RAW_CHARS = 24_000
_ASK_MAX_TOKENS = 500
_HISTORY_MAX_TOKENS = 800
_TEMPERATURE = 0.1
_REQUEST_TIMEOUT = 30.0

_AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"
_ASK_PROMPT_PATH = _AGENTS_DIR / "avos_ask_agent.md"
_HISTORY_PROMPT_PATH = _AGENTS_DIR / "avos_history_agent.md"
_ASK_JSON_CONVERTER_PATH = _AGENTS_DIR / "avos_ask_agent_JSON_converter.md"
_HISTORY_JSON_CONVERTER_PATH = _AGENTS_DIR / "avos_hisotry_agent_JSON_converter.md"

_JSON_CONVERTER_MAX_TOKENS = 2000

# Regex patterns for dumb formatter
_PR_NUM = re.compile(r"\[pr:\s*#(\d+)\]", re.IGNORECASE)
_ISSUE_NUM = re.compile(r"\[issue:\s*#(\d+)\]", re.IGNORECASE)
_HASH = re.compile(r"\[hash:\s*([a-f0-9]+)\]", re.IGNORECASE)
_AUTHOR = re.compile(r"\[author:\s*([^\]]+)\]", re.IGNORECASE)
_TITLE = re.compile(r"Title:\s*(.+?)(?:\n|$)", re.DOTALL | re.IGNORECASE)
_MESSAGE = re.compile(r"Message:\s*(.+?)(?:\n|$)", re.DOTALL | re.IGNORECASE)


def _load_prompt(path: Path, **kwargs: str) -> str:
    """Load prompt template from file and substitute placeholders."""
    if not path.exists():
        _log.warning("Prompt file not found: %s", path)
        return ""
    return path.read_text(encoding="utf-8").format(**kwargs)


def _truncate_raw_output(raw_output: str, max_chars: int = _MAX_RAW_CHARS) -> str:
    """Truncate raw output by artifact blocks, keeping top results."""
    if len(raw_output) <= max_chars:
        return raw_output
    artifacts = raw_output.split("---")
    truncated: list[str] = []
    char_count = 0
    for artifact in artifacts:
        block = artifact.strip()
        if not block:
            continue
        if char_count + len(block) + len("---") > max_chars:
            break
        truncated.append(block)
        char_count += len(block) + len("---")
    result = "---".join(truncated)
    if len(raw_output) > len(result):
        result += "\n\n[... additional artifacts truncated]"
    return result


def parse_ask_response(response: str) -> tuple[str, list[str]]:
    """Parse reply agent output for ask mode.

    Returns:
        (answer_text, evidence_lines)
    """
    parts = response.split("EVIDENCE:")
    answer = parts[0].replace("ANSWER:", "").strip()
    evidence: list[str] = []
    if len(parts) > 1:
        for line in parts[1].strip().splitlines():
            line = line.strip()
            if line and line != "(none)":
                evidence.append(line)
    return answer, evidence


def parse_history_response(response: str) -> tuple[str, str]:
    """Parse reply agent output for history mode.

    Returns:
        (timeline_text, summary_text)
    """
    parts = response.split("SUMMARY:")
    timeline = parts[0].replace("TIMELINE:", "").strip()
    summary = parts[1].strip() if len(parts) > 1 else ""
    return timeline, summary


def _truncate_title(s: str, max_len: int = 45) -> str:
    """Truncate title with ... if over max_len."""
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _extract_artifact_refs(block: str) -> list[tuple[str, str, str, str]]:
    """Extract (type, ref, title, author) from artifact block. type is pr, issue, or commit."""
    refs: list[tuple[str, str, str, str]] = []
    author = "unknown"
    for m in _AUTHOR.finditer(block):
        author = m.group(1).strip()
        break

    pr = _PR_NUM.search(block)
    if pr:
        title_m = _TITLE.search(block)
        title = _truncate_title(title_m.group(1) if title_m else "")
        refs.append(("pr", pr.group(1), title, author))

    issue = _ISSUE_NUM.search(block)
    if issue:
        title_m = _TITLE.search(block)
        title = _truncate_title(title_m.group(1) if title_m else "")
        refs.append(("issue", issue.group(1), title, author))

    h = _HASH.search(block)
    if h:
        msg_m = _MESSAGE.search(block)
        msg = _truncate_title(msg_m.group(1) if msg_m else "")
        refs.append(("commit", h.group(1)[:8], msg, author))

    return refs


def _dumb_format_ask(raw_output: str) -> str:
    """Regex-based fallback formatter for ask output. No LLM call."""
    lines: list[str] = []
    seen: set[str] = set()
    for block in raw_output.split("---"):
        for kind, ref, title, author in _extract_artifact_refs(block):
            key = f"{kind}#{ref}"
            if key not in seen and len(lines) < 8:
                seen.add(key)
                if kind == "pr":
                    lines.append(f"PR #{ref} {title} @{author}")
                elif kind == "issue":
                    lines.append(f"Issue #{ref} {title} @{author}")
                else:
                    lines.append(f"Commit {ref} {title} @{author}")
    evidence_str = "\n".join(lines) if lines else "(none)"
    return f"ANSWER:\nTop evidence from repository memory. Review artifacts above for details.\n\nEVIDENCE:\n{evidence_str}"


def _dumb_format_history(raw_output: str) -> str:
    """Regex-based fallback formatter for history output. No LLM call."""
    events: list[str] = []
    seen: set[str] = set()
    for block in raw_output.split("---"):
        for kind, ref, title, author in _extract_artifact_refs(block):
            key = f"{kind}#{ref}"
            if key not in seen and len(events) < 15:
                seen.add(key)
                if kind == "pr":
                    events.append(f"PR #{ref} {title} @{author}")
                elif kind == "issue":
                    events.append(f"Issue #{ref} {title} @{author}")
                else:
                    events.append(f"Commit {ref} {title} @{author}")
    timeline_str = "\n".join(events) if events else "(no relevant history found)"
    return f"TIMELINE:\n{timeline_str}\n\nSUMMARY:\nChronological evidence from repository memory. Review artifacts above for details."


class ReplyOutputService:
    """Decorates ask/history output for clean terminal display.

    Uses a user-configurable reply model (OpenAI-compatible API). If the
    model call fails, falls back to dumb regex-based formatter.

    Args:
        api_key: API key for the reply model.
        api_url: Endpoint URL (e.g. OpenAI-compatible chat completions).
        model: Model identifier.
    """

    def __init__(
        self,
        api_key: str,
        api_url: str,
        model: str,
    ) -> None:
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

    def format_ask(self, question: str, raw_output: str) -> str | None:
        """Format raw artifacts into clean ask output.

        Args:
            question: Developer's question.
            raw_output: Raw artifact content string.

        Returns:
            Formatted ANSWER/EVIDENCE string, or None on failure.
        """
        truncated = _truncate_raw_output(raw_output)
        prompt = _load_prompt(_ASK_PROMPT_PATH, question=question, raw_output=truncated)
        if not prompt:
            return None
        try:
            body = {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": _ASK_MAX_TOKENS,
                "temperature": _TEMPERATURE,
            }
            response = self._client.post(self._api_url, json=body)
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content")
            return content.strip() if content else None
        except Exception as e:
            _log.warning("Reply model call failed for ask: %s", e)
            return None

    def format_history(self, subject: str, raw_output: str) -> str | None:
        """Format raw artifacts into clean history output.

        Args:
            subject: Subject/topic for timeline.
            raw_output: Raw artifact content string.

        Returns:
            Formatted TIMELINE/SUMMARY string, or None on failure.
        """
        truncated = _truncate_raw_output(raw_output)
        prompt = _load_prompt(_HISTORY_PROMPT_PATH, subject=subject, raw_output=truncated)
        if not prompt:
            return None
        try:
            body = {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": _HISTORY_MAX_TOKENS,
                "temperature": _TEMPERATURE,
            }
            response = self._client.post(self._api_url, json=body)
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content")
            return content.strip() if content else None
        except Exception as e:
            _log.warning("Reply model call failed for history: %s", e)
            return None

    def format_ask_json(self, ask_reply_text: str) -> str | None:
        """Convert ask agent reply text to strict JSON via converter agent.

        Args:
            ask_reply_text: The ANSWER/EVIDENCE text from format_ask or dumb_format_ask.

        Returns:
            JSON string conforming to avos.ask.v1 schema, or None on failure.
        """
        prompt = _load_prompt(_ASK_JSON_CONVERTER_PATH, ask_reply_text=ask_reply_text)
        if not prompt:
            return None
        try:
            body = {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": _JSON_CONVERTER_MAX_TOKENS,
                "temperature": 0.0,
            }
            response = self._client.post(self._api_url, json=body)
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content")
            return content.strip() if content else None
        except Exception as e:
            _log.warning("Reply model call failed for ask JSON converter: %s", e)
            return None

    def format_history_json(self, history_reply_text: str) -> str | None:
        """Convert history agent reply text to strict JSON via converter agent.

        Args:
            history_reply_text: The TIMELINE/SUMMARY text from format_history or dumb_format_history.

        Returns:
            JSON string conforming to avos.history.v1 schema, or None on failure.
        """
        prompt = _load_prompt(_HISTORY_JSON_CONVERTER_PATH, history_reply_text=history_reply_text)
        if not prompt:
            return None
        try:
            body = {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": _JSON_CONVERTER_MAX_TOKENS,
                "temperature": 0.0,
            }
            response = self._client.post(self._api_url, json=body)
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content")
            return content.strip() if content else None
        except Exception as e:
            _log.warning("Reply model call failed for history JSON converter: %s", e)
            return None


def dumb_format_ask(raw_output: str) -> str:
    """Public dumb formatter for ask (used when reply agent fails)."""
    return _dumb_format_ask(raw_output)


def dumb_format_history(raw_output: str) -> str:
    """Public dumb formatter for history (used when reply agent fails)."""
    return _dumb_format_history(raw_output)

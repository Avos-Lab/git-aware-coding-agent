"""Ask command orchestrator for AVOS CLI.

Implements the `avos ask "question"` flow: retrieves relevant memory
artifacts, sanitizes, packs within budget, synthesizes via LLM, validates
citation grounding, and renders answer or deterministic fallback.
"""

from __future__ import annotations

import json as json_module
from pathlib import Path

from avos_cli.config.manager import load_config
from avos_cli.exceptions import (
    AvosError,
    ConfigurationNotInitializedError,
    LLMSynthesisError,
)
from avos_cli.models.query import (
    FallbackReason,
    QueryMode,
    RetrievedArtifact,
    SanitizedArtifact,
    SynthesisRequest,
)
from avos_cli.services.citation_validator import CitationValidator
from avos_cli.services.context_budget_service import ContextBudgetService
from avos_cli.services.llm_client import LLMClient
from avos_cli.services.memory_client import AvosMemoryClient
from avos_cli.services.query_fallback_formatter import QueryFallbackFormatter
from avos_cli.services.reply_output_service import (
    ReplyOutputService,
    dumb_format_ask,
    parse_ask_response,
)
from avos_cli.services.sanitization_service import SanitizationService
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import (
    print_error,
    print_info,
    print_json,
    print_warning,
    render_panel,
    render_table,
)
from avos_cli.utils.sanitization_diagnostics import explain_sanitization_gate

_log = get_logger("commands.ask")

_ASK_K = 10
_ASK_SEARCH_MODE = "semantic"
_MIN_GROUNDED_CITATIONS = 2
_SANITIZATION_CONFIDENCE_THRESHOLD = 70


def _build_raw_output(artifacts: list[SanitizedArtifact]) -> str:
    """Build raw artifact string for reply layer (matches QueryFallbackFormatter format)."""
    lines: list[str] = []
    for art in artifacts:
        lines.append(f"[{art.note_id}] ({art.created_at})\n{art.content}")
        lines.append("---")
    return "\n".join(lines)


def _render_reply_output(
    question: str,
    raw_output: str,
    reply_service: ReplyOutputService | None,
    json_output: bool = False,
    json_merge: dict[str, object] | None = None,
) -> None:
    """Render ask output via reply layer or raw. Used for both success and fallback paths.

    Args:
        question: The user's question.
        raw_output: Raw artifact content string.
        reply_service: Optional reply output service for decorated terminal output.
        json_output: If True, emit JSON via converter agent instead of human UI.
        json_merge: Optional top-level keys merged into successful JSON ``data`` objects.
    """
    if reply_service:
        decorated = reply_service.format_ask(question, raw_output)
        output = decorated if decorated else dumb_format_ask(raw_output)

        if json_output:
            json_str = reply_service.format_ask_json(output)
            if json_str:
                try:
                    parsed = json_module.loads(json_str)
                    if isinstance(parsed, dict) and json_merge:
                        for key, value in json_merge.items():
                            parsed[key] = value
                    print_json(success=True, data=parsed, error=None)
                    return
                except json_module.JSONDecodeError:
                    _log.warning("JSON converter returned invalid JSON")
            print_json(
                success=False,
                data=None,
                error={
                    "code": "JSON_CONVERSION_FAILED",
                    "message": "Failed to convert ask output to JSON",
                    "hint": "Check REPLY_MODEL configuration",
                    "retryable": True,
                },
            )
            return

        answer, evidence = parse_ask_response(output)
        render_panel("Answer", answer, style="success")
        if evidence:
            render_table(
                f"Evidence ({len(evidence)} citations)",
                [("Reference", "")],
                [[line] for line in evidence],
            )
    else:
        if json_output:
            print_json(
                success=False,
                data=None,
                error={
                    "code": "REPLY_SERVICE_UNAVAILABLE",
                    "message": "JSON output requires REPLY_MODEL configuration",
                    "hint": "Set REPLY_MODEL, REPLY_MODEL_URL, REPLY_MODEL_API_KEY environment variables",
                    "retryable": False,
                },
            )
            return
        print_info(raw_output)


class AskOrchestrator:
    """Orchestrates the `avos ask` command.

    Pipeline: search -> sanitize -> budget -> synthesize -> ground -> render/fallback.
    Exit codes: 0=success, 1=precondition, 2=hard external error.

    Args:
        memory_client: Avos Memory API client.
        llm_client: LLM synthesis client.
        repo_root: Path to the repository root.
        reply_service: Optional reply output service for decorated terminal output.
    """

    def __init__(
        self,
        memory_client: AvosMemoryClient,
        llm_client: LLMClient,
        repo_root: Path,
        reply_service: ReplyOutputService | None = None,
    ) -> None:
        self._memory = memory_client
        self._llm = llm_client
        self._repo_root = repo_root
        self._reply_service = reply_service
        self._sanitizer = SanitizationService()
        self._budget = ContextBudgetService()
        self._citation_validator = CitationValidator()
        self._fallback_formatter = QueryFallbackFormatter()

    def run(self, repo_slug: str, question: str, json_output: bool = False) -> int:
        """Execute the ask flow.

        Args:
            repo_slug: Repository identifier in 'org/repo' format.
            question: Natural language question from the user.
            json_output: If True, emit JSON output instead of human UI.

        Returns:
            Exit code: 0 (success/fallback), 1 (precondition), 2 (hard error).
        """
        if "/" not in repo_slug:
            if json_output:
                print_json(
                    success=False,
                    data=None,
                    error={
                        "code": "REPOSITORY_CONTEXT_ERROR",
                        "message": "Invalid repo slug. Expected 'org/repo'.",
                        "hint": None,
                        "retryable": False,
                    },
                )
            else:
                print_error("[REPOSITORY_CONTEXT_ERROR] Invalid repo slug. Expected 'org/repo'.")
            return 1

        try:
            config = load_config(self._repo_root)
        except ConfigurationNotInitializedError as e:
            if json_output:
                print_json(
                    success=False,
                    data=None,
                    error={
                        "code": "CONFIG_NOT_INITIALIZED",
                        "message": str(e),
                        "hint": "Run 'avos connect org/repo' first.",
                        "retryable": False,
                    },
                )
            else:
                print_error(f"[CONFIG_NOT_INITIALIZED] {e}")
            return 1
        except AvosError as e:
            if json_output:
                print_json(
                    success=False,
                    data=None,
                    error={
                        "code": e.code,
                        "message": str(e),
                        "hint": getattr(e, "hint", None),
                        "retryable": getattr(e, "retryable", False),
                    },
                )
            else:
                print_error(f"[{e.code}] {e}")
            return 1

        memory_id = config.memory_id

        # Stage 1: Retrieve
        try:
            search_result = self._memory.search(
                memory_id=memory_id, query=question, k=_ASK_K, mode=_ASK_SEARCH_MODE
            )
        except AvosError as e:
            if json_output:
                print_json(
                    success=False,
                    data=None,
                    error={
                        "code": e.code,
                        "message": f"Memory search failed: {e}",
                        "hint": getattr(e, "hint", None),
                        "retryable": getattr(e, "retryable", True),
                    },
                )
            else:
                print_error(f"[{e.code}] Memory search failed: {e}")
            return 2

        # Stage 2: Empty check
        if not search_result.results:
            if json_output:
                print_json(
                    success=True,
                    data={
                        "format": "avos.ask.v1",
                        "raw_text": "",
                        "answer": {"text": "No matching evidence found in repository memory."},
                        "evidence": {"is_none": True, "items": [], "unparsed_lines": []},
                        "parse_warnings": [],
                    },
                    error=None,
                )
            else:
                print_info(
                    "No matching evidence found in repository memory. Try a different question or ingest more data."
                )
            return 0

        # Convert to internal model
        artifacts = [
            RetrievedArtifact(
                note_id=hit.note_id,
                content=hit.content,
                created_at=hit.created_at,
                rank=hit.rank,
            )
            for hit in search_result.results
        ]

        # Stage 3: Sanitize
        sanitization_result = self._sanitizer.sanitize(artifacts)

        if sanitization_result.confidence_score < _SANITIZATION_CONFIDENCE_THRESHOLD:
            _log.warning(
                "Sanitization confidence %d below threshold %d",
                sanitization_result.confidence_score,
                _SANITIZATION_CONFIDENCE_THRESHOLD,
            )
            fallback_output = self._fallback_formatter.format_ask_fallback(
                sanitization_result.artifacts, FallbackReason.SAFETY_BLOCK
            )
            headline, detail_lines, json_merge = explain_sanitization_gate(
                sanitization_result, _SANITIZATION_CONFIDENCE_THRESHOLD
            )
            if not json_output:
                print_warning(headline)
                for line in detail_lines:
                    print_info(line)
            _render_reply_output(
                question,
                fallback_output,
                self._reply_service,
                json_output,
                json_merge=json_merge,
            )
            return 0

        # Stage 4: Budget pack
        budget_result = self._budget.pack(sanitization_result.artifacts, mode="ask")

        if budget_result.included_count < _MIN_GROUNDED_CITATIONS:
            fallback_output = self._fallback_formatter.format_ask_fallback(
                sanitization_result.artifacts, FallbackReason.BUDGET_EXHAUSTED
            )
            if not json_output:
                print_warning("Insufficient evidence for synthesis.")
            _render_reply_output(question, fallback_output, self._reply_service, json_output)
            return 0

        # Stage 5: Synthesize
        try:
            synthesis_request = SynthesisRequest(
                mode=QueryMode.ASK,
                query=question,
                provider=config.llm.provider,
                model=config.llm.model,
                prompt_template_version="ask_v1",
                artifacts=budget_result.included,
            )
            synthesis_response = self._llm.synthesize(synthesis_request)
        except LLMSynthesisError as e:
            _log.warning("LLM synthesis failed: %s", e)
            fallback_output = self._fallback_formatter.format_ask_fallback(
                sanitization_result.artifacts, FallbackReason.LLM_UNAVAILABLE
            )
            if not json_output:
                print_warning("LLM synthesis unavailable. Showing raw evidence.")
            _render_reply_output(question, fallback_output, self._reply_service, json_output)
            return 0

        # Stage 6: Validate citations
        grounded, dropped, warnings = self._citation_validator.validate(
            synthesis_response.answer_text, budget_result.included
        )

        if len(grounded) < _MIN_GROUNDED_CITATIONS:
            _log.warning(
                "Grounding failed: %d/%d citations grounded",
                len(grounded),
                len(grounded) + len(dropped),
            )
            fallback_output = self._fallback_formatter.format_ask_fallback(
                sanitization_result.artifacts, FallbackReason.GROUNDING_FAILED
            )
            if not json_output:
                print_warning("Citation grounding insufficient. Showing raw evidence.")
            _render_reply_output(question, fallback_output, self._reply_service, json_output)
            return 0

        # Stage 7: Render
        if not json_output:
            for w in warnings:
                print_warning(w)

        if self._reply_service:
            raw_output = _build_raw_output(budget_result.included)
            _render_reply_output(question, raw_output, self._reply_service, json_output)
        else:
            if json_output:
                print_json(
                    success=False,
                    data=None,
                    error={
                        "code": "REPLY_SERVICE_UNAVAILABLE",
                        "message": "JSON output requires REPLY_MODEL configuration",
                        "hint": "Set REPLY_MODEL, REPLY_MODEL_URL, REPLY_MODEL_API_KEY environment variables",
                        "retryable": False,
                    },
                )
                return 0

            answer_text = synthesis_response.answer_text
            try:
                parsed = json_module.loads(answer_text)
                if isinstance(parsed, dict) and "answer" in parsed:
                    answer_text = parsed["answer"]
            except (json_module.JSONDecodeError, TypeError):
                pass

            render_panel("Answer", answer_text, style="success")

            if grounded:
                evidence_rows: list[list[str]] = []
                for cit in grounded:
                    note_id_short = (
                        cit.note_id[:10] + ".." if len(cit.note_id) > 12 else cit.note_id
                    )
                    evidence_rows.append([note_id_short, cit.display_label])
                render_table(
                    f"Evidence ({len(grounded)} citations)",
                    [("Note ID", "dim"), ("Label", "")],
                    evidence_rows,
                )

        return 0

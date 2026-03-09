"""Ask command orchestrator for AVOS CLI.

Implements the `avos ask "question"` flow: retrieves relevant memory
artifacts, sanitizes, packs within budget, synthesizes via LLM, validates
citation grounding, and renders answer or deterministic fallback.
"""

from __future__ import annotations

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
    SynthesisRequest,
)
from avos_cli.services.citation_validator import CitationValidator
from avos_cli.services.context_budget_service import ContextBudgetService
from avos_cli.services.llm_client import LLMClient
from avos_cli.services.memory_client import AvosMemoryClient
from avos_cli.services.query_fallback_formatter import QueryFallbackFormatter
from avos_cli.services.sanitization_service import SanitizationService
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import (
    print_error,
    print_info,
    print_success,
    print_warning,
    render_panel,
    render_table,
)

_log = get_logger("commands.ask")

_ASK_K = 10
_ASK_SEARCH_MODE = "semantic"
_MIN_GROUNDED_CITATIONS = 2
_SANITIZATION_CONFIDENCE_THRESHOLD = 70


class AskOrchestrator:
    """Orchestrates the `avos ask` command.

    Pipeline: search -> sanitize -> budget -> synthesize -> ground -> render/fallback.
    Exit codes: 0=success, 1=precondition, 2=hard external error.

    Args:
        memory_client: Avos Memory API client.
        llm_client: LLM synthesis client.
        repo_root: Path to the repository root.
    """

    def __init__(
        self,
        memory_client: AvosMemoryClient,
        llm_client: LLMClient,
        repo_root: Path,
    ) -> None:
        self._memory = memory_client
        self._llm = llm_client
        self._repo_root = repo_root
        self._sanitizer = SanitizationService()
        self._budget = ContextBudgetService()
        self._citation_validator = CitationValidator()
        self._fallback_formatter = QueryFallbackFormatter()

    def run(self, repo_slug: str, question: str) -> int:
        """Execute the ask flow.

        Args:
            repo_slug: Repository identifier in 'org/repo' format.
            question: Natural language question from the user.

        Returns:
            Exit code: 0 (success/fallback), 1 (precondition), 2 (hard error).
        """
        if "/" not in repo_slug:
            print_error("[REPOSITORY_CONTEXT_ERROR] Invalid repo slug. Expected 'org/repo'.")
            return 1

        try:
            config = load_config(self._repo_root)
        except ConfigurationNotInitializedError as e:
            print_error(f"[CONFIG_NOT_INITIALIZED] {e}")
            return 1
        except AvosError as e:
            print_error(f"[{e.code}] {e}")
            return 1

        memory_id = config.memory_id

        # Stage 1: Retrieve
        try:
            search_result = self._memory.search(
                memory_id=memory_id, query=question, k=_ASK_K, mode=_ASK_SEARCH_MODE
            )
        except AvosError as e:
            print_error(f"[{e.code}] Memory search failed: {e}")
            return 2

        # Stage 2: Empty check
        if not search_result.results:
            print_info("No matching evidence found in repository memory. Try a different question or ingest more data.")
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
            _log.warning("Sanitization confidence %d below threshold %d", sanitization_result.confidence_score, _SANITIZATION_CONFIDENCE_THRESHOLD)
            fallback_output = self._fallback_formatter.format_ask_fallback(
                sanitization_result.artifacts, FallbackReason.SAFETY_BLOCK
            )
            print_warning("Content safety check insufficient for synthesis.")
            print_info(fallback_output)
            return 0

        # Stage 4: Budget pack
        budget_result = self._budget.pack(sanitization_result.artifacts, mode="ask")

        if budget_result.included_count < _MIN_GROUNDED_CITATIONS:
            fallback_output = self._fallback_formatter.format_ask_fallback(
                sanitization_result.artifacts, FallbackReason.BUDGET_EXHAUSTED
            )
            print_warning("Insufficient evidence for synthesis.")
            print_info(fallback_output)
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
            print_warning("LLM synthesis unavailable. Showing raw evidence.")
            print_info(fallback_output)
            return 0

        # Stage 6: Validate citations
        grounded, dropped, warnings = self._citation_validator.validate(
            synthesis_response.answer_text, budget_result.included
        )

        if len(grounded) < _MIN_GROUNDED_CITATIONS:
            _log.warning("Grounding failed: %d/%d citations grounded", len(grounded), len(grounded) + len(dropped))
            fallback_output = self._fallback_formatter.format_ask_fallback(
                sanitization_result.artifacts, FallbackReason.GROUNDING_FAILED
            )
            print_warning("Citation grounding insufficient. Showing raw evidence.")
            print_info(fallback_output)
            return 0

        # Stage 7: Render
        for w in warnings:
            print_warning(w)

        answer_text = synthesis_response.answer_text
        try:
            import json
            parsed = json.loads(answer_text)
            if isinstance(parsed, dict) and "answer" in parsed:
                answer_text = parsed["answer"]
        except (json.JSONDecodeError, TypeError):
            pass

        render_panel("Answer", answer_text, style="success")

        if grounded:
            evidence_rows: list[list[str]] = []
            for cit in grounded:
                note_id_short = cit.note_id[:10] + ".." if len(cit.note_id) > 12 else cit.note_id
                evidence_rows.append([note_id_short, cit.display_label])
            render_table(
                f"Evidence ({len(grounded)} citations)",
                [("Note ID", "dim"), ("Label", "")],
                evidence_rows,
            )

        return 0

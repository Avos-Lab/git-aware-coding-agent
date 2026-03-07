"""History command orchestrator for AVOS CLI.

Implements the `avos history "subject"` flow: retrieves relevant memory
artifacts via hybrid search, sorts chronologically, sanitizes, packs
within budget, synthesizes timeline via LLM, validates citation grounding,
and renders timeline or deterministic chronological fallback.
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
from avos_cli.services.chronology_service import ChronologyService
from avos_cli.services.citation_validator import CitationValidator
from avos_cli.services.context_budget_service import ContextBudgetService
from avos_cli.services.llm_client import LLMClient
from avos_cli.services.memory_client import AvosMemoryClient
from avos_cli.services.query_fallback_formatter import QueryFallbackFormatter
from avos_cli.services.sanitization_service import SanitizationService
from avos_cli.utils.logger import get_logger
from avos_cli.utils.output import print_error, print_info, print_success, print_warning

_log = get_logger("commands.history")

_HISTORY_K = 20
_HISTORY_SEARCH_MODE = "hybrid"
_MIN_GROUNDED_CITATIONS = 2
_SANITIZATION_CONFIDENCE_THRESHOLD = 70


class HistoryOrchestrator:
    """Orchestrates the `avos history` command.

    Pipeline: search -> chronology -> sanitize -> budget -> synthesize -> ground -> render/fallback.
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
        self._chronology = ChronologyService()
        self._sanitizer = SanitizationService()
        self._budget = ContextBudgetService()
        self._citation_validator = CitationValidator()
        self._fallback_formatter = QueryFallbackFormatter()

    def run(self, repo_slug: str, subject: str) -> int:
        """Execute the history flow.

        Args:
            repo_slug: Repository identifier in 'org/repo' format.
            subject: Subject/topic for chronological history.

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

        # Stage 1: Retrieve (hybrid, k=20)
        try:
            search_result = self._memory.search(
                memory_id=memory_id, query=subject, k=_HISTORY_K, mode=_HISTORY_SEARCH_MODE
            )
        except AvosError as e:
            print_error(f"[{e.code}] Memory search failed: {e}")
            return 2

        # Stage 2: Empty check
        if not search_result.results:
            print_info("No matching evidence found in repository memory. Try a different subject or ingest more data.")
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

        # Stage 3: Chronological sort
        sorted_artifacts = self._chronology.sort(artifacts)

        # Stage 4: Sanitize
        sanitization_result = self._sanitizer.sanitize(sorted_artifacts)

        if sanitization_result.confidence_score < _SANITIZATION_CONFIDENCE_THRESHOLD:
            _log.warning("Sanitization confidence %d below threshold %d", sanitization_result.confidence_score, _SANITIZATION_CONFIDENCE_THRESHOLD)
            fallback_output = self._fallback_formatter.format_history_fallback(
                sanitization_result.artifacts, FallbackReason.SAFETY_BLOCK
            )
            print_warning("Content safety check insufficient for synthesis.")
            print_info(fallback_output)
            return 0

        # Stage 5: Budget pack
        budget_result = self._budget.pack(sanitization_result.artifacts, mode="history")

        if budget_result.included_count < _MIN_GROUNDED_CITATIONS:
            fallback_output = self._fallback_formatter.format_history_fallback(
                sanitization_result.artifacts, FallbackReason.BUDGET_EXHAUSTED
            )
            print_warning("Insufficient evidence for synthesis.")
            print_info(fallback_output)
            return 0

        # Stage 6: Synthesize
        try:
            synthesis_request = SynthesisRequest(
                mode=QueryMode.HISTORY,
                query=subject,
                provider=config.llm.provider,
                model=config.llm.model,
                prompt_template_version="history_v1",
                artifacts=budget_result.included,
            )
            synthesis_response = self._llm.synthesize(synthesis_request)
        except LLMSynthesisError as e:
            _log.warning("LLM synthesis failed: %s", e)
            fallback_output = self._fallback_formatter.format_history_fallback(
                sanitization_result.artifacts, FallbackReason.LLM_UNAVAILABLE
            )
            print_warning("LLM synthesis unavailable. Showing chronological evidence.")
            print_info(fallback_output)
            return 0

        # Stage 7: Validate citations
        grounded, dropped, warnings = self._citation_validator.validate(
            synthesis_response.answer_text, budget_result.included
        )

        if len(grounded) < _MIN_GROUNDED_CITATIONS:
            _log.warning("Grounding failed: %d/%d citations grounded", len(grounded), len(grounded) + len(dropped))
            fallback_output = self._fallback_formatter.format_history_fallback(
                sanitization_result.artifacts, FallbackReason.GROUNDING_FAILED
            )
            print_warning("Citation grounding insufficient. Showing chronological evidence.")
            print_info(fallback_output)
            return 0

        # Stage 8: Render
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

        print_success("Timeline:")
        print_info(answer_text)

        if grounded:
            print_info("\nEvidence:")
            for cit in grounded:
                print_info(f"  [{cit.display_label}]")

        return 0

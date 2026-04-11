"""History command orchestrator for AVOS CLI.

Implements the `avos history "subject"` flow: retrieves relevant memory
artifacts via hybrid search, enriches with git diff summaries, sorts
chronologically, sanitizes, packs within budget, synthesizes timeline via LLM,
validates citation grounding, and renders timeline or deterministic
chronological fallback.
"""

from __future__ import annotations

import json as json_module
from pathlib import Path
from typing import TYPE_CHECKING

from avos_cli.config.manager import load_config
from avos_cli.exceptions import (
    AvosError,
    ConfigurationNotInitializedError,
    LLMSynthesisError,
)
from avos_cli.models.api import SearchHit
from avos_cli.models.diff import DiffStatus
from avos_cli.models.query import (
    FallbackReason,
    QueryMode,
    RetrievedArtifact,
    SanitizedArtifact,
    SynthesisRequest,
)
from avos_cli.parsers import ReferenceParser, extract_refs_by_note
from avos_cli.services.chronology_service import ChronologyService
from avos_cli.services.citation_validator import CitationValidator
from avos_cli.services.context_budget_service import ContextBudgetService
from avos_cli.services.diff_resolver import DiffResolver
from avos_cli.services.diff_summary_service import DiffSummaryService
from avos_cli.services.llm_client import LLMClient
from avos_cli.services.memory_client import AvosMemoryClient
from avos_cli.services.query_fallback_formatter import QueryFallbackFormatter
from avos_cli.services.reply_output_service import (
    ReplyOutputService,
    dumb_format_history,
    parse_history_response,
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

if TYPE_CHECKING:
    from avos_cli.services.github_client import GitHubClient

_log = get_logger("commands.history")

_HISTORY_K = 20


def _build_raw_output(artifacts: list[SanitizedArtifact]) -> str:
    """Build raw artifact string for reply layer."""
    lines: list[str] = []
    for art in artifacts:
        lines.append(f"[{art.note_id}] ({art.created_at})\n{art.content}")
        lines.append("---")
    return "\n".join(lines)


def _render_reply_output(
    subject: str,
    raw_output: str,
    reply_service: ReplyOutputService | None,
    json_output: bool = False,
    json_merge: dict[str, object] | None = None,
) -> None:
    """Render history output via reply layer or raw.

    Args:
        subject: The subject/topic for timeline.
        raw_output: Raw artifact content string.
        reply_service: Optional reply output service for decorated terminal output.
        json_output: If True, emit JSON via converter agent instead of human UI.
        json_merge: Optional top-level keys merged into successful JSON ``data`` objects.
    """
    if reply_service:
        decorated = reply_service.format_history(subject, raw_output)
        output = decorated if decorated else dumb_format_history(raw_output)

        if json_output:
            json_str = reply_service.format_history_json(output)
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
                    "message": "Failed to convert history output to JSON",
                    "hint": "Check REPLY_MODEL configuration",
                    "retryable": True,
                },
            )
            return

        timeline, summary = parse_history_response(output)
        render_panel("Timeline", timeline, style="success")
        if summary:
            render_panel("Summary", summary, style="info")
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


_HISTORY_SEARCH_MODE = "hybrid"
_MIN_GROUNDED_CITATIONS = 2
_SANITIZATION_CONFIDENCE_THRESHOLD = 70


class HistoryOrchestrator:
    """Orchestrates the `avos history` command.

    Pipeline: search -> enrich with diffs -> chronology -> sanitize -> budget -> synthesize -> ground -> render/fallback.
    Exit codes: 0=success, 1=precondition, 2=hard external error.

    Args:
        memory_client: Avos Memory API client.
        llm_client: LLM synthesis client.
        repo_root: Path to the repository root.
        reply_service: Optional reply output service for decorated terminal output.
        github_client: Optional GitHub client for diff enrichment.
        diff_summary_service: Optional service for summarizing diffs via LLM.
    """

    def __init__(
        self,
        memory_client: AvosMemoryClient,
        llm_client: LLMClient,
        repo_root: Path,
        reply_service: ReplyOutputService | None = None,
        github_client: GitHubClient | None = None,
        diff_summary_service: DiffSummaryService | None = None,
    ) -> None:
        self._memory = memory_client
        self._llm = llm_client
        self._repo_root = repo_root
        self._reply_service = reply_service
        self._github_client = github_client
        self._diff_summary_service = diff_summary_service
        self._chronology = ChronologyService()
        self._sanitizer = SanitizationService()
        self._budget = ContextBudgetService()
        self._citation_validator = CitationValidator()
        self._fallback_formatter = QueryFallbackFormatter()

    def run(self, repo_slug: str, subject: str, json_output: bool = False) -> int:
        """Execute the history flow.

        Args:
            repo_slug: Repository identifier in 'org/repo' format.
            subject: Subject/topic for chronological history.
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

        # Stage 1: Retrieve (hybrid, k=20)
        try:
            search_result = self._memory.search(
                memory_id=memory_id, query=subject, k=_HISTORY_K, mode=_HISTORY_SEARCH_MODE
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
                        "format": "avos.history.v1",
                        "raw_text": "",
                        "timeline": {
                            "is_empty_history": True,
                            "months": [],
                            "unparsed_timeline_lines": [],
                        },
                        "summary": {"text": f'No engineering history found for "{subject}".'},
                        "parse_warnings": [],
                    },
                    error=None,
                )
            else:
                print_info(
                    "No matching evidence found in repository memory. Try a different subject or ingest more data."
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

        # Stage 2.5: Diff enrichment (graceful skip)
        enriched_artifacts = self._enrich_with_diffs(
            search_result.results, artifacts, repo_slug
        )
        if enriched_artifacts is not None:
            artifacts = enriched_artifacts

        # Stage 3: Chronological sort
        sorted_artifacts = self._chronology.sort(artifacts)

        # Stage 4: Sanitize
        sanitization_result = self._sanitizer.sanitize(sorted_artifacts)

        if sanitization_result.confidence_score < _SANITIZATION_CONFIDENCE_THRESHOLD:
            _log.warning(
                "Sanitization confidence %d below threshold %d",
                sanitization_result.confidence_score,
                _SANITIZATION_CONFIDENCE_THRESHOLD,
            )
            fallback_output = self._fallback_formatter.format_history_fallback(
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
                subject,
                fallback_output,
                self._reply_service,
                json_output,
                json_merge=json_merge,
            )
            return 0

        # Stage 5: Budget pack
        budget_result = self._budget.pack(sanitization_result.artifacts, mode="history")

        if budget_result.included_count < _MIN_GROUNDED_CITATIONS:
            fallback_output = self._fallback_formatter.format_history_fallback(
                sanitization_result.artifacts, FallbackReason.BUDGET_EXHAUSTED
            )
            if not json_output:
                print_warning("Insufficient evidence for synthesis.")
            _render_reply_output(subject, fallback_output, self._reply_service, json_output)
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
            if not json_output:
                print_warning("LLM synthesis unavailable. Showing chronological evidence.")
            _render_reply_output(subject, fallback_output, self._reply_service, json_output)
            return 0

        # Stage 7: Validate citations
        grounded, dropped, warnings = self._citation_validator.validate(
            synthesis_response.answer_text, budget_result.included
        )

        if len(grounded) < _MIN_GROUNDED_CITATIONS:
            _log.warning(
                "Grounding failed: %d/%d citations grounded",
                len(grounded),
                len(grounded) + len(dropped),
            )
            fallback_output = self._fallback_formatter.format_history_fallback(
                sanitization_result.artifacts, FallbackReason.GROUNDING_FAILED
            )
            if not json_output:
                print_warning("Citation grounding insufficient. Showing chronological evidence.")
            _render_reply_output(subject, fallback_output, self._reply_service, json_output)
            return 0

        # Stage 8: Render
        if not json_output:
            for w in warnings:
                print_warning(w)

        if self._reply_service:
            raw_output = _build_raw_output(budget_result.included)
            _render_reply_output(subject, raw_output, self._reply_service, json_output)
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

            render_panel("Timeline", answer_text, style="success")

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

    def _enrich_with_diffs(
        self,
        hits: list[SearchHit],
        artifacts: list[RetrievedArtifact],
        repo_slug: str,
    ) -> list[RetrievedArtifact] | None:
        """Enrich artifacts with git diff summaries.

        Extracts PR/commit references from search hits, fetches diffs via GitHub API,
        summarizes them via the diff summary service, and injects summaries into
        artifact content.

        Args:
            hits: Original search hits from memory API.
            artifacts: Converted RetrievedArtifact list.
            repo_slug: Repository slug for reference resolution.

        Returns:
            Enriched artifacts list, or None if enrichment should be skipped.
        """
        if self._github_client is None or self._diff_summary_service is None:
            _log.debug("Diff enrichment skipped: missing github_client or diff_summary_service")
            return None

        try:
            note_refs_list = extract_refs_by_note(hits)

            all_refs: list[str] = []
            note_id_to_refs: dict[str, list[str]] = {}
            for note_refs in note_refs_list:
                note_id_to_refs[note_refs.note_id] = note_refs.references
                all_refs.extend(note_refs.references)

            if not all_refs:
                _log.debug("No PR/commit references found in artifacts")
                return None

            parser = ReferenceParser()
            parsed_refs = parser.parse_all(all_refs, repo_slug)

            if not parsed_refs:
                _log.debug("No valid references parsed")
                return None

            resolver = DiffResolver(self._github_client)
            diff_results = resolver.resolve(parsed_refs)

            resolved_diffs = [r for r in diff_results if r.status == DiffStatus.RESOLVED]
            if not resolved_diffs:
                _log.debug("No diffs resolved successfully")
                return None

            summaries = self._diff_summary_service.summarize_diffs(resolved_diffs)
            if not summaries:
                _log.debug("No diff summaries generated")
                return None

            canonical_to_summary: dict[str, str] = summaries

            enriched: list[RetrievedArtifact] = []
            for artifact in artifacts:
                refs_for_note = note_id_to_refs.get(artifact.note_id, [])
                summary_parts: list[str] = []

                for ref_str in refs_for_note:
                    parsed = parser.parse(ref_str, repo_slug)
                    if parsed is None:
                        continue
                    for canonical_id, summary in canonical_to_summary.items():
                        if self._ref_matches_canonical(parsed, canonical_id):
                            summary_parts.append(summary)
                            break

                if summary_parts:
                    combined_summary = "\n\n".join(summary_parts)
                    new_content = (
                        f"{artifact.content}\n\n--- Diff Summary ---\n{combined_summary}"
                    )
                    enriched.append(
                        RetrievedArtifact(
                            note_id=artifact.note_id,
                            content=new_content,
                            created_at=artifact.created_at,
                            rank=artifact.rank,
                        )
                    )
                else:
                    enriched.append(artifact)

            return enriched

        except Exception as e:
            _log.warning("Diff enrichment failed: %s", e)
            return None

    def _ref_matches_canonical(self, parsed: object, canonical_id: str) -> bool:
        """Check if a parsed reference matches a canonical ID.

        Args:
            parsed: ParsedReference object.
            canonical_id: Canonical ID like 'PR #123' or full SHA.

        Returns:
            True if the reference matches.
        """
        from avos_cli.models.diff import DiffReferenceType, ParsedReference

        if not isinstance(parsed, ParsedReference):
            return False

        if parsed.reference_type == DiffReferenceType.PR:
            return canonical_id == f"PR #{parsed.raw_id}"
        else:
            return canonical_id.startswith(parsed.raw_id) or parsed.raw_id.startswith(
                canonical_id[:7]
            )

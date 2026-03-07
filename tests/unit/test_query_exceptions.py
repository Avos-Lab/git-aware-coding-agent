"""Tests for Sprint 3 query exception classes and error codes.

Covers new ErrorCode values, exception hierarchy, default messages,
hints, retryable flags, and failure class metadata for query pipeline errors.
"""

from __future__ import annotations

import pytest

from avos_cli.exceptions import (
    AvosError,
    ContextBudgetError,
    ErrorCode,
    GroundingError,
    LLMSynthesisError,
    SanitizationError,
)


class TestNewErrorCodes:
    def test_sanitization_failed_code_exists(self):
        assert ErrorCode.SANITIZATION_FAILED == "SANITIZATION_FAILED"

    def test_grounding_failed_code_exists(self):
        assert ErrorCode.GROUNDING_FAILED == "GROUNDING_FAILED"

    def test_llm_synthesis_error_code_exists(self):
        assert ErrorCode.LLM_SYNTHESIS_ERROR == "LLM_SYNTHESIS_ERROR"

    def test_context_budget_error_code_exists(self):
        assert ErrorCode.CONTEXT_BUDGET_ERROR == "CONTEXT_BUDGET_ERROR"

    def test_query_empty_result_code_exists(self):
        assert ErrorCode.QUERY_EMPTY_RESULT == "QUERY_EMPTY_RESULT"

    def test_all_new_codes_are_strings(self):
        new_codes = [
            ErrorCode.SANITIZATION_FAILED,
            ErrorCode.GROUNDING_FAILED,
            ErrorCode.LLM_SYNTHESIS_ERROR,
            ErrorCode.CONTEXT_BUDGET_ERROR,
            ErrorCode.QUERY_EMPTY_RESULT,
        ]
        for code in new_codes:
            assert isinstance(code.value, str)


class TestSanitizationError:
    def test_inherits_avos_error(self):
        assert issubclass(SanitizationError, AvosError)

    def test_default_message(self):
        exc = SanitizationError("confidence below threshold")
        assert str(exc) == "confidence below threshold"
        assert exc.code == ErrorCode.SANITIZATION_FAILED

    def test_has_hint(self):
        exc = SanitizationError("low confidence")
        assert exc.hint is not None

    def test_not_retryable(self):
        exc = SanitizationError("blocked")
        assert exc.retryable is False

    def test_confidence_score_attribute(self):
        exc = SanitizationError("low confidence", confidence_score=65)
        assert exc.confidence_score == 65

    def test_confidence_score_default_none(self):
        exc = SanitizationError("blocked")
        assert exc.confidence_score is None

    def test_catchable_as_avos_error(self):
        with pytest.raises(AvosError):
            raise SanitizationError("test")


class TestGroundingError:
    def test_inherits_avos_error(self):
        assert issubclass(GroundingError, AvosError)

    def test_default_message(self):
        exc = GroundingError("no grounded citations")
        assert str(exc) == "no grounded citations"
        assert exc.code == ErrorCode.GROUNDING_FAILED

    def test_has_hint(self):
        exc = GroundingError("ungrounded")
        assert exc.hint is not None

    def test_not_retryable(self):
        exc = GroundingError("failed")
        assert exc.retryable is False

    def test_grounded_count_attribute(self):
        exc = GroundingError("below threshold", grounded_count=1, total_count=5)
        assert exc.grounded_count == 1
        assert exc.total_count == 5

    def test_count_defaults(self):
        exc = GroundingError("failed")
        assert exc.grounded_count == 0
        assert exc.total_count == 0


class TestLLMSynthesisError:
    def test_inherits_avos_error(self):
        assert issubclass(LLMSynthesisError, AvosError)

    def test_default_message(self):
        exc = LLMSynthesisError("provider timeout")
        assert str(exc) == "provider timeout"
        assert exc.code == ErrorCode.LLM_SYNTHESIS_ERROR

    def test_has_hint(self):
        exc = LLMSynthesisError("timeout")
        assert exc.hint is not None

    def test_transient_failure(self):
        exc = LLMSynthesisError("timeout", failure_class="transient")
        assert exc.retryable is True
        assert exc.failure_class == "transient"

    def test_non_transient_failure(self):
        exc = LLMSynthesisError("invalid schema", failure_class="non_transient")
        assert exc.retryable is False
        assert exc.failure_class == "non_transient"

    def test_default_failure_class(self):
        exc = LLMSynthesisError("error")
        assert exc.failure_class == "unknown"
        assert exc.retryable is False


class TestContextBudgetError:
    def test_inherits_avos_error(self):
        assert issubclass(ContextBudgetError, AvosError)

    def test_default_message(self):
        exc = ContextBudgetError("below minimum evidence floor")
        assert str(exc) == "below minimum evidence floor"
        assert exc.code == ErrorCode.CONTEXT_BUDGET_ERROR

    def test_has_hint(self):
        exc = ContextBudgetError("insufficient")
        assert exc.hint is not None

    def test_not_retryable(self):
        exc = ContextBudgetError("budget exceeded")
        assert exc.retryable is False

    def test_catchable_as_avos_error(self):
        with pytest.raises(AvosError):
            raise ContextBudgetError("test")

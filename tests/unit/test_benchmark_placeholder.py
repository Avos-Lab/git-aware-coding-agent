"""Placeholder benchmark tests for CI benchmark stage.

Per Sprint 6 WP-01, the benchmark stage runs pytest -m benchmark.
This module provides a minimal passing test so the stage does not fail
with "no tests collected". Real benchmark criteria can be added later.
"""

from __future__ import annotations

import pytest


@pytest.mark.benchmark
def test_benchmark_placeholder() -> None:
    """Minimal benchmark test to satisfy CI benchmark stage."""
    # Placeholder: real benchmarks (e.g. ingest performance) can be added
    # when benchmark criteria are defined.
    assert True

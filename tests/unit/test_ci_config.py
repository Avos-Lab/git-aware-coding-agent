"""Tests for CI workflow configuration.

Validates .github/workflows/ci.yml structure, stage ordering,
and required quality gates per Sprint 6 WP-01.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"

REQUIRED_JOBS = ["lint", "unit", "integration", "contract", "benchmark", "coverage", "secret-scan"]
REQUIRED_TRIGGERS = ["push", "pull_request"]


def _load_ci_yaml() -> dict:
    """Load and parse the CI workflow YAML."""
    if not CI_PATH.exists():
        pytest.skip(f"CI workflow not found at {CI_PATH}")
    content = CI_PATH.read_text()
    return yaml.safe_load(content)


def _get_triggers(data: dict) -> dict:
    """Get the 'on' triggers dict. YAML may parse 'on' as boolean True."""
    return data.get("on", data.get(True, {}))


class TestCIConfigExists:
    """CI workflow file must exist."""

    def test_ci_workflow_file_exists(self) -> None:
        assert CI_PATH.exists(), f"Expected {CI_PATH} to exist"


class TestCIConfigStructure:
    """Validate YAML structure and required keys."""

    def test_yaml_is_valid(self) -> None:
        data = _load_ci_yaml()
        assert isinstance(data, dict)
        assert "name" in data
        assert "jobs" in data
        assert _get_triggers(data), "workflow must have 'on' triggers"

    def test_has_required_jobs(self) -> None:
        data = _load_ci_yaml()
        jobs = data.get("jobs", {})
        for job_name in REQUIRED_JOBS:
            assert job_name in jobs, f"Missing required job: {job_name}"

    def test_triggers_push_and_pull_request(self) -> None:
        data = _load_ci_yaml()
        on = _get_triggers(data)
        for trigger in REQUIRED_TRIGGERS:
            assert trigger in on, f"Missing trigger: {trigger}"

    def test_push_targets_main(self) -> None:
        data = _load_ci_yaml()
        on = _get_triggers(data)
        push = on.get("push", {})
        branches = push.get("branches", []) if isinstance(push, dict) else []
        assert "main" in branches, "push should target main branch"


class TestCIStageOrdering:
    """Validate job dependency chain for staged pipeline."""

    def test_lint_has_no_deps(self) -> None:
        data = _load_ci_yaml()
        lint_job = data.get("jobs", {}).get("lint", {})
        assert "needs" not in lint_job or lint_job.get("needs") == [], (
            "lint should run first with no dependencies"
        )

    def test_unit_needs_lint(self) -> None:
        data = _load_ci_yaml()
        unit_job = data.get("jobs", {}).get("unit", {})
        needs = unit_job.get("needs", [])
        assert "lint" in needs, "unit should depend on lint"

    def test_integration_needs_unit(self) -> None:
        data = _load_ci_yaml()
        integration_job = data.get("jobs", {}).get("integration", {})
        needs = integration_job.get("needs", [])
        assert "unit" in needs, "integration should depend on unit"

    def test_contract_needs_integration(self) -> None:
        data = _load_ci_yaml()
        contract_job = data.get("jobs", {}).get("contract", {})
        needs = contract_job.get("needs", [])
        assert "integration" in needs, "contract should depend on integration"

    def test_benchmark_needs_contract(self) -> None:
        data = _load_ci_yaml()
        benchmark_job = data.get("jobs", {}).get("benchmark", {})
        needs = benchmark_job.get("needs", [])
        assert "contract" in needs, "benchmark should depend on contract"

    def test_coverage_needs_benchmark(self) -> None:
        data = _load_ci_yaml()
        coverage_job = data.get("jobs", {}).get("coverage", {})
        needs = coverage_job.get("needs", [])
        assert "benchmark" in needs, "coverage should depend on benchmark"

    def test_secret_scan_needs_coverage(self) -> None:
        data = _load_ci_yaml()
        secret_job = data.get("jobs", {}).get("secret-scan", {})
        needs = secret_job.get("needs", [])
        assert "coverage" in needs, "secret-scan should depend on coverage"


class TestCIRequiredGates:
    """Validate that each job runs the expected commands."""

    def test_lint_runs_ruff_and_mypy(self) -> None:
        data = _load_ci_yaml()
        steps = data.get("jobs", {}).get("lint", {}).get("steps", [])
        run_commands = [
            s.get("run", "") for s in steps if isinstance(s.get("run"), str)
        ]
        combined = " ".join(run_commands)
        assert "ruff" in combined, "lint should run ruff"
        assert "mypy" in combined, "lint should run mypy"

    def test_unit_runs_pytest_unit(self) -> None:
        data = _load_ci_yaml()
        steps = data.get("jobs", {}).get("unit", {}).get("steps", [])
        run_commands = [
            s.get("run", "") for s in steps if isinstance(s.get("run"), str)
        ]
        combined = " ".join(run_commands)
        assert "pytest" in combined and "tests/unit" in combined, (
            "unit job should run pytest tests/unit"
        )

    def test_contract_runs_pytest_contract_marker(self) -> None:
        data = _load_ci_yaml()
        steps = data.get("jobs", {}).get("contract", {}).get("steps", [])
        run_commands = [
            s.get("run", "") for s in steps if isinstance(s.get("run"), str)
        ]
        combined = " ".join(run_commands)
        assert "pytest" in combined and "contract" in combined, (
            "contract job should run pytest with contract marker"
        )

    def test_coverage_runs_cov(self) -> None:
        data = _load_ci_yaml()
        steps = data.get("jobs", {}).get("coverage", {}).get("steps", [])
        run_commands = [
            s.get("run", "") for s in steps if isinstance(s.get("run"), str)
        ]
        combined = " ".join(run_commands)
        assert "cov" in combined or "coverage" in combined, (
            "coverage job should run coverage"
        )

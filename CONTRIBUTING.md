# Contributing to avos

Thank you for your interest in contributing. This guide covers setup, testing, code style, and the PR process.

## Setup

1. Fork and clone the repository.
2. Create a virtual environment and install in development mode:

   ```bash
   pip install -e ".[dev]"
   ```

3. Set environment variables for full functionality (see [docs/user/README.md](docs/user/README.md)):
   - `AVOS_API_KEY`
   - `GITHUB_TOKEN`
   - `ANTHROPIC_API_KEY` (for `ask` and `history`)

## Running Tests

```bash
# Unit tests
pytest tests/unit/ -x

# Integration tests
pytest tests/integration/ -x

# Contract tests
pytest tests/contract/ -m contract

# All tests with coverage
pytest --cov=avos_cli --cov-report=term-missing
```

Tests must pass before submitting a PR. Coverage should not decrease.

## Code Style

- **Ruff**: Run `ruff check avos_cli tests` and fix any issues.
- **Mypy**: Run `mypy avos_cli` and resolve type errors.
- Follow existing patterns: snake_case for files and functions, type hints on public APIs.

## Pull Request Process

1. Create a branch from `main`.
2. Make your changes. Keep commits focused and messages clear.
3. Run the full test suite and ensure it passes.
4. Run `ruff check` and `mypy`.
5. Open a PR with a clear description of the change.
6. Address review feedback.

### PR Template

When opening a PR, include:

- **Summary**: What does this change do?
- **Motivation**: Why is this change needed?
- **Testing**: How was it tested? Any new tests?

## Release Process

Releases are cut by maintainers. The process includes:

1. Update version in `pyproject.toml` and `avos_cli/__init__.py`.
2. Update `CHANGELOG.md`.
3. Run full CI (lint, unit, integration, contract, coverage, secret scan).
4. Tag the release and publish to PyPI (or TestPyPI for dry runs).

## Questions

Open an issue for questions or discussions.

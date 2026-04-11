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
   - `OPENAI_API_KEY` (default LLM for `ask` and `history`; or `ANTHROPIC_API_KEY` if using Anthropic)

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

Releases are cut by maintainers. The PyPI distribution name is **`git_aware_coding_agent`** (`pip install git_aware_coding_agent`); the import package remains **`avos_cli`** and the CLI command is **`avos`** (all subcommands: `avos connect`, `avos ask`, etc.).

1. Update version in `pyproject.toml` and `avos_cli/__init__.py`.
2. Update `CHANGELOG.md`.
3. Run full CI (lint, unit, integration, contract, coverage, secret scan).
4. **Build locally** (optional sanity check):

   ```bash
   rm -rf dist/ build/
   python -m pip install -U build twine
   python -m build
   python -m twine check dist/*
   ```

5. **Publish via GitHub Actions** (recommended): add **repository** secrets **Settings → Secrets and variables → Actions**: **`PYPI_API_TOKEN`** (required for production) and optionally **`TESTPYPI_API_TOKEN`** (for TestPyPI). Then either:
   - **Actions → Publish → Run workflow** — choose **pypi** (default) or **testpypi**; or
   - **Publish a GitHub Release** — when you publish a release, the same workflow uploads to **PyPI** automatically (no manual run needed for that path).

   PyPI tokens use username **`__token__`** and the token value as the password.

6. **TestPyPI install check** (after TestPyPI upload):

   ```bash
   python -m venv .venv-tptest
   source .venv-tptest/bin/activate
   pip install --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ \
     git_aware_coding_agent==<version>
   avos --version
   ```

7. **Production PyPI**: run the same workflow with target **pypi**, then verify `pip install git_aware_coding_agent`.

8. Tag the release and push the tag (match `pyproject.toml` version), e.g. `git tag v1.0.0 && git push origin v1.0.0`, and create a GitHub Release.

**Local upload** (alternative): `python -m twine upload --repository testpypi dist/*` or `twine upload dist/*` with `TWINE_USERNAME=__token__` and `TWINE_PASSWORD=<api-token>`.

## Questions

Open an issue for questions or discussions.

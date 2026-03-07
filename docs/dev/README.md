# avos Developer Guide

Architecture overview, local setup, and test strategy for contributors.

## Architecture Overview

avos uses a four-layer architecture:

| Layer | Responsibility |
|-------|----------------|
| **L4: CLI Surface** | Typer commands, argument parsing, output formatting |
| **L3: Command Orchestrators** | One orchestrator per command; business logic; no cross-calls |
| **L2: Shared Services** | GitHub client, Git client, Avos Memory client, artifact builders |
| **L1: Avos Memory API** | Closed-source remote API (add, search, delete) |

Orchestrators never call each other. They share data only through the Avos Memory API.

## Local Setup

### Prerequisites

- Python 3.10+
- Git
- AVOS_API_KEY, GITHUB_TOKEN, ANTHROPIC_API_KEY (for full functionality)

### Install in development mode

```bash
git clone <repo-url>
cd avos-dev-cli
pip install -e ".[dev]"
```

### Run the CLI

```bash
avos --version
avos --help
```

## Test Strategy

### Test categories

- **Unit** (`tests/unit/`): Fast, isolated, mocked. Run with `pytest tests/unit/ -x`
- **Integration** (`tests/integration/`): Workflow tests, may use mocks or fixtures
- **Contract** (`tests/contract/`): API boundary validation at HTTP level (respx)
- **CLI** (`tests/cli/`): End-to-end CLI invocation tests

### Running tests

```bash
# All unit tests
pytest tests/unit/ -x

# Contract tests (API boundary)
pytest tests/contract/ -m contract

# With coverage
pytest --cov=avos_cli --cov-report=term-missing
```

### Coverage

Coverage target: 90% (configured in `pyproject.toml`). Some modules are omitted (e.g. `llm_client`, `watcher`) for practical reasons.

## Code Style

- **Ruff**: Linting and formatting. Run `ruff check avos_cli tests`
- **Mypy**: Static typing. Run `mypy avos_cli`

## Project Structure

```
avos_cli/
  cli/          # Typer app and command definitions
  commands/     # Orchestrators (one per command)
  services/     # Shared services (memory, github, git, etc.)
  artifacts/    # Artifact builders
  models/       # Pydantic models
  config/       # Config and state management
  utils/        # Output, logging, hashing, time helpers
tests/
  unit/         # Unit tests
  integration/  # Integration tests
  contract/     # API contract tests
  cli/          # CLI invocation tests
```

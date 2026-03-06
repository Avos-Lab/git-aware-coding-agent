.PHONY: install lint format typecheck test test-cov test-repeat clean

install:
	pip install -e ".[dev]"

lint:
	ruff check avos_cli/ tests/

format:
	ruff format avos_cli/ tests/
	ruff check --fix avos_cli/ tests/

typecheck:
	mypy avos_cli/

test:
	pytest

test-cov:
	pytest --cov=avos_cli --cov-report=term-missing --cov-branch

test-repeat:
	pytest && pytest && pytest

clean:
	rm -rf build/ dist/ *.egg-info .mypy_cache .pytest_cache .coverage htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

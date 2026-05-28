.PHONY: install lint format test audit ci

install:
	uv sync --frozen --group dev

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest

audit:
	uv tool run pip-audit

bandit:
	uv tool run bandit -r . -ll -x ./.venv

ci: install lint test audit bandit

# Development

Use Poetry for local work.

## Setup

```bash
poetry install
```

## Checks

```bash
poetry run ruff check .
poetry run mypy src
poetry run pytest tests --cov=src
```

## Scope

The first implementation focuses on the domain layer and database schema.
UI work should stay separate from model and migration changes.

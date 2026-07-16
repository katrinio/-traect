# Contributing

This repository is a template. The same workflow applies to projects started from it.

## Setup

```bash
poetry install
poetry run pre-commit install
```

## Before a PR

```bash
poetry run ruff check .
poetry run mypy src
poetry run pytest tests --cov=src
```

These checks run in CI on every pull request.

## Style

- Keep business logic in `src/`, not in scripts.
- Add type hints to new code. `mypy` runs in strict mode.
- Add tests for new modules and non-trivial logic.

## PR

- Keep the change small and focused.
- Commit messages on `main` drive the release version. Use [conventional commits](https://www.conventionalcommits.org/): `fix:`, `feat:`, or `feat!:` for breaking changes. See [README.md](README.md#versioning).

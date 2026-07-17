# Contributing

Этот репозиторий — шаблон. Тот же workflow применяется к проектам, созданным на его основе.

## Настройка

```bash
poetry install
poetry run pre-commit install
```

## Перед PR

```bash
poetry run ruff check .
poetry run mypy src
poetry run pytest tests --cov=src
```

Эти проверки запускаются в CI при каждом pull request.

## Стиль

- Бизнес-логику держите в `src/`, а не в скриптах.
- Добавляйте type hints к новому коду. `mypy` работает в strict mode.
- Добавляйте тесты для новых модулей и нетривиальной логики.

## PR

- Делайте изменение небольшим и сфокусированным.
- Коммит-сообщения в `main` определяют версию релиза. Используйте [conventional commits](https://www.conventionalcommits.org/): `fix:`, `feat:` или `feat!:` для breaking changes. См. [README.md](README.md#versioning).

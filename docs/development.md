# Development

Для локальной работы используйте Poetry.

## Настройка

```bash
poetry install
```

## Проверки

```bash
poetry run ruff check .
poetry run mypy src
poetry run pytest tests --cov=src
```

## Область

Текущая реализация сфокусирована на domain layer и схеме базы данных.
Работу над UI следует держать отдельно от изменений модели и миграций.

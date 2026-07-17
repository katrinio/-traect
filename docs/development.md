# Development

Для локальной работы используйте Poetry.

## Настройка

```bash
poetry install
poetry run playwright install chromium
```

## Проверки

```bash
poetry run ruff check .
poetry run mypy src
poetry run pytest tests --cov=src
```

Браузерный smoke-тест входит в общий запуск pytest. Для запуска только пользовательского потока:

```bash
poetry run pytest tests/test_browser_smoke.py -m browser
```

## Область

Текущая реализация сфокусирована на domain layer и схеме базы данных.
Работу над UI следует держать отдельно от изменений модели и миграций.

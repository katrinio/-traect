# Development

Для локальной работы используйте Poetry.

## Настройка

```bash
poetry install
poetry run playwright install chromium
```

Границу ISO-недели задаёт backend. По умолчанию используется `UTC`; для другой серверной timezone задайте, например, `TRAECT_TIMEZONE=Europe/Belgrade`. Frontend получает текущую неделю из API и не вычисляет её по времени браузера.

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

## Структура кода

Backend разделён по уровню ответственности:

- `traect/api/app.py` — WSGI lifecycle, HTTP-ответы и раздача web assets;
- `traect/api/routes.py` — сопоставление HTTP routes с application service;
- `traect/api/serializers.py` — стабильное отображение domain-моделей в API payload;
- `traect/app/service.py` — транзакционные use cases и правила weekly review;
- `traect/app/weekly_audit.py` — read-only проверка legacy weekly data и централизованные safe repair-планы;
- `traect/cli.py` — команды запуска сервера и операционной диагностики;
- `traect/domain/` — ORM-модель и enums без HTTP-представления.

Frontend использует небольшие нативные ES-модули без framework:

- `static/app.js` — единое состояние приложения, навигация и orchestration;
- `static/js/api.js` — HTTP client;
- `static/js/presentation.js` — общие labels и DOM helpers;
- `static/js/current.js`, `timeline.js`, `review.js`, `domains.js`, `setup.js` — отдельные экранные сценарии;
- `static/js/tradeoff.js` — общий read-only weekly trade-off.

Экранный модуль не должен самостоятельно выбирать Workspace или вычислять текущую неделю. Эти данные приходят из `app.js` и backend API. Общая логика выносится только после появления реального повторного использования; абстракции для будущих charts или framework-компонентов заранее не создаются.

Общие frozen-clock и WSGI helpers тестов находятся в `tests/support.py`. Browser helpers остаются рядом со smoke-тестами, поскольку описывают только пользовательский поток.

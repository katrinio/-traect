# -traect

-traect — это weekly attention tracker.

Он помогает увидеть, как ограниченное внимание распределяется между `Domain`, заданными пользователем, с течением времени, чтобы понимать компромиссы, а не пытаться держать всё на максимуме одновременно.

Продуктовые определения, правила weekly review и границы интерпретации данных описаны в [принципах проекта](docs/principles.md).

## Основная идея

Модель намеренно нейтральна:

- `Workspace` группирует одну настройку или контекст.
- `Domain` — переиспользуемая область внимания, например Work, Health или Projects.
- `Week` хранит один еженедельный обзор.
- `WeekDomainState` хранит состояние одного `Domain` в одной `Week`.

Модель данных остаётся нейтральной, чтобы в будущем поддерживать разные типы workspace.

## Что отслеживает приложение

- фокус недели
- чем пришлось пожертвовать
- почему так вышло
- заметки за неделю
- `attention` и `condition` для каждого domain

## Что не входит в первую версию

- задачи
- привычки
- функции календаря
- уведомления
- AI-рекомендации

## Реализованный backend-функционал

Первый рабочий срез уже умеет:

- создавать `Workspace`
- создавать, переименовывать, получать список, менять порядок, архивировать и восстанавливать `Domain`
- создавать или обновлять еженедельный обзор для `Workspace`
- хранить одно состояние на активный domain за неделю
- получать текущую неделю
- получать прошлые недели в обратном хронологическом порядке

## HTTP API

Backend предоставляет небольшой набор HTTP-эндпоинтов:

- `POST /workspaces`
- `GET /workspaces/current`
- `GET /workspaces/{workspace_id}`
- `POST /workspaces/{workspace_id}/domains`
- `GET /workspaces/{workspace_id}/domains`
- `PUT /workspaces/{workspace_id}/domains/order`
- `PATCH /domains/{domain_id}`
- `POST /domains/{domain_id}/archive`
- `POST /domains/{domain_id}/restore`
- `PUT /workspaces/{workspace_id}/weeks/{iso_year}/{iso_week}`
- `GET /workspaces/{workspace_id}/weeks/current`
- `GET /workspaces/{workspace_id}/weeks/current-context`
- `GET /workspaces/{workspace_id}/weeks`
- `GET /workspaces/{workspace_id}/history/focus?reviewed_weeks=12|26|52|all`
- `GET /workspaces/{workspace_id}/history/condition?domain_id={domain_id}&reviewed_weeks=12|26|52|all`
- `GET /workspaces/{workspace_id}/history/trade-offs?reviewed_weeks=12|26|52|all&focus_domain_id={domain_id}&sacrifice_domain_id={domain_id}`
- `GET /health`

## Docker deployment

Сервер читает `TRAECT_HOST` (по умолчанию `127.0.0.1`) и `TRAECT_PORT` (по умолчанию `8000`). Production compose передаёт `0.0.0.0:8000` внутри контейнера, но публикует сервис только на `127.0.0.1:8012` для reverse proxy. SQLite-файл хранится в bind-mounted `./data` как `/data/traect.db`; production timezone — `Europe/Belgrade`.

## Поток экранов

После onboarding приложение работает через четыре основных экрана:

- `Current` — компактный обзор текущей ISO-недели только для чтения
- `History` — журнал сохранённых недельных срезов в обратном хронологическом порядке
- `Patterns` — аналитические вкладки Focus, Condition и Trade-offs
- `Domains` — минимальное управление доменами

`Edit review` открывается из `Current` как отдельный редактор текущего provisional review, но не является основной nav-вкладкой.

`Current` отвечает на один вопрос: что происходит прямо сейчас.

После заголовка недели он показывает сохранённый weekly trade-off: `Main focus`, `What gave way` и, если она указана, причину `Why`. Summary доступен только для чтения и не выводится до сохранения первого review текущей недели.

Он группирует активные `Domain` по фактически полученному attention:

- `Primary focus`
- `Maintained`
- `Paused`

Текущее condition остаётся отдельным понятием и только аннотирует строку domain:

- `Stable`
- `At risk`
- `Critical`

Таким образом распределение внимания и фактическое состояние не смешиваются в одном понятии.

## History

`History` отвечает на вопрос: что происходило в каждую сохранённую неделю.

Для каждой недели он показывает сохранённый weekly trade-off, а затем группирует исторические состояния `Domain` по attention и отдельно обозначает condition. Используются имена и состояния, записанные вместе с той неделей: архивные `Domain` остаются видимыми, а новые `Domain` не добавляются в старые обзоры.

Три последние недели раскрыты по умолчанию. Более старые недели остаются компактными и показывают `Main focus` и то, что уступило ему место; полный сохранённый срез раскрывается по заголовку недели.

History — это хронологический операционный журнал, а не аналитика. Он не выводит причинно-следственные связи, не рассчитывает продуктивность и не делает автоматических выводов.

## Patterns

`Patterns` содержит аналитические вкладки `Focus`, `Condition` и `Trade-offs`. Это описательные агрегации сохранённых weekly reviews, а не рекомендации, score или оценка качества недели.

Детальные правила интерпретации описаны в [принципах проекта](docs/principles.md). То, как агрегации читают persisted history, legacy rows, identity fallback и integrity metadata, описано в [storage](docs/storage.md).

## Lifecycle weekly review

Сохранённый обзор текущей ISO-недели имеет состояние `Provisional` и может редактироваться. После смены ISO-недели он становится `Final` и доступен только для чтения. Lifecycle вычисляется backend по `TRAECT_TIMEZONE` или `UTC` по умолчанию и не хранится отдельным флагом.

Подробная продуктовая семантика lifecycle описана в [принципах](docs/principles.md), storage-поведение — в [storage](docs/storage.md).

## Edit review

`Edit review` фиксирует, что фактически произошло к текущему моменту ISO-недели. Он редактирует только текущий provisional snapshot и не позволяет изменять final review или создавать review для будущей недели.

Он содержит:

- `Attention this week` для каждого активного domain
- `Condition at start` для каждого активного domain
- опциональный контекст domain до 300 символов
- настроенный для Domain `Minimum acceptable level` как read-only контекст рядом с Condition
- один `Main focus`
- `What gave way` и причину trade-off
- заметки недели
- действие сохранения

`Main focus` не хранится отдельным полем. Единственный источник истины — `WeekDomainState.attention == primary_focus`; Current, History и API получают Main focus из этого состояния. В неделе может быть ноль или один такой Domain. Без него нельзя указать `What gave way`, а выбранные Domain должны различаться.

## Единый словарь данных

Канонические поля weekly state — `attention` и `condition`. Их значения и продуктовый смысл описаны в [принципах проекта](docs/principles.md), а соответствие базе/API/frontend — в [storage](docs/storage.md).

## Minimum acceptable level

`minimum_acceptable_level` — необязательное описание приемлемого состояния конкретного `Domain`. Оно показывается как read-only контекст в weekly review и помогает пользователю выбрать `Condition`, но приложение не оценивает его автоматически.

Продуктовый смысл описан в [принципах](docs/principles.md), snapshot-поведение — в [storage](docs/storage.md).

## Аудит исторических недель

Исторические weekly review можно проверить отдельной командой:

```text
poetry run traect audit weekly-data
poetry run traect audit weekly-data --format json
```

Dry-run используется по умолчанию. Полный порядок запуска, backup перед `--fix-safe`, scope-флаги, safe repairs, severities и issue codes описаны в [weekly data audit](docs/weekly-data-audit.md).

## Настройка Workspace

Если база данных пуста, приложение открывает экран настройки.

Он позволяет:

- задать имя `Workspace`
- добавить начальные `Domain`
- удалить `Domain` до сохранения
- изменить порядок `Domain` до сохранения
- создать `Workspace` и начальные `Domain` одним действием

После успешного создания `Workspace` экран настройки исчезает, и приложение переходит на `Current`.

## Управление доменами

Для существующего `Workspace` доступен минимальный экран управления `Domain`.

Он позволяет:

- создать `Domain`
- переименовать `Domain`
- изменить порядок активных `Domain`
- архивировать `Domain`
- восстановить архивный `Domain`

Архивные `Domain` остаются в исторических еженедельных обзорах, но не попадают автоматически в новые еженедельные check-in.

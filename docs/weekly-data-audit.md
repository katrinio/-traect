# Audit legacy weekly data

Weekly review менялся вместе с продуктом: прежние версии использовали другой словарь, отдельное поле focus и менее строгие ограничения. Исторические записи — это пользовательская история, поэтому аудит отделяет проверку от ремонта и не пытается угадывать намерение пользователя.

## Быстрый запуск

Из корня проекта:

```text
poetry run traect audit weekly-data
poetry run traect audit weekly-data --format json
poetry run traect audit weekly-data --fix-safe
```

Команда использует базу из `TRAECT_DATABASE_URL`, а без переменной — `sqlite:///traect.db`. Она не запускает миграции: это позволяет проверить в том числе схему до удаления legacy focus-полей.

Dry-run — поведение по умолчанию. Он только читает данные, печатает найденные проблемы и предлагаемые безопасные repairs. Изменения разрешает только явный флаг `--fix-safe`; общего `--fix` нет.

Дополнительный scope:

```text
poetry run traect audit weekly-data --workspace-id 1
poetry run traect audit weekly-data --iso-year 2026 --iso-week 17
poetry run traect audit weekly-data --workspace-id 1 --iso-year 2026 --iso-week 17
```

`--iso-year` и `--iso-week` всегда передаются вместе.

## Перед `--fix-safe`

Сначала остановите запись в приложение и сделайте резервную копию базы принятым для окружения способом. Для локальной SQLite-базы можно воспользоваться встроенной командой SQLite:

```text
sqlite3 traect.db ".backup 'traect-before-weekly-audit.db'"
sqlite3 traect-before-weekly-audit.db "PRAGMA integrity_check;"
```

Ожидаемый результат второй команды — `ok`. Если `TRAECT_DATABASE_URL` указывает на другой файл или СУБД, используйте соответствующую штатную процедуру backup, не эти команды.

Безопасная последовательность:

1. Создать и проверить backup.
2. Запустить dry-run.
3. Просмотреть все `manual_review` и `fatal`, а также proposed repairs.
4. Запустить `--fix-safe`.
5. Повторить dry-run. Исправленные проблемы должны исчезнуть, неоднозначные — остаться стабильными.

## Что считается безопасным ремонтом

Автоматически применяются только изменения с единственным разумным результатом:

- удаление точной копии `WeekDomainState`, если meaningful-поля совпадают;
- перевод известной legacy-терминологии в канонические значения;
- перенос legacy focus в `attention = primary_focus`, если состояние Domain существует ровно в одном смысле и другого Primary focus нет;
- синхронизация временного legacy focus-поля с единственным каноническим Primary focus;
- удаление полностью идентичной дублирующей Week, если нет внешних таблиц, ссылающихся на Week.

Repair-планы централизованы в слое weekly audit. Они применяются одной транзакцией на Week. Неожиданная ошибка откатывает все repairs этой Week, но не блокирует независимые недели. После применения проводится повторная проверка repair-плана.

Запуск идемпотентен: повторный `--fix-safe` не создаёт дополнительные записи и не применяет уже выполненные repairs.

## Что никогда не исправляется автоматически

- два разных Primary focus;
- конфликтующие дубликаты состояний или недель;
- Primary focus, совпадающий с sacrificed Domain;
- sacrificed Domain без Primary focus или без состояния в snapshot;
- reason без sacrificed Domain — текст сохраняется как возможная значимая история;
- неизвестные attention или condition;
- отсутствующие Domain-ссылки;
- будущие и структурно неполные недели.

Архивный Domain остаётся полноценной исторической ссылкой и не считается отсутствующим. Аудит не переименовывает исторические snapshots, не добавляет в них новые Domain и не удаляет архивные Domain.

## Severities

- `info` — структурно корректный факт, полезный для диагностики;
- `repairable` — найден однозначный safe repair;
- `manual_review` — данные читаются, но смысл нельзя восстановить без решения человека;
- `fatal` — структура или значение не позволяют надёжно интерпретировать запись.

Текст сообщения предназначен человеку. Интеграции и тесты должны опираться на стабильный `code`.

## Stable issue codes

| Code | Значение |
| --- | --- |
| `duplicate_week` | одинаковые координаты Workspace + ISO week встречаются более одного раза |
| `invalid_iso_week` | ISO year/week не образуют допустимую неделю |
| `duplicate_domain_state` | Week содержит повторные состояния одного Domain |
| `multiple_primary_focus` | Week содержит более одного Primary focus |
| `legacy_focus_mismatch` | legacy focus расходится с каноническим attention |
| `legacy_focus_missing_state` | legacy focus не имеет состояния в snapshot |
| `invalid_attention` | attention неизвестен или требует известного terminology mapping |
| `invalid_condition` | condition неизвестен или требует известного terminology mapping |
| `focus_equals_sacrifice` | Primary focus и sacrificed Domain совпадают |
| `sacrifice_missing_state` | sacrificed Domain отсутствует в snapshot |
| `sacrifice_without_focus` | sacrificed Domain указан без Primary focus |
| `reason_without_sacrifice` | reason сохранён без sacrificed Domain |
| `missing_domain_reference` | ссылка указывает на отсутствующую строку Domain |
| `future_week` | legacy Week находится позже текущей ISO-недели |
| `incomplete_snapshot` | обязательный идентификатор или часть схемы отсутствует |
| `invalid_week_dates` | starts/ends не совпадают с ISO-неделей |
| `domain_workspace_mismatch` | Domain и Week принадлежат разным Workspace |

## JSON report и exit code

`--format json` возвращает timestamp, scope без полного database URL, число проверенных недель и состояний, counts по code и severity, issues, proposed/applied/rolled-back repairs и число unresolved manual-review items. Свободный текст notes и sacrifice reason в отчёт и логи не попадает.

Exit code:

- `0` — нет unresolved `manual_review`/`fatal`, repairs не откатывались;
- `1` — остались `manual_review` или `fatal`;
- `2` — хотя бы одна транзакция safe repair была откачена.

JSON-формат подходит для повторяемой диагностики, но findings намеренно не сохраняются в отдельной таблице: для персонального приложения on-demand отчёта достаточно.

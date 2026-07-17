# Storage

Проект хранит данные в SQL-базе через SQLAlchemy.

## Что хранится

- workspaces
- domains
- weeks
- состояния domain по неделям

## Где хранится

Расположение базы данных настраивается вне кодовой базы.
Для локальной разработки Alembic по умолчанию использует `sqlite:///traect.db`, если не задан `TRAECT_DATABASE_URL`.
Тот же `TRAECT_DATABASE_URL` использует команда запуска приложения.

## Поведение

- запись данных приложения идёт через ORM
- при запуске приложение применяет все ожидающие миграции Alembic до начала приёма запросов
- схему также можно обновить явно командой `poetry run alembic upgrade head`
- исторические weekly review проверяются отдельной командой `poetry run traect audit weekly-data`; она не запускает миграции и по умолчанию не изменяет данные
- данные domain не встраиваются в код UI
- Domain хранит необязательный `minimum_acceptable_level` длиной до 500 символов
- недельное состояние хранит канонические колонки `attention` и `condition`; их значения совпадают с Python enum, API и frontend без преобразования
- lifecycle review не хранится в таблице: `Provisional` или `Final` вычисляется по ISO-неделе и серверной timezone
- будущие legacy-записи считаются некорректными; чтение истории сообщает об ошибке и не переписывает и не удаляет их автоматически

## Недельное состояние Domain

- `attention`: `primary_focus`, `maintained`, `paused`
- `condition`: `stable`, `at_risk`, `critical`

Эти измерения независимы. Миграция `0005_unify_product_terminology` сохраняет исторические строки и связи, переводит прежние значения в канонические и останавливается с ошибкой при неизвестном значении.

`minimum_acceptable_level_snapshot` хранит контекст Domain, доступный при последнем сохранении provisional review. Он обновляется только вместе с сохранением этой provisional недели. Final и legacy snapshots не обновляются из текущей Domain-конфигурации; `null` в старой строке является валидным отсутствием исторического контекста.

Миграция `0008_minimum_acceptable_level` добавляет обе nullable-колонки без backfill и не изменяет существующие weekly review.

## Канонический Primary focus

Primary focus представлен исключительно строкой `week_domain_state` с `attention = primary_focus`. В одной неделе допускается ноль или одна такая строка. В таблице `week` нет дублирующих focus-колонок; `main_focus` в API вычисляется из weekly Domain states и не хранится отдельно.

Миграция `0006_canonical_focus_source` переносит однозначные исторические значения в `attention`, отдаёт приоритет уже сохранённому `primary_focus` и удаляет прежние дублирующие колонки. Неоднозначные данные останавливают миграцию для ручной проверки.

## Focus history

Focus history не имеет отдельной таблицы и не хранит кэшированные счётчики. Read-only service выполняет ограниченную агрегацию сохранённых `week` и `week_domain_state`, используя только `attention = primary_focus`. Для последних 12, 26 и 52 выбираются валидные persisted reviews, а не непрерывный календарный диапазон; `all` использует всю валидную историю до текущей ISO-недели.

Недели без focus входят в reviewed-week denominator. Duplicate Week, duplicate Domain state, неизвестный attention и несколько Primary focus исключаются и возвращаются как integrity metadata. Историческая группировка использует Domain ID; архивность берётся из текущей Domain metadata, а имя — из самого свежего focus snapshot. Отсутствующая Domain reference сохраняет событие под стабильным ID и нейтральным именем `Unavailable Domain`.

## Condition history

Condition history использует ту же функцию range parsing и ту же трёхзапросную загрузку `week`, `week_domain_state` и `domain`, но агрегирует каждый Domain отдельно по `WeekDomainState.condition`. Отдельных history-таблиц и кэшированных counters нет, поэтому persisted correction сразу меняет результат.

Для выбранного Domain каждая валидная review-неделя получает machine-readable presence: `recorded`, `absent` или `excluded`. Condition shares делятся на число валидных `recorded` states; coverage делится на число reviews и отдельно показывает snapshots с отсутствующим Domain. Duplicate Week исключается из reviewed range, conflicting duplicate state и неизвестный Condition остаются в sequence как `excluded` с кодом центрального weekly audit.

Историческое имя берётся из самого свежего валидного Domain-state snapshot в диапазоне. Архивность берётся из текущей Domain metadata. Состояние с отсутствующей Domain reference остаётся доступным под исходным ID и fallback-именем `Unavailable Domain`.

## Paused sequences

Paused sequences вычисляются без отдельной таблицы и persistent counters из того же bounded history набора. Единственный источник — `WeekDomainState.attention == paused`. Последовательность продолжают только соседние календарные reviewed weeks с одним валидным состоянием выбранного Domain; другой attention, absent state, пропущенная review-неделя, duplicate/conflicting state или неизвестный attention разрывают её.

Condition, minimum acceptable level, архивность и свободный текст не участвуют в расчёте. Сохранённый provisional snapshot включается, несохранённая форма не включается. Persisted historical correction автоматически меняет текущую, самую длинную и исторические последовательности при следующем чтении.

## Trade-off patterns

Trade-off patterns не имеют отдельной таблицы или persistent counters. Read-only service использует общую трёхзапросную history-загрузку и связывает единственный валидный `attention = primary_focus` с `week.sacrificed_domain_id`. Последние 12, 26 и 52 означают persisted reviewed weeks, `all` — всю валидную историю до текущей ISO-недели; сохранённый provisional snapshot включается.

Пары, sacrifice ranking и оба Domain-centric breakdown группируются по стабильным ID. Имена берутся из weekly Domain-state snapshots, текущая Domain metadata используется только для textual archived/unavailable status и sort order. Missing current Domain reference не стирает читаемую историческую пару, если state сохраняет стабильный ID и snapshot name.

Shares пар и `What gave way` делятся на valid paired weeks. Focus-centric shares делятся на валидные недели конкретного Primary-focus Domain и поэтому сохраняют `focus_without_sacrifice`. Duplicate Week, duplicate state, invalid/multiple focus, sacrifice без focus, self-pair и missing sacrifice state возвращаются как integrity metadata и не попадают в ranking. Свободный `sacrifice_reason` не загружается для агрегации и не анализируется.

## Аудит legacy weekly data

On-demand аудит читает сырые табличные значения, поэтому способен сообщить о неизвестных enum и повреждённых ссылках, которые ORM не может безопасно загрузить. Safe repairs отделены от обнаружения и разрешаются только флагом `--fix-safe`; каждая Week ремонтируется в своей транзакции и повторно проверяется перед commit.

Findings не сохраняются в базе и не показываются в Current или Timeline. JSON-отчёт позволяет вынести их во внешнюю диагностику без новой audit metadata schema. Порядок запуска и полный контракт отчёта описаны в [weekly data audit](weekly-data-audit.md).

## Заметки

Модель намеренно небольшая, чтобы в будущем поддерживать другие типы workspace без переписывания.

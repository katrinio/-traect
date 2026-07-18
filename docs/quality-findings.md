# Code Quality Review: Findings & Enum Reference

Полный каталог качества кода, дубликатов и canonical enum значений из Stage 2.

## Quality Findings матрица

Все 15 находок с классификацией, риском и рекомендациями. Wave 3 уже применена (5 коммитов готовы).

| ID | Название | Category | Severity | Confidence | Статус | Рекомендация |
|----|----------|----------|----------|------------|--------|--------------|
| Q-1 | JS: week-link duplication (4 мест) | Duplication | Medium | High | ✓ Fixed | Extracted to `createTimelineWeekLink` |
| Q-2 | Py: _weeks_are_consecutive duplicates | Duplication | Medium | High | ✓ Fixed | Centralized in `history.py` |
| Q-3 | Py: attention values duplicated ×4 | Duplication | Medium | High | ✓ Fixed | `CANONICAL_ATTENTION_VALUES` from enum |
| Q-4 | Py: lifecycle computed twice | Duplication | Low | High | ✓ Fixed | history: `ReviewLifecycle.*.value` |
| Q-5 | Py: upsert_week load-bearing order uncommented | Documentation | Medium | High | ✓ Fixed | Added why-comments (partial unique index) |
| Q-6 | Py: validate_week_values returns unused | Naming | Low | High | ✓ Fixed | Returns `None` now |
| Q-7 | Py: parse_focus_history_range is shared | Naming | Medium | High | ✓ Fixed | routes uses `parse_reviewed_week_range` |
| Q-8 | JS: state.focusHistory.range is shared | Naming | Low | High | Skipped | Could rename to `state.historyRange` (cosmetic) |
| Q-9 | JS: cache invalidation divergence | Readability | Medium | High | ✓ Fixed | `invalidateHistoryCaches({includeTimeline})` |
| Q-10 | Py: _classify_states vs _classify_attention_states | Duplication | Low | High | ✓ Keep | Intentional structural, do not unify |
| Q-11 | API: unknown-query inconsistent (trade-offs vs focus/condition) | API | Low | High | Pending | **Product decision needed** |
| Q-12 | Py: _normalize_domain_name for workspace | Naming | Low | High | Skipped | Rename to `_normalize_name` (cosmetic) |
| Q-13 | Tests: builder types `dict[str, object]` | Typing | Low | High | Skipped | Fix to `Any` if mypy expands |
| Q-14 | formatPercentage duplication ×3 | Duplication | Medium | High | ✓ Fixed | Extracted to `presentation.js` |
| Q-15 | JS: renderNoPairs dense boolean | Readability | Low | High | Skipped | Extract to named const (cosmetic) |

**Итоги:**
- **1 High** (unused return) — быстро закреплено
- **6 Medium** (дубликаты) — 5 закреплены, 1 pending decision
- **8 Low** (читаемость) — 4 закреплены, 4 skipped (cosmetic)
- **Wave 3 готов:** 5 коммитов, все тесты pass (127 non-browser + 38 browser)

---

## Дубликаты: что устранено

| Что | Было | Стало | Статус |
|-----|-----|-------|--------|
| Week-link на Timeline | 4 реализации в 4 модулях | 1 в `presentation.js` | ✓ |
| `formatPercentage` | 3 копии в JS | 1 функция | ✓ |
| `formatWeekLabel` | 17 сборок `Week ${w}, ${y}` | 1 функция | ✓ |
| `_weeks_are_consecutive` | В `paused_streaks.py` и `condition_history.py` | Shared в `history.py` | ✓ |
| `_week_reference` / lifecycle | 4 разных вычисления | `week_reference()` + `review_lifecycle()` | ✓ |
| Attention values | Строки в 4 местах | `CANONICAL_ATTENTION_VALUES` enum | ✓ |

---

## Canonical Enum & Terminology Reference

### Attention (Внимание / Фокусировка)

| Концепт | Enum значение | DB значение | UI / API |
|---------|---------------|-------------|----------|
| Primary focus | `primary_focus` | `"primary_focus"` | Primary focus / Основной фокус |
| Maintained | `maintained` | `"maintained"` | Maintained / Поддерживаемо |
| Paused | `paused` | `"paused"` | Paused / На паузе |

**Источник истины:** `DomainAttention` enum (`src/traect/domain/enums.py`)  
**Используется в:** все three history services, service validation, frontend presenters

### Condition (Состояние / Здоровье)

| Концепт | Enum значение | DB значение | UI / API |
|---------|---------------|-------------|----------|
| Stable | `stable` | `"stable"` | 🟢 Stable / Стабильно |
| At risk | `at_risk` | `"at_risk"` | 🟡 At risk / Под угрозой |
| Critical | `critical` | `"critical"` | 🔴 Critical / Критично |

**Источник истины:** `DomainCondition` enum  
**Используется в:** condition history, service validation, frontend presenters

### Lifecycle (Жизненный цикл недели)

| Концепт | Enum значение | API wire | Условие |
|---------|---------------|----------|---------|
| Provisional | `provisional` | `"provisional"` | `(iso_year, iso_week) == current` |
| Final | `final` | `"final"` | `(iso_year, iso_week) != current` |

**Источник истины:** `ReviewLifecycle` enum  
**Используется в:** history aggregations, week responses, frontend lifecycle markers

**Важно:** `history.review_lifecycle()` теперь возвращает `ReviewLifecycle.PROVISIONAL.value` вместо строк — закреплено к enum!

### Internal vs Product copy

| Слой / Контекст | Внутреннее имя | Пользовательское имя | Примечание |
|-----------------|-----------------|---------------------|-----------|
| Weekly review | `sacrificed_domain_id` | "What gave way" | Внутренняя терминология ≠ UI |
| History aggregation | `unavailable: true` | "Unavailable Domain" tag | Domain reference missing |
| Archived Domain | `archived_at is not None` | "Archived" tag | Distinct from unavailable |
| Status in timeline | `lifecycle === "provisional"` | "Provisional" / "Final" | Lifecycle state |

**Консистентность:** internal → product copy трансляция последовательна и документирована.

---

## Позитивные находки (Keep as is)

Паттерны, которые уже хороши:

- ✓ **Range metadata** `{type: "reviewed_weeks", value}` — идентична во всех трёх history endpoints, test-pinned
- ✓ **WSGI error envelope** `{"error": msg}` — единая JSON форма, правильный per-exception статус, no leaked internals
- ✓ **Transaction ownership** в api/app.py — каждый write коммитит/откатывает в одном месте; zero service-level commits
- ✓ **Frontend loader family** — uniform loading/error/retry; две-tier mapper strictness (throw vs issues[]) calibrated по payload risk
- ✓ **Deterministic ordering** — multi-key ranking (count → recency → sort_order → name → id), tests pin порядок
- ✓ **Feature-specific summary denominators** — `focus_share`, `share_of_pairs`, `coverage_share` intentionally разные; имена соответствуют denominators
- ✓ **Week-reference два-shape split** — `week_reference()` (no lifecycle, internal) vs source-week (with lifecycle, linked) justified по использованию

---

## Wave 3 Commit Plan (уже применён)

Все 5 коммитов готовы. Все тесты pass, ничего не сломано.

### 1. `docs: explain focus replacement order in upsert_week`
- **Файлы:** `src/traect/app/service.py`
- **Что:** Why-комментарии к Primary focus demotion, intermediate flush (partial unique index), default states
- **Почему:** Защита load-bearing порядка операций от будущих "оптимизаций"

### 2. `refactor: centralize shared history week helpers`
- **Файлы:** `src/traect/app/history.py`, `paused_streaks.py`, `condition_history.py`, `focus_history.py`, `tradeoff_history.py`
- **Что:** 
  - `week_reference()` → `history.py` (заменить дубликаты)
  - `weeks_are_consecutive()` → `history.py` (заменить дубликаты)
  - `review_lifecycle()` → `history.py` (использовать везде вместо inline)
  - `CANONICAL_ATTENTION_VALUES = frozenset(a.value for a in DomainAttention)` → `history.py`
- **Почему:** Единый источник истины, нет дрейфа в дубликатах

### 3. `refactor: share history presentation helpers`
- **Файлы:** `src/traect/web/static/js/presentation.js`, `focus-history.js`, `condition-history.js`, `tradeoff-history.js`, `timeline.js`
- **Что:** 
  - `formatPercentage()` → `presentation.js`
  - `formatWeekLabel()` → `presentation.js`
  - `createTimelineWeekLink()` → `presentation.js`
- **Почему:** 4→1 реализация ссылки на Timeline, 3→1 percentage formatter, ~15→1 week label

### 4. `refactor: clarify history cache invalidation`
- **Файлы:** `src/traect/web/static/app.js`
- **Что:** 
  - `invalidateHistoryCaches({includeTimeline})` helper function
  - Comment: Timeline renders snapshot names, updates only after review save; history aggregations read current metadata, update on any Domain change
  - `saveReview()` calls with `includeTimeline: true`
  - `refresh()` calls with `includeTimeline: false`
- **Почему:** Правильное различие выглядит как случайная ошибка без комментария

### 5. `refactor: clarify review validation and range parsing`
- **Файлы:** `src/traect/api/routes.py`, `src/traect/app/service.py`
- **Что:**
  - routes использует `parse_reviewed_week_range` (не focus-специфичный alias)
  - `validate_week_values()` возвращает `None` (не unused focus_id)
- **Почему:** Честные контракты — имена и сигнатуры соответствуют действительности

---

## Product decisions (не решены, отложены)

### C-3: Unknown query-parameter policy

**Текущее состояние:**
- `/history/focus`, `/history/condition` — игнорируют неизвестные params
- `/history/trade-offs` — отвергает неизвестные params (400)

**Рекомендация:** uniform tolerant policy (игнорировать все).  
**Обоснование:** меньше ломает клиентов, уже поведение 2 из 3 endpoints.

### C-1: Integrity block envelope

**Текущее состояние:**
- Focus: top-level `excluded_reasons` + `summary.excluded_week_count`
- Condition/Trade-offs: `integrity: {excluded_*_count, excluded_reasons}`

**Рекомендация:** унифицировать на `integrity: {...}` везде.  
**Примечание:** координированное изменение (service + frontend + тесты).

---

## Итог Stage 2

| Метрика | Значение |
|---------|----------|
| Total findings | 15 (Q-1...Q-15) |
| Severity: High | 1 |
| Severity: Medium | 6 |
| Severity: Low | 8 |
| Wave 3 fixed | 9 (✓) |
| Pending decisions | 2 (C-3, C-1) |
| Skipped (cosmetic) | 4 |
| Tests pass | 127 non-browser + 38 browser |
| Code quality | High — broad refactoring not justified |

**Вердикт:** Small local cleanup recommended. Все важное уже закреплено в Wave 3.

# -traect: Архитектура и консистентность

Полный обзор слоёв, API контрактов, ошибок и найденных несоответствий после Stage 1–3 review.

## 1. Архитектура системы

Четырёхслойная архитектура с защитной валидацией на каждом уровне.

```
Frontend (JavaScript)
  ↓ mappers, validators, fetch/retry, cache-invalidation
API Routes (WSGI, dispatch)
  ↓ parse params, validate input, call service, serialize
Service (Python, ORM)
  ↓ business logic, validation, transaction ownership, aggregations
Database (SQLite + raw SQL)
  ↓ ORM models, constraints, audit tables, legacy rows
```

**Защита на каждом уровне:**
- Frontend: UX-feedback (error states, Retry)
- Backend: correctness (ValidationError, NotFoundError, ConflictError)
- Database: integrity constraints (partial unique index, foreign keys)
- Audit: legacy detection (WeeklyIssueCode codes, repair engine)
- **Не удаляется!** Это intentional defense in depth.

---

## 2. API Endpoints матрица

### Write операции

| Метод | Путь | Request | Success (200) | Validation (400) | Conflict (409) | Not Found (404) |
|-------|------|---------|---------------|------------------|----------------|-----------------|
| POST | /workspaces | name, domains?[] | workspace | name is required | — | — |
| POST | .../domains | name, level? | domain | name required | — | workspace missing |
| PATCH | /domains/{id} | name?, level? | domain | bad value | — | domain not found |
| PUT | .../weeks/{y}/{w} | states[], sacrifice? | week | invalid state | **final week** | workspace/week missing |
| POST | /domains/{id}/archive | — | domain | — | — | domain not found |

### Read операции (История)

| Endpoint | Query params | Success (200) | Empty | Bad param | Unknown param |
|----------|--------------|---------------|-------|-----------|---------------|
| GET .../history/focus | reviewed_weeks? | focus_payload | zero-summary | 400 | ✓ ignored |
| GET .../history/condition | reviewed_weeks?, domain_id? | condition_payload | zero-summary, history:null | 400 | ✓ ignored |
| GET .../history/trade-offs | reviewed_weeks?, focus_id?, sac_id? | tradeoff_payload | zero-summary | 400 | ⚠️ 400 strict |

**⚠️ C-3 (Product decision):** trade-offs отвергает неизвестные параметры, focus/condition игнорируют.  
**Рекомендация:** uniform tolerant policy для всех трёх.

---

## 3. Обработка ошибок

Унифицированная WSGI трансляция в JSON.

| Тип ошибки | Исключение | HTTP статус | Body | Frontend |
|-----------|-----------|------------|------|----------|
| Validation | `ValidationError` | 400 | `{"error": msg}` | error state + Retry |
| Not found | `NotFoundError` | 404 | `{"error": msg}` | error state (or null for .../current) |
| Conflict (final) | `ConflictError` | 409 | `{"error": msg}` | error state, suggest reload |
| Malformed JSON | `ValidationError` | 400 | `{"error": "invalid JSON"}` | error state |
| Unknown route | `NotFoundError` | 404 | `{"error": "route not found"}` | error state |
| Network | — | — | — | fetch error, Retry |

**✓ Консистентно:** каждая ошибка映射 одному HTTP статусу, единый JSON envelope, no leaked internals.

---

## 4. Найденные несоответствия (Consistency Review, Stage 3)

### C-1: Integrity block shape drift (Medium) — Product decision

**Текущая форма:**
- Focus history: `summary.excluded_week_count` + `excluded_reasons` (top level)
- Condition history: `integrity: {excluded_week_count, excluded_reasons}`
- Trade-off history: `integrity: {excluded_pair_count, excluded_reasons}`

**Проблема:** разные конверты для одного понятия (exclusion/integrity).

**Рекомендация:** унифицировать на `integrity: {excluded_*_count, excluded_reasons}` во всех трёх.  
**Внимание:** координированное изменение (service + frontend mapper + тесты вместе).

### C-2: Lifecycle literals anchored to enum ✓ Fixed

| Было | Стало | Статус |
|-----|-------|--------|
| history.py: `"provisional" / "final"` strings | `ReviewLifecycle.PROVISIONAL.value` | ✓ Закреплено |

### C-3: Unknown query-parameter policy (Low) — Product decision needed

| Endpoint | Текущее | Рекомендация |
|----------|---------|-------------|
| /history/focus | игнорирует | tolerant |
| /history/condition | игнорирует | tolerant |
| /history/trade-offs | отвергает 400 | tolerant |

**Рекомендация:** uniform tolerant policy (игнорировать все неизвестные параметры).

### C-4: Focus per-week reference ✓ Fixed

| Было | Стало | Статус |
|-----|-------|--------|
| focus: {domain_id, name, unavailable, name_source} | focus: {domain_id, name, **archived**, unavailable, name_source} | ✓ Aligned |

### C-5: Error-copy capitalization (Low) — Keep as-is

Service: `"domain not found"` (lowercase)  
History: `"Domain has no Condition history…"` (capitalized)

**Статус:** leave as-is (product copy, pinned by tests).

---

## 5. Семантика null / missing / empty / unavailable

Чёткие различия для исторических и текущих состояний (не коллапсируют).

| Состояние | Backend репрезентация | API wire | Frontend |
|-----------|----------------------|----------|----------|
| Omitted field | `.get() / UNSET sentinel` | no key | omits key |
| Explicit null | distinguished from UNSET | `null` | clears in PATCH |
| Empty snapshot + valid ref | `resolve_domain_identity()` → current | `name_source: "current_domain"` | shows current name |
| Empty snapshot + no ref | fallback "Unavailable Domain" | `name_source: "fallback", unavailable: true` | "Unavailable" tag |
| Archived Domain | `archived_at` set, snapshot kept | `archived: true, unavailable: false` | "Archived" tag |
| Missing Domain ref | metadata is None | `unavailable: true` | "Unavailable" tag |
| No saved history | empty selection | zero-summary / `history: null` | calm empty state |
| Empty list | — | `[]` never null | maps over [] |

**✓ Консистентно:** три типа "нет данных" (absent / excluded / unavailable) и три источника имён (snapshot / current_domain / fallback) сохранены без коллапса.

---

## 6. Позитивные находки (Keep as is)

Паттерны, которые уже хороши и не должны быть "улучшены":

- **Range metadata** `{type: "reviewed_weeks", value}` — идентична во всех трёх history endpoints, test-pinned
- **WSGI error envelope** `{"error": msg}` — единая JSON форма, правильный per-exception статус
- **Transaction ownership** в api/app.py — каждый write коммитит/откатывает в одном месте
- **Frontend loader family** — uniform loading/error/retry; две-tier mapper strictness (throw vs issues[]) по payload risk
- **Deterministic ordering** — multi-key ranking (count → recency → sort_order → name → id)
- **Feature-specific summary denominators** — intentionally разные имена для разных denominators
- **Week-reference два-shape split** — `week_reference()` (no lifecycle) vs source-week (with lifecycle)

---

## 7. Итоговые выводы

### Баланс
- **Архитектура:** здорова, четыре слоя, защита на каждом уровне
- **API:** консистентные контракты, единая ошибка-трансляция, 200 на create (deliberate)
- **Consistency:** 5 находок, 2 закреплены (C-2, C-4), 1 ожидает product decision (C-3), 1 требует координации (C-1)
- **Null семантика:** строгие различия, без коллапса

### Следующие шаги
1. **Product decision на C-3** — unknown query-parameter policy (tolerant vs strict)
2. **Координированное изменение C-1** — integrity envelope (service + frontend mapper + тесты)
3. **Keep as-is** — все остальные паттерны

### Вердикт Stage 3
**Small internal consistency cleanup recommended** + one product decision (C-3).  
Broad refactoring не оправдан. Архитектура устойчива и готова.

# Data Flow & Processing Pipelines

Визуальный обзор потоков данных через основные компоненты системы.

## Write Flow: Save Weekly Review

```
Frontend (review.js)
  ↓ collectReviewPayload()
  ↓ fetchJSON(PUT /workspaces/{id}/weeks/{y}/{w})
  
API Routes (routes.py: _upsert_week)
  ↓ validate request body
  ↓ parse WeekStateInput[]
  ↓ check query domain_ids
  
Service (service.py: upsert_week)
  ↓ validate_week_values() — membership, enums, uniqueness
  ↓ seed default states if empty
  ↓ PRIMARY_FOCUS demotion loop (crucial order!)
  ↓ session.flush() ← ⚠️ CRITICAL: before new focus written
  ↓ apply new states (create or update)
  
Database (SQLite)
  ↓ constraints: partial unique index on (week_id, domain_id, primary_focus)
  ↓ foreign keys: week → workspace, domain → workspace
  
Frontend (app.js)
  ↓ invalidateHistoryCaches({ includeTimeline: true })
  ↓ reload timeline + all history tabs
  ↓ renderTimeline() + 3x history renderers
```

**Critical order:**
1. Demote old PRIMARY_FOCUS → MAINTAINED
2. **FLUSH** (without this, partial unique index fails)
3. Apply new states with new PRIMARY_FOCUS

---

## Read Flow: History Aggregation (Focus history example)

```
Frontend (app.js: loadFocusHistory)
  ↓ fetchJSON(GET /workspaces/{id}/history/focus?reviewed_weeks=all)
  
API Routes (routes.py: GET .../history/focus)
  ↓ parse_reviewed_week_range(range_values[0])
  ↓ call FocusHistoryService(session).aggregate()
  
FocusHistoryService (focus_history.py: aggregate)
  
  [Stage 1: Load raw rows]
  ↓ load_history_rows() → raw SQL
    - SELECT weeks (no ORM!) to allow legacy enum values
    - SELECT states (no ORM!) to read invalid condition/attention
    - SELECT domains
  ↓ Row shapes: dict[str, Any] (raw, unchecked)
  
  [Stage 2: Select weeks]
  ↓ Group weeks by (iso_year, iso_week) → "period key"
  ↓ Filter periods by current_iso_week (chronological)
  ↓ Limit to reviewed_weeks count
  ↓ Build excluded_reasons Counter[str, int]
  
  [Stage 3: Aggregate within weeks]
  ↓ For each selected week:
    - Find primary_focus state (WHERE attention = "primary_focus")
    - Classify: valid/excluded with REASON
    - Append to sequence[]
  
  [Stage 4: Build domain index]
  ↓ For each Domain with focus events:
    - Resolve domain identity (wave-2: snapshot name → current name)
    - Count focus occurrences
    - Calculate focus_share = count / reviewed_week_count
    - Find most_recent_focus week reference
  
  [Stage 5: Ranking]
  ↓ Sort by: (-focus_count, -recency_year, -recency_week, sort_order, name.casefold(), domain_id)
  ↓ Build zero_focus_domains list (active but never focused)
  
  [Stage 6: Serialize]
  ↓ Return dict with:
    - range: {"type": "reviewed_weeks", "value": reviewed_weeks}
    - summary: {reviewed_week_count, focused_week_count, no_focus_week_count, excluded_week_count, ...}
    - domains: [{domain_id, name, name_source, archived, unavailable, focus_count, focus_share, most_recent_focus, weeks}, ...]
    - weeks: [{week_id, iso_year, iso_week, lifecycle, focus: {domain_id, name, archived, unavailable, name_source}}, ...]
    - excluded_reasons: {code: count, ...}
    - zero_focus_domains: [{domain_id, name}, ...]
  
Database ← Raw SQL only
  ↓ no ORM — this is intentional
  ↓ Reason: history must tolerate legacy rows with unknown enum values
  ↓ ORM would raise on unknown attention/condition, hiding data quality issues
  ↓ See: app/history.py module docstring

Frontend (focus-history.js: mapFocusHistory)
  ↓ Validate response shape (throw if incomplete)
  ↓ Return payload as-is (pure validation gate)

Frontend (focus-history.js: renderFocusHistory)
  ↓ Check loading state → spinner
  ↓ Check error state → error msg + Retry button
  ↓ Build sections: summary, integrity notice, distribution, zero-focus, sequence
  ↓ Render with formatPercentage(), formatWeekLabel(), createTimelineWeekLink()
  
Browser
  ↓ Render HTML
  ↓ Click week link → scroll to Timeline, open <details>
```

**Key constraints:**
- Raw SQL at history boundary (no ORM on legacy data)
- Deterministic multi-key sorting (tests pin order)
- Chronological selection (newest first, stop at limit)
- Domain identity three-rule fallback (snapshot → current → unavailable)
- No Transaction; read-only service

---

## Lifecycle State Machine

```
               Provisional (same ISO week as current)
                    ↓
                    ↓ (time passes, current week advances)
                    ↓
                   Final (any other ISO week)
                    
Computed, never stored. Used in:
- renderTimeline() — "Provisional" badge on <details>
- history payloads — every week reference includes lifecycle
- frontend: week.lifecycle === "provisional" → unlock Edit button
```

---

## Domain Identity Resolution (wave-2)

Three-rule fallback (used in all three history services via `resolve_domain_identity()`):

```
Input: (metadata: Domain | None, snapshot_name: string | None)

Rule 1: Snapshot name is readable (non-empty, non-whitespace)
        → Return snapshot name as-is
        → name_source: "snapshot"
        → unavailable: true if metadata is None (missing ref)

Rule 2: Snapshot name is empty BUT metadata exists
        → Use current Domain name from metadata
        → name_source: "current_domain"
        → unavailable: false (ref is valid)

Rule 3: No snapshot name AND no metadata
        → Use fallback "Unavailable Domain"
        → name_source: "fallback"
        → unavailable: true (no ref, no name)

Output: {name: str, archived: bool, unavailable: bool, name_source: "snapshot"|"current_domain"|"fallback"}

Guarantees:
- Three distinct name sources are identifiable (frontend can format differently)
- Snapshot names never silently lose readability
- Missing references are explicitly marked unavailable
- Archived vs unavailable are distinct (archived_at vs missing ref)
```

---

## Error Flow

```
User Input (frontend)
  ↓ Frontend validation (quick feedback)
  ↓ fetch(PUT/POST/PATCH)
  
HTTP Request
  ↓ WSGI handler (api/app.py)
  
Application Layer
  ↓ routes.py dispatcher
  ↓ JSON body parse → ValidationError on malformed
  ↓ extract parameters → KeyError/ValueError → mapped to 400
  ↓ validate service call → domain in workspace?
  ↓ call Service
  
Service Layer (app/*.py)
  ↓ raise ValidationError(msg) — user-facing, 400
  ↓ raise NotFoundError(msg) — entity missing, 404
  ↓ raise ConflictError(msg) — state conflict (e.g., final week), 409
  
WSGI Error Handler (api/app.py)
  ↓ catch TraectError subclass → 400/404/409 + {"error": msg}
  ↓ catch built-ins (ValueError, KeyError, etc) → 400 + {"error": "..."}
  ↓ catch unexpected exceptions → 422 + {"error": "..."}
  
HTTP Response
  ↓ JSON body {"error": msg}
  ↓ appropriate status code
  
Frontend (fetchJSON)
  ↓ non-2xx status → throw Error(status)
  ↓ JSON.parse() → throw on malformed
  
Component (history mapper or controller)
  ↓ catch Error → set state.error = true
  ↓ render error state + Retry button
```

**Uniform across all endpoints.**

---

## Weekly Audit & Repair (read-only in this review)

```
CLI: traect audit weekly-data [--fix-safe]

Python (weekly_audit.py: audit_weekly_data)
  
  [Load legacy rows]
  ↓ Raw SQL: SELECT * FROM week + states (allow invalid enums)
  
  [Audit week]
  ↓ Check ISO week valid
  ↓ Check dates consistent
  ↓ Find issues → WeeklyIssueCode list
  
  [Audit states]
  ↓ Check attention in {primary_focus, maintained, paused}
  ↓ Check condition in {stable, at_risk, critical}
  ↓ Check uniqueness (no dup domain per week)
  ↓ Check Primary focus is unique
  ↓ Issue codes: invalid_attention, invalid_condition, duplicate_domain_state, etc.
  
  [Audit legacy focus]
  ↓ Compare legacy focus fields with current WeekDomainState
  ↓ Detect mismatches
  
  [Report]
  ↓ WeeklyAuditReport: {issues[], repairs[]} 
  ↓ Each issue: {code, severity, week_id, domain_id, message}
  
  [--fix-safe: Apply repairs]
  ↓ Repairable issues:
    - drop unknown enum values (mark as repaired)
    - fix invalid dates (mark as repaired)
  ↓ Manual review required:
    - missing domain references
    - conflicting focus/states
  ↓ Exit code: 0 (clean) / 1 (manual review) / 2 (rollback)
```

**Issue codes are shared with history exclusion reasons** (wave-1: `WeeklyIssueCode` enum in `issue_codes.py`).

---

## Cache Invalidation

```
saveReview()
  ↓ PUT /weeks/{y}/{w}
  ↓ invalidateHistoryCaches({ includeTimeline: true })
  ↓ Timeline is cleared (snapshot names changed or new week saved)
  ↓ All three history caches cleared (current Domain metadata might have changed)

refresh() [after domain op]
  ↓ POST /domains/archive or reorder
  ↓ invalidateHistoryCaches({ includeTimeline: false })
  ↓ Timeline NOT cleared (still uses snapshot names saved in weeks, not current Domain state)
  ↓ History caches cleared (they use current archived_at, name, etc.)
```

**Why the difference:**
- Timeline: snapshot names in week table are immutable; renaming Domain doesn't change saved names
- History: `archived_at` and current `name` from Domain table; both change when you archive or rename

**Comment explains this** (wave-3: `invalidateHistoryCaches()` function in app.js).

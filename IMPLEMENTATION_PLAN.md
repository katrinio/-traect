# Weekly Semantics Refactor - Implementation Plan

## Components to implement:

### 1. Database Migration
- ✅ File: `migrations/versions/0009_starting_condition_snapshot.py`
- Makes `condition` nullable
- Adds `starting_condition` column
- Adds check constraint to enforce valid state combinations

### 2. Model Changes
- ✅ Updated: `WeekDomainState.condition` → nullable
- ✅ Added: `WeekDomainState.starting_condition`
- ✅ Updated: `WeekStateInput` with `starting_condition` instead of `condition`

### 3. Service Layer Logic

#### Helper Functions (Added)
- ✅ `_WeekDataState` - state classification constants
- ✅ `_classify_week_domain_state()` - classify single state
- ✅ `_get_week_initialization_state()` - check week consistency

#### Validation Logic to Add in `upsert_week()`

**New validations needed:**
1. **Determine lifecycle**: LEGACY / UNINITIALIZED / INITIALIZED
2. **Atomic initialization check**: if initializing, ALL domains must have starting_condition
3. **Completeness check**: provided domain_ids must match active domains exactly
4. **Immutability check**: if already initialized, starting_condition cannot change
5. **Consistency check**: no mixed states within one week

#### Updated `upsert_week()` signature
```python
def upsert_week(
    self,
    workspace_id: int,
    iso_year: int,
    iso_week: int,
    *,
    sacrificed_domain_id: int | None = None,
    sacrifice_reason: str | None = None,
    notes: str | None = None,
    states: list[WeekStateInput] | None = None,
) -> Week:
```

### 4. API Changes

#### Routes.py changes
- Update `_upsert_week()` to handle new `starting_condition` in payload
- Parse `states[]` with `starting_condition` field instead of `condition`

#### WeekStateInput payload structure
```json
{
  "states": [
    {
      "domain_id": 1,
      "starting_condition": "stable",  // NEW: immutable snapshot
      "attention": "primary_focus",
      "comment": "..."
    }
  ],
  "sacrificed_domain_id": null,
  "notes": "..."
}
```

### 5. Serializers

Update response to send `starting_condition` instead of `condition` for new records:
```python
def week_domain_state_response(state: WeekDomainState):
    # For new initialized records: use starting_condition
    # For legacy records: use condition (marked as legacy)
    # For uninitialized: null
```

### 6. UI Changes (JavaScript)

- Update `review.js`:
  - Change payload structure to send `starting_condition`
  - Show "Condition at start" label
  - After first save: make it read-only
- Update presentation helpers for new label
- Update History/Patterns display

### 7. History & Patterns

- `condition_history.py`: Use `starting_condition` for new, `condition` for legacy
- `focus_history.py`: No changes needed
- `tradeoff_history.py`: No changes needed

### 8. Tests

Required test scenarios:
1. ✅ Atomic initialization - all domains at once
2. ✅ Reject partial initialization
3. ✅ Reject duplicate/unknown domains
4. ✅ Immutability of starting_condition
5. ✅ Mutable attention
6. ✅ Legacy record reading
7. ✅ Detection of mixed/invalid state
8. ✅ FINAL read-only enforcement
9. ✅ Backward compatibility with existing records

## Implementation Status

- [x] Migration file created
- [x] Model updated
- [x] WeekStateInput signature updated
- [x] Helper functions added
- [ ] upsert_week() logic updated
- [ ] API routes updated
- [ ] Serializers updated
- [ ] UI/JS updated
- [ ] History/Patterns updated
- [ ] Tests written
- [ ] Full test suite run

## Next Steps

1. Update `upsert_week()` with complete validation logic
2. Update API routes to parse new payload structure
3. Update serializers
4. Update UI
5. Update History/Patterns
6. Write comprehensive tests
7. Run full test suite

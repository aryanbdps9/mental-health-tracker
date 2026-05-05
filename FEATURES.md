# Features

## Answer intelligence

Related questions across questionnaires are linked. Answering one can pre-fill others.

- PHQ-9 Q9 ("thoughts of flatlining yourself") = "Not at all" → C-SSRS Q1 = "No" → Q2 = "No" → Q3/Q4/Q5 = "No"
- PHQ-9 Q9 = "Nearly every day" → C-SSRS frequency options incompatible with that are dimmed
- All bidirectional - answering C-SSRS updates PHQ-9 too
- All links defined in JSON (`answer_links` in each questionnaire file), not in code
- Cascade uses dirty-set graph propagation - each node processes at most once
- Dependency graph validated for consistency at session start
- Options that would cause a contradiction are visually dimmed (still selectable)
- Selecting a dimmed option shows a contradiction banner with two choices:
  - "Resolve" - clears the conflicting answers elsewhere and re-cascades, keeping auto-fill working
  - "Disable auto-fill" - turns off link intelligence for the rest of the session

## Security

- Password-protected login screen (SHA-256 hashed, httponly session cookie)
- Random port by default (well-known ports blocklisted)
- `Cache-Control: no-store` on all responses
- CSP + X-Frame-Options headers
- Optional auto-shutdown timer
- Binds to 127.0.0.1 only

## Architecture

- Frontend: vanilla JS SPA. All answer state in a single `FlowSession` class
- Backend: Flask serving JSON files. No database. Atomic writes via temp + rename
- Questionnaires, questions, and options all have random 8-char IDs
- Responses store option IDs (not raw values) - the option object carries value, label, and ID separately

## Tests

```
pip install selenium
python app.py --password test123 &
MHT_TEST_PORT=<port> python test_all.py
```

Test suite covers:
- Cascade pre-fill (PHQ-9 Q9 → C-SSRS Q1..Q5)
- Dimmed option triggers contradiction
- Sequential clicks on same question don't contradict
- Resolve clears conflicts and re-cascades
- Graph validation

Requires Edge/Chromium. Tests run headless.

## Plans

1. Reword "daily check-in" to "since last check-in" throughout the app and questionnaire descriptions. The recall period framing should reflect actual usage rather than implying a strict daily obligation.

2. Micro check-in questionnaires: shorter, proportion-based versions of each standard questionnaire designed for frequent logging.
   - Slider question type (0-100% of time since last check-in) for symptoms. Granularity adapts to the gap: ≤24h is near-binary, multi-day shows half-day segments with labels like "About 2 days out of 5 days".
   - Auto-advance only for ≤24h gaps when user clicks exactly on 0% or 100%. Otherwise always show Next + Skip buttons.
   - SI and yes/no questions stay as yes/no.
   - Timeframe banner shows "Reporting on: last 1 day 4 hours" with option to override.
   - Intelligence links use named methods (versioned enum in code, e.g. `"method": "zero_nonzero_v1"`) instead of special value tokens — the constraint spec names the method, code evaluates it. Single source of truth in data.
   - History distinguishes questionnaire type (full / micro).
   - Backward compatible: existing full-questionnaire entries remain unchanged, micro entries stored alongside with a `"micro": true` flag.

3. Reconstruction engine: compute standard questionnaire scores from micro entries.
   - Each micro questionnaire defines a `reconstructs` field naming the target standard questionnaire and a scored mapping method (also a versioned enum).
   - Weighted average over the recall window accounts for uneven gaps (a 3-day gap entry weighs 3x a 1-day entry).
   - This produces the "view" — the score a therapist would see at any point in time.

4. Export: export the current view (filtered history, reconciled summaries, score trends) as a self-describing file with metadata (questionnaire name, date range, scoring method, recall period) in a format readable by both humans and machines. Blocked on reconstruction engine (3).

5. Dependency visualiser/editor: web UI for viewing and editing answer_links as a graph. Changes saved to questionnaire JSON files, require server reboot. Any rules inconsistent with an in-progress or saved draft check-in disable intelligence for that check-in.

6. Android app (data format is already JSON + cloud-sync ready).

# core/normalize.py changelog

Normalization behavior changes are recorded here before their DEV eval
runs (hard rule 6: never change a normalization rule without measuring
its effect and logging why). `eval-dev`/`eval-ci` are not wired yet at
this phase (docs/05_Phase_Plan.md P1), so "DEV eval" for this module
currently means the SROIE hard-set parse-failure rate measured via
`docflow sroie ingest` — the only real-data measurement harness available
until the eval runner lands.

## Entry format

- **Date:**
- **Function / change:**
- **Why (what gap, found how):**
- **Before / after measurement:**
- **Kept or reverted:**

---

## 2026-10-02 — `parse_date`: 2-digit years + dot separator for numeric dates

- **Function / change:** `_NUMERIC_DATE_RE` now accepts a 2-digit year
  (`DD/MM/YY`, `DD-MM-YY`, `DD.MM.YY`) alongside the existing 4-digit
  case, and now accepts `.` as a separator (previously only `/` and `-`
  were matched — the SROIE ingestion task brief had assumed `.` was
  already supported; it was not). A 2-digit year is pivoted per the
  standard convention — `00`-`69` → `2000`-`2069`, `70`-`99` →
  `1970`-`1999` — and flagged `DATE_TWO_DIGIT_YEAR` so downstream
  confidence scoring can see the year was inferred, not printed in full.
  Day/month ambiguity resolution (`DATE_AMBIGUOUS_DAY_MONTH`, day-first
  default) is unchanged and composes with the new flag.
- **Why (what gap, found how):** Found via real-data ingestion, not
  synthetic testing. Running `docflow sroie ingest` against all 973
  SROIE2019 receipts (plan: `docs/superpowers/plans/2026-10-02-sroie-ingest-freeze-verify.md`,
  Task 6) produced a 25.3% parse-failure rate (246/973). Root-causing
  the date failures found 208/245 were pure-numeric 2-digit-year dates
  (`DD/MM/YY`) that `_NUMERIC_DATE_RE` rejected outright (it required
  exactly 4 digits), and 2 more were dot-separated dates rejected for
  the same reason (separator not in the regex at all). This is exactly
  the kind of gap synthetic test fixtures didn't surface: the existing
  property tests never generated a pure-numeric 2-digit-year date, so
  nothing exercised this path before it hit real receipts.
- **Before / after measurement:** Before: 246/973 parse failures (25.3%)
  on the full SROIE hard set. After: re-measured by re-running
  `docflow sroie ingest` from scratch post-fix — see the ingestion
  report pasted in the session that made this change for the actual
  post-fix count and the remaining failure-category breakdown.
- **Kept or reverted:** Kept — reduces a measured, real-data failure
  category; unit and property tests (round-trip over the pivot's
  unambiguous 1970–2069 range) added in
  `tests/unit/core/test_normalize.py` and
  `tests/property/core/test_normalize_property.py`.

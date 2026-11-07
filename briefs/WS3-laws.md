# WS3 — Labor-law dataset (research agent + verifier agent)

**Folder:** `data/laws/` (+ `src/shiftwright_laws/resolver.py`) · **Oversight:** David
**Read first:** `SPEC.md`, `contracts/models.py` (`LawRule`, `LawRuleType`, `LawPack`, `Citation`)

## Goal
A cited, machine-readable dataset of the labor rules that matter for retail hourly scheduling:
federal, all 50 states + DC, and cities with their own scheduling laws. Accuracy beats coverage.
**An entry with no primary or official source is worse than no entry.**

## Scope
- Rule types: exactly the `LawRuleType` enum. Nothing else.
- Jurisdictions: `federal.json`; `states/XX.json` for all 50 + DC; `cities/<state>-<city>.json` for
  cities with their own retail scheduling, break, or minimum-wage rules (e.g. predictive-scheduling
  cities). The research agent builds the city list and records its source in `cities/_index.json`.
- A state with no rule of a given type just has no entry; record that in the file's `notes`
  ("No state meal-break requirement for adults; federal does not require one.").

## Sources (in priority order)
1. Statute or regulation text, or the state labor department's official page.
2. US DOL state-law tables (dol.gov/agencies/whd/state) as a cross-check and index.
3. Reputable secondary sources only to *find* primary sources; never cite them alone.

Each `Citation.excerpt` is a short paraphrase or a ≤25-word quote. `last_verified` = today.
`confidence`: high = primary source read directly; medium = official secondary (DOL tables);
low = anything else (low entries are excluded from solving by default).

## Process
1. **Research agent:** federal first, then TX, CA, then the predictive-scheduling cities, then
   every other state, alphabetically. Commit each file as it's finished; keep `STATUS.md` updated
   with a coverage table (state × rule type).
2. **Verifier agent (separate session, starts at M2):** for a random 20% of entries, plus **all**
   TX, CA, and demo-relevant entries, re-open the citation and confirm params match. Set
   `verified: true` or open an issue in `data/laws/ISSUES.md`. It must not edit entries it didn't verify.

## Resolver
`resolve(jurisdiction) -> LawPack`: merge federal + state + city. Where rules of the same type
conflict, keep the more protective one for the worker (lower OT threshold, longer break, earlier
latest-end for minors...). Keep all citations. Set `coverage` and `warnings` (unknown city →
`state_only` + warning; unknown state → `federal_fallback` + warning).

## Must include
Federal: weekly OT 40h ×1.5; FLSA child-labor rules for ages 14–15 (hours and times, school vs.
non-school weeks); the hazardous-occupation order barring under-18s from operating powered
industrial trucks (`minor_prohibited_roles` with tag `powered_industrial_truck`).

## Acceptance tests
- Every file validates against `LawRule`; every rule has a citation URL and `last_verified`.
- `resolve(TX, austin)` → includes federal OT and minor rules; warnings if Austin has no city file.
- `resolve(CA, None)` → daily OT, meal break, rest break present.
- `resolve(ZZ)` → `federal_fallback` with a warning.

# Contract v1.5: any business, any manager (Tier 1)

*Prompt for the coordinator (OpenCode). Drafted Sat Nov 7 ~00:30 CT by the Claude Code session at David's
request. Contracts are owned by David: implement this, then show him the diff summary before tagging.*

## Goal

Any hourly-workforce manager can cold-start Shiftwright and end up fully covered:
a mom-and-pop who plans on a napkin (chat only, no forecasts) or a big-box store with an hours budget and
corporate forecasts (CSV import). The engine and validator are already industry-neutral (no retail terms in
either). What's retail-shaped is the contract surface around intake, a few enums, tipped pay, and the minor
hazardous-job tags. v1.5 fixes exactly that and nothing more.

Framing for the pitch: **master of one problem** (legal, lowest-cost hourly shift scheduling), not one
industry.

## Rules for this change

- One batch, one version: `CONTRACT_VERSION = "1.5.0"`, tag `contracts-v1.5`. Agents rebase once.
- **Additive only.** Every new field has a default; no renames, no removals. Every existing fixture must
  still load unchanged (version stamp aside), and the Austin/Chicago/Seattle/SF demo stores must solve to
  the same schedule as before. The demo path is frozen.
- Do NOT state law in the contract. The contract defines shapes and tag names; WS3 fills the values from
  primary sources. Docstring examples say "e.g." and carry no numbers that read as law.
- Out of scope (Tier 2, later, separate batch): split shifts / multiple shifts per day, split-shift and
  spread-of-hours premiums, day-of-rest laws, on-call pay. Do not add placeholder fields for them.

## Changes

### 1. Business type (`Store`)

```python
class Sector(str, Enum):
    retail = "retail"
    food = "food"            # restaurants, cafes, QSR, bars, catering
    hospitality = "hospitality"  # hotels, lodging
    other = "other"

class Store(BaseModel):
    ...
    sector: Optional[Sector] = None          # v1.5. For law applicability only.
    business_description: str = ""          # v1.5. Free text from intake, e.g. "family taqueria, 2 locations".
```

SEMANTICS (new #19): a law rule with `applies_to` applies when `applies_to == "both"`, or equals
`Store.sector` (`food` ↔ `food`, `retail` ↔ `retail`). `sector = None` or `other` ⇒ the rule **applies**
(protective default; the readiness check warns "business type not set"). `hospitality` matches
`applies_to` values only when WS3 adds one that names it. WS3 may widen `applies_to` to a list later;
until then it stays `"retail" | "food" | "both"`.

### 2. Events

```python
class EventKind(str, Enum):
    truck = "truck"; floor_set = "floor_set"; promo = "promo"; online_surge = "online_surge"
    delivery = "delivery"            # v1.5: any inbound freight/produce delivery that needs a crew
    private_event = "private_event"  # v1.5: buyouts, parties, banquets
    catering = "catering"            # v1.5
    other = "other"

class Event(BaseModel):
    ...
    label: str = ""   # v1.5. Display name, e.g. "Sysco delivery", "Rehearsal dinner". UI shows label or kind.
```

API.md: the `events` card shows kinds relevant to `Store.sector` first; all kinds stay valid everywhere.

### 3. Demand by individual day (intake, no model change)

`DemandRequirement` already carries `day`; only the intake surface was grouped. API.md changes:

- `department_staffing.peaks[].day_group` accepts: `"all"`, `"weekday"`, `"weekend"`, `"saturday"`,
  `"sunday"`, a single day `"mon"`…`"sun"`, or a comma list `"fri,sat"`. Existing values keep their meaning.
- `coverage_grid.day_type` gains `"custom"`: the card's `days: int[]` is then authoritative.
  `truck_day` is shown only when the store has truck events.
- The server derives day groups from the store's actual hours and events, not from a fixed weekday/Sat/Sun
  split (today: `day_groups()` in `apps/api/src/shiftwright_api/agent/tools.py`).

### 4. Napkin mode (agent-estimated demand)

```python
class DemandSource(str, Enum):
    corporate = "corporate"; leader = "leader"; event = "event"
    estimate = "estimate"   # v1.5: drafted by the agent from the leader's description, confirmed on a card
```

API.md:
- `department_staffing` props gain `rationale: {role_id: string}` (one plain sentence per role saying what
  the suggestion is based on, quoting the leader's words, e.g. "You said Friday nights get slammed").
- A submitted `department_staffing` card saves demand as `source: "leader"` (the leader confirmed it).
  `estimate` is only for demand saved without a card, e.g. a headless/dry-run draft; readiness warns while
  any `estimate` demand exists ("staffing levels are a draft").
- Rule for the agent (prompt, not contract, but list it here): it never invents a forecast number and
  presents it as fact. Every estimate is labeled as a guess and shown for confirmation.

### 5. Tipped pay

```python
class Role(BaseModel):
    ...
    tipped: bool = False   # v1.5. Customer tips are a regular part of pay in this role.

class Employee(BaseModel):
    ...
    tipped_wage_per_hour: Optional[float] = None
    # v1.5. Cash wage for hours in tipped roles. None = wage_per_hour for all hours.

class LawRuleType(str, Enum):
    ...
    tipped_minimum_wage = "tipped_minimum_wage"
    # params: {cash_wage_per_hour: float, max_tip_credit_per_hour: float|null, effective: date}
```

SEMANTICS (new #20, keep it simple and conservative):
- A shift is **tipped** iff every `RoleSegment` is in a role with `tipped=True` and the employee has
  `tipped_wage_per_hour`. Tipped shifts pay `tipped_wage_per_hour` for all paid hours (incl. paid breaks);
  every other shift pays `wage_per_hour`. Mixed-role shifts pay `wage_per_hour` (conservative).
- Overtime premium on any hour = `(multiplier − 1) × wage_per_hour` (overestimates cost on tipped hours,
  never underpays). WS3 may later propose an exact rule.
- `below_minimum_wage` (#15) extends: for an employee with ≥1 tipped shift, `tipped_wage_per_hour` is
  checked against the in-effect `tipped_minimum_wage.cash_wage_per_hour`. **If the law pack has no
  `tipped_minimum_wage` rule, the full `minimum_wage` applies to tipped hours too** (jurisdictions without
  a tip credit simply have no such rule). `wage_per_hour` is still checked against `minimum_wage` as today.
- Resolver: `tipped_minimum_wage` is **exclusive** like `minimum_wage` (keep the single highest cash wage;
  ties → more local).
- Engine and validator compute cost from the same rule; tips themselves are never modeled or estimated.

### 6. Minor hazardous-job tags

```python
# minor_prohibited_roles params gain an optional lower age bound:
#   {age_below: int, age_min: int|null, role_tags: [str]}
#   applies to employees with age_min <= age < age_below (age_min null = no lower bound)

ROLE_TAGS: tuple[str, ...] = (   # v1.5 controlled vocabulary for Role tags used by law rules
    "powered_industrial_truck",
    "meat_slicer",            # power-driven meat processing / slicing machines
    "bakery_machine",         # power-driven bakery mixers, dough machines
    "baler_compactor",        # paper balers, box crushers, trash compactors
    "motor_vehicle_driving",  # driving on public roads (deliveries, errands)
    "cooking",                # cooking and food prep at heat sources
    "fryer",                  # deep fryers / pressure fryers
    "power_saw",              # power-driven saws and cutters
    "ladder_scaffold",        # work from ladders or scaffolds
    "alcohol_service",        # serving or selling alcohol
)
```

- `StoreConfig.role_tags` values must come from `ROLE_TAGS` (validator: unknown tag ⇒ `malformed`, so a
  typo can't silently disable a law). Add a test.
- These are **names only**. WS3 decides from 29 CFR Part 570 and state law which tags each rule bans, at
  what ages, and with which exceptions; any tag no rule references is harmless. If WS3 finds a needed
  hazard the list lacks, it files a request and we add it in a patch release.
- Engine + validator: `minor_prohibited_roles` is already generic; the only change is honoring `age_min`.
- API: the importer/chat auto-tagger (today `apps/api/src/shiftwright_api/equipment.py`, forklifts only)
  extends to every tag, keyword-based, and the agent confirms tags with the leader. Readiness lists tagged
  roles that have minors trained in them.

## Process

1. Pause new contract-dependent work: tell each agent "v1.5 is landing; finish your current slice, commit,
   don't start anything that touches contracts."
2. Edit `contracts/models.py`, `contracts/API.md`, `contracts/SEMANTICS.md` (changelog entry + #19, #20,
   updated #15 and the `minor_prohibited_roles` param doc). Bump to 1.5.0.
3. `make types`; regenerate fixtures that stamp the version (`uv run python -m shiftwright_scenarios.demo`
   and the locality variants); `uv run pytest`; web `npm run build`.
4. Check: every committed fixture loads; each demo store solves to the same schedule and metrics as at
   1.4.0 (compare objective, coverage, hours) — nothing in v1.5 should change them.
5. **Show David the diff summary** (fields added, semantics added). On his OK: commit, tag `contracts-v1.5`,
   push `main`.
6. Notify agents to rebase, with their slice below.

## Follow-up slices per workstream (dispatch after the tag)

- **WS3 laws:** `tipped_minimum_wage` for federal + every state (primary sources; states with no tip credit
  get no rule and a `notes` line saying so); federal child-labor hazardous orders and the 14–15 cooking
  limits mapped to `ROLE_TAGS` with `age_min`/`age_below`; state equivalents for TX, CA, IL, WA first; set
  `applies_to` on every `predictive_scheduling` rule. Coverage table gains the new types.
- **WS1 engine:** tipped pay (#20), `age_min`, `sector`-aware law applicability (#19). Same schedules on all
  existing demo stores.
- **WS2 validator:** the same three, independently; `ROLE_TAGS` check; golden-bad schedules for a tipped
  underpayment and a 15-year-old on a `fryer` role (test-only law values).
- **WS4 scenarios:** one `food` scenario generator path (restaurant roles: server (tipped), bartender
  (tipped, `alcohol_service`), host, line cook (`cooking`, `fryer`), prep (`meat_slicer`), dishwasher;
  lunch and dinner peaks, Fri/Sat heavier; a private event); a `demo_restaurant` fixture (Chicago, so Fair
  Workweek `food` rules apply) with a 15-year-old trained on the fryer. Keep the existing demos byte-identical
  apart from the version stamp.
- **WS6 api:** industry-neutral `core.md`/`onboard.md` (ask what the business is first; set `sector` and
  `business_description`; never assume trucks; napkin flow: describe → drafted `department_staffing` with
  `rationale` → confirm); day groups from actual hours; events card kinds by sector; auto-tagger for all
  `ROLE_TAGS`; CSV-mapping prompt not retail-specific; `restaurant_small` template optional.
- **WS7 web:** business-type question in `store_basics`; per-day staffing (`custom` day groups); event
  `label`; tipped badge on roles and tipped pay in the cost breakdown; tag chips on roles; "draft" marker
  on `estimate` demand.
- **WS5 evals:** add the `food` scenarios to the quick suite once WS4 ships them.

## Done means

`contracts-v1.5` tagged and pushed; all tests green; all four existing demo stores unchanged; a chat-only
cold start for "a 30-seat taqueria in Chicago" reaches `readiness.ready = true` with tipped servers, a
private event, per-day staffing, and the fryer rule blocking a 15-year-old.

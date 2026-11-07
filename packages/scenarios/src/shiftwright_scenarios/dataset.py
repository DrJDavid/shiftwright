"""Test-company datasets: one generated business as the files a manager would bring (PUNCHLIST E4).

    make_dataset(sector, size, difficulty, state, city, seed) -> dict[str, bytes]
        FILES, in this order: the five corporate CSVs (exports.write_exports), README.txt (company,
        location, the manager's narrative to paste into the chat, import order, seed) and
        ANSWER_KEY.txt (everything planted, rendered from Scenario.expected).
    make_dataset_zip(...) -> bytes      the same files in one folder named after the company;
                                        byte-identical for the same arguments.
    dataset_meta(...) -> dict           company_name, folder, narrative, seed, jurisdiction, leader_setup, ...

    uv run python -m shiftwright_scenarios.make_dataset --sector food --size S --difficulty legal_trap \\
        --state IL --city chicago --seed 42 --out <dir>

seed=None picks a random seed; it's returned by dataset_meta and printed in README.txt. To get the
meta and the files for the same random company, call dataset_meta first and pass meta["seed"] on.

The CLI entry point is the make_dataset module; import the functions from here or the package root
(importing the shiftwright_scenarios.make_dataset module rebinds the package's make_dataset name to it).
"""
from __future__ import annotations

import argparse
import io
import json
import random
import re
import tempfile
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Optional

from shiftwright_contracts.models import EventKind, Jurisdiction
from shiftwright_laws import resolve
from shiftwright_laws.resolver import LAWS_DIR, city_slug

from .catalog import DAY_NAMES
from .exports import JOB_CODES, tm_id, write_exports
from .generator import WEEK_START, generate
from .models import Scenario

SECTORS = ("retail", "food")
SIZES = ("S", "M")
DATASET_DIFFICULTIES = ("easy", "normal", "tight", "legal_trap", "messy")
IMPORT_ORDER = ("roster", "training", "availability", "forecast", "history")
FILES = tuple(f"{k}.csv" for k in IMPORT_ORDER) + ("README.txt", "ANSWER_KEY.txt")
# Name-matching import maps every export column except this one (the realistic eval's LLM mapping gets it).
MANUAL_MAPPINGS = {"forecast": {"Req HC": "headcount"}}
MAX_SEED = 999_999
ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def _check(sector, size, difficulty, state, city, seed) -> tuple[Jurisdiction, int]:
    if sector not in SECTORS:
        raise ValueError(f"sector must be one of {', '.join(SECTORS)}; got {sector!r}")
    if size not in SIZES:
        raise ValueError(f"size must be one of {', '.join(SIZES)}; got {size!r}")
    if difficulty not in DATASET_DIFFICULTIES:
        raise ValueError(f"difficulty must be one of {', '.join(DATASET_DIFFICULTIES)}; got {difficulty!r}")
    if not isinstance(state, str) or not state.strip() \
            or not (LAWS_DIR / "states" / f"{state.strip().upper()}.json").is_file():
        raise ValueError(f"state must be a two-letter US state code in data/laws; got {state!r}")
    if city is not None and not isinstance(city, str):
        raise ValueError(f"city must be a string or None; got {city!r}")
    if seed is None:
        seed = random.SystemRandom().randint(1, MAX_SEED)
    elif isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SEED:
        raise ValueError(f"seed must be an integer 0..{MAX_SEED} or None; got {seed!r}")
    slug = city_slug(city.replace("_", " ")) if city and city.strip() else None
    return Jurisdiction(state=state.strip().upper(), city=slug), seed


@lru_cache(maxsize=32)
def _scenario(sector: str, size: str, difficulty: str, state: str, city: Optional[str], seed: int) -> Scenario:
    return generate(seed, size, difficulty, Jurisdiction(state=state, city=city), sector=sector)


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _location(jur: Jurisdiction) -> str:
    return f"{jur.city.replace('-', ' ').title()}, {jur.state}" if jur.city else jur.state


def _base_name(sc: Scenario) -> str:
    # The generator's store name carries "(size/difficulty)"; a test company shouldn't give that away.
    return sc.config.store.name.split(" (")[0]


def _narrative(sc: Scenario) -> str:
    return sc.narrative.replace(sc.config.store.name, _base_name(sc))


def _leader_setup(sc: Scenario, name: str, jur: Jurisdiction) -> dict:
    """What the manager tells the chat that no CSV carries, in import_packs' leader_setup.json shape
    (packs_harness), with role ids as the importer creates them (the lower-cased job codes)."""
    cfg, st = sc.config, sc.config.store
    setup = {
        "template": "empty", "name": name, "jurisdiction": jur.model_dump(), "week_start": st.week_start.isoformat(),
        "timezone": st.timezone, "slot_minutes": st.slot_minutes,
        "hours_by_day": {DAY_NAMES[h.day][:3]: [_hhmm(h.open), _hhmm(h.close)] for h in st.hours},
        "pre_open_minutes": st.pre_open_minutes, "post_close_minutes": st.post_close_minutes,
        "weekly_hours_cap": cfg.budget.weekly_hours_cap,
        "gap_penalty_per_hour": {JOB_CODES[r.id].lower(): r.gap_penalty_per_hour for r in cfg.roles},
        "manual_mappings": MANUAL_MAPPINGS,
    }
    trucks = [e for e in cfg.events if e.kind == EventKind.truck]
    if trucks:
        setup["truck_days"] = {"days": [DAY_NAMES[e.day][:3] for e in trucks],
                               "start": _hhmm(trucks[0].start), "end": _hhmm(trucks[0].end)}
    return setup


def _meta(sector, size, difficulty, state, city, seed) -> tuple[dict, Scenario]:
    jur, seed = _check(sector, size, difficulty, state, city, seed)
    sc = _scenario(sector, size, difficulty, jur.state, jur.city, seed)
    name = f"{_base_name(sc)}, {_location(jur)}"
    meta = {
        "company_name": name,
        "folder": re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-"),
        "sector": sector, "size": size, "difficulty": difficulty, "seed": seed,
        "jurisdiction": jur.model_dump(), "location": _location(jur),
        "law_coverage": resolve(jur, on=WEEK_START).coverage,
        "timezone": sc.config.store.timezone, "week_start": sc.config.store.week_start.isoformat(),
        "narrative": _narrative(sc),
        "import_order": list(IMPORT_ORDER), "files": list(FILES),
        "leader_setup": _leader_setup(sc, name, jur),
    }
    return meta, sc


def dataset_meta(sector: str, size: str, difficulty: str, state: str, city: Optional[str] = None,
                 seed: Optional[int] = None) -> dict:
    """The company's name, folder, narrative and resolved seed (plus leader_setup) without the files."""
    return _meta(sector, size, difficulty, state, city, seed)[0]


def _readme(meta: dict, sc: Scenario) -> str:
    cfg = sc.config
    city = meta["jurisdiction"]["city"]
    law = {"full": "Labor law: federal, state" + (" and city" if city else "") + " rules from the Shiftwright dataset.",
           "state_only": f"Labor law: no city ordinance data for {meta['location']}; state and federal rules apply.",
           "federal_fallback": "Labor law: no state data; only federal rules apply."}[meta["law_coverage"]]
    kind = "restaurant" if meta["sector"] == "food" else "retail store"
    cmd = (f"uv run python -m shiftwright_scenarios.make_dataset --sector {meta['sector']} --size {meta['size']} "
           f"--difficulty {meta['difficulty']} --state {meta['jurisdiction']['state']}"
           + (f" --city {city}" if city else "") + f" --seed {meta['seed']} --out <dir>")
    return "\n".join([
        meta["company_name"],
        "=" * len(meta["company_name"]),
        "",
        f"A synthetic {kind} in {meta['location']} ({meta['timezone']}): {len(cfg.employees)} staff, "
        f"{len(cfg.roles)} roles, schedule week starting {cfg.store.week_start:%a %b %-d, %Y}.",
        "Everyone here is made up. " + law,
        "",
        "1. Create the workplace",
        f"   Name: {meta['company_name']}    Location: {meta['location']}",
        "",
        "2. Paste this into the chat (it's how the manager describes the place; one line):",
        "",
        meta["narrative"],
        "",
        "3. Import the files in this order (training and availability look people up by TM_ID):",
        "   " + " -> ".join(f"{k}.csv" for k in IMPORT_ORDER),
        "   Column notes: TM_ID is the employee ID; Job Code is the role; Req HC on forecast.csv is the",
        "   required headcount; dates are MM/DD/YYYY; DOB gives the age; Avail values are ALL, NOT AVAIL or",
        "   HHMM-HHMM windows separated by ';'; forecast and history times are 12-hour clock.",
        "",
        "ANSWER_KEY.txt lists what was planted. Don't show it to whoever is being tested.",
        "",
        f"Seed: {meta['seed']}",
        f"Regenerate exactly: {cmd}",
        "",
    ])


def _who(sc: Scenario, eid: str) -> str:
    e = next((x for x in sc.config.employees if x.id == eid), None)
    if e is None:
        return eid
    return f"{e.name} (TM_ID {tm_id(eid)}, {eid}, age {e.age}, trained: {', '.join(e.trained_role_ids)})"


def _value(sc: Scenario, k: str, v) -> str:
    if k in ("start", "end", "open", "close") and isinstance(v, int):
        return _hhmm(v)
    if k in ("days", "weekdays") and isinstance(v, list):
        return ", ".join(DAY_NAMES[d] for d in v)
    if (k == "day" or k.endswith("_day")) and isinstance(v, int) and 0 <= v < 7:
        return DAY_NAMES[v]
    if k == "employee_ids":
        return "; ".join(_who(sc, e) for e in v)
    if k == "employee_id":
        return _who(sc, v)
    if k == "hours" and isinstance(v, dict):
        return ", ".join(f"{DAY_NAMES[int(d)][:3]} {_hhmm(o)}-{_hhmm(c)}" for d, (o, c) in sorted(v.items()))
    return v if isinstance(v, str) else json.dumps(v)


def _fact(sc: Scenario, f: dict) -> str:
    rest = ", ".join(f"{k}={_value(sc, k, v)}" for k, v in f.items() if k != "kind")
    return f"{f['kind']}: {rest}" if rest else f["kind"]


def _answer_key(meta: dict, sc: Scenario) -> str:
    ex, cfg = sc.expected, sc.config
    out = [f"ANSWER KEY: {meta['company_name']}",
           f"sector={meta['sector']} size={meta['size']} difficulty={meta['difficulty']} seed={meta['seed']}",
           "Everything below is read from the generator's expected data for this scenario.", ""]

    traps = {k: v for k, v in (ex.get("traps") or {}).items() if k != "notes"}
    if traps:
        out.append("Planted traps:")
        for k, ids in traps.items():
            out.append(f"  {k}:")
            out += [f"    - {_who(sc, e)}" for e in ids]
        if ex["traps"].get("notes"):
            out.append(f"  Notes: {ex['traps']['notes']}")
    else:
        out.append("Planted traps: none")
    out.append("")

    floor = ex.get("minimum_wage")
    if floor is not None:
        low = [e for e in cfg.employees if e.wage_per_hour < floor]
        out.append(f"Minimum wage for this location: ${floor:.2f}/h"
                   + (f"; tipped cash wage ${ex['tipped_cash_wage']:.2f}/h ({ex['tipped_rule_id']})"
                      if ex.get("tipped_cash_wage") is not None else ""))
        out.append("Below the minimum wage: " + ("none" if not low else "; ".join(_who(sc, e.id) for e in low)))
        out.append("")

    out.append("What the narrative leaves out:" if ex.get("narrative_omissions") else "What the narrative leaves out: nothing")
    out += [f"  - {_fact(sc, o)}" for o in ex.get("narrative_omissions") or []]
    out.append("Where the narrative contradicts itself:" if ex.get("narrative_contradictions")
               else "Where the narrative contradicts itself: nowhere")
    for c in ex.get("narrative_contradictions") or []:
        k = {"event": "day", "truck": "days"}.get(c["kind"], c["kind"])
        out.append(f"  - \"{c['statement']}\"  ({c['kind']}: true value {_value(sc, k, c['fact_value'])},"
                   f" stated {_value(sc, k, c['contradicting_value'])})")
    out.append("")

    out.append(f"Infeasible: {'yes' if ex.get('infeasible') else 'no'}")
    if ex.get("infeasible_summary"):
        out.append(f"  {ex['infeasible_summary']}")
    if ex.get("conflicting_ids"):
        out.append(f"  Conflicting: {json.dumps(ex['conflicting_ids'])}")
    out.append("")

    out.append("What the narrative states (for checking the setup):")
    out += [f"  - {_fact(sc, f)}" for f in ex.get("narrative_facts") or []]
    out.append("")
    other = [("required_hours", "Demand (person-hours)"), ("budget_ratio", "Payroll cap / demand"),
             ("truck_days", "Truck days"), ("event_day", "Private event day"), ("callout_day", "Call-out day"),
             ("school_week", "School week")]
    for k, label in other:
        if k in ex:
            out.append(f"{label}: {_value(sc, 'days' if k == 'truck_days' else k, ex[k])}")
    return "\n".join(out) + "\n"


def make_dataset(sector: str, size: str, difficulty: str, state: str, city: Optional[str] = None,
                 seed: Optional[int] = None) -> dict[str, bytes]:
    """FILES -> bytes for one generated company. Raises ValueError on any value outside the allowed sets."""
    meta, sc = _meta(sector, size, difficulty, state, city, seed)
    with tempfile.TemporaryDirectory() as d:
        write_exports(sc, Path(d))
        files = {f"{k}.csv": (Path(d) / f"{k}.csv").read_bytes() for k in IMPORT_ORDER}
    files["README.txt"] = _readme(meta, sc).encode()
    files["ANSWER_KEY.txt"] = _answer_key(meta, sc).encode()
    return files


def make_dataset_zip(sector: str, size: str, difficulty: str, state: str, city: Optional[str] = None,
                     seed: Optional[int] = None) -> bytes:
    meta = dataset_meta(sector, size, difficulty, state, city, seed)
    files = make_dataset(sector, size, difficulty, state, city, meta["seed"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in FILES:
            info = zipfile.ZipInfo(f"{meta['folder']}/{name}", date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, files[name])
    return buf.getvalue()


def main(argv: Optional[list[str]] = None) -> None:
    p = argparse.ArgumentParser(prog="python -m shiftwright_scenarios.make_dataset", description=__doc__.split("\n")[0])
    p.add_argument("--sector", required=True, choices=SECTORS)
    p.add_argument("--size", required=True, choices=SIZES)
    p.add_argument("--difficulty", required=True, choices=DATASET_DIFFICULTIES)
    p.add_argument("--state", required=True)
    p.add_argument("--city", default=None)
    p.add_argument("--seed", type=int, default=None, help="omit for a random seed (printed and kept in README.txt)")
    p.add_argument("--out", required=True, type=Path, help="writes <out>/<company>/ and <out>/<company>.zip")
    a = p.parse_args(argv)
    try:
        meta = dataset_meta(a.sector, a.size, a.difficulty, a.state, a.city, a.seed)
    except ValueError as e:
        p.error(str(e))
    args = (a.sector, a.size, a.difficulty, a.state, a.city, meta["seed"])
    folder = a.out / meta["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in make_dataset(*args).items():
        (folder / name).write_bytes(data)
    (a.out / f"{meta['folder']}.zip").write_bytes(make_dataset_zip(*args))
    print(f"{meta['company_name']}: seed {meta['seed']} -> {folder}/ and {folder}.zip")

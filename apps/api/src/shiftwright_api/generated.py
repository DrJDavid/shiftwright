"""Generated sample businesses (PUNCHLIST A3) on top of WS4's dataset builder.

Files come from `shiftwright_scenarios.make_dataset(sector, size, difficulty, state, city, seed)` (E4) when it
exists; until then from `generate(...)` + `write_exports(...)` with a minimal README/ANSWER_KEY. The company
name, sector, location and the manager's narrative always come from `generate(...)` with the same arguments.
"""
from __future__ import annotations

import io
import json
import re
import secrets
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from shiftwright_contracts.models import Jurisdiction, Sector

SECTORS = ("retail", "food")
SIZES = ("S", "M")
DIFFICULTIES = ("easy", "normal", "tight", "legal_trap", "messy")
DEFAULT_PLACE = {"retail": ("TX", "austin"), "food": ("IL", "chicago")}
CSV_ORDER = ("roster", "training", "availability", "forecast", "history")
MAX_SEED = 2**31 - 1


class BadParams(ValueError):
    pass


@dataclass(frozen=True)
class Params:
    sector: str
    size: str
    difficulty: str
    state: str
    city: Optional[str]
    seed: int

    def as_dict(self) -> dict:
        return dict(sector=self.sector, size=self.size, difficulty=self.difficulty, state=self.state,
                    city=self.city, seed=self.seed)


@dataclass
class Dataset:
    params: Params
    company_name: str
    sector: Sector
    jurisdiction: Jurisdiction
    narrative: str
    files: dict[str, bytes]  # roster.csv, ..., README.txt, ANSWER_KEY.txt


def parse_params(body: dict) -> Params:
    """Validate the request body; BadParams (HTTP 400) on anything outside the allowed values."""
    if not isinstance(body, dict):
        raise BadParams("Body must be a JSON object.")
    unknown = sorted(set(body) - {"sector", "size", "difficulty", "state", "city", "seed"})
    if unknown:
        raise BadParams(f"Unknown fields: {unknown}")

    def pick(key: str, allowed: tuple, default):
        v = body.get(key)
        if v is None:
            return default
        if v not in allowed:
            raise BadParams(f"{key} must be one of {list(allowed)}, got {v!r}")
        return v

    sector = pick("sector", SECTORS, None)
    if sector is None:
        raise BadParams(f"sector is required: one of {list(SECTORS)}")
    size = pick("size", SIZES, "S")
    difficulty = pick("difficulty", DIFFICULTIES, "easy")
    state, city = body.get("state"), body.get("city")
    if state is None:
        if city is not None:
            raise BadParams("city needs a state")
        state, city = DEFAULT_PLACE[sector]
    if not (isinstance(state, str) and re.fullmatch(r"[A-Za-z]{2}", state.strip())):
        raise BadParams(f"state must be a two-letter code, got {state!r}")
    if city is not None and not (isinstance(city, str) and re.fullmatch(r"[A-Za-z][A-Za-z .'-]{0,39}", city.strip())):
        raise BadParams(f"city must be a city name, got {city!r}")
    seed = body.get("seed")
    if seed is None:
        seed = secrets.randbelow(1_000_000)
    elif isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SEED:
        raise BadParams(f"seed must be an integer from 0 to {MAX_SEED}, got {seed!r}")
    return Params(sector, size, difficulty, state.strip().upper(), city.strip().lower() if city else None, seed)


def _scenario(p: Params):
    from shiftwright_scenarios import generate

    return generate(p.seed, p.size, p.difficulty, Jurisdiction(state=p.state, city=p.city), sector=p.sector)


def _clean_name(raw: str) -> str:
    """Generator names carry a "(S/easy)" tag for evals; a sample business shouldn't show its difficulty."""
    return re.sub(r"\s*\([SML]/[a-z_]+\)\s*$", "", raw).strip() or raw


def has_builder() -> bool:
    import shiftwright_scenarios

    return hasattr(shiftwright_scenarios, "make_dataset")


def _fallback_files(p: Params, sc, name: str, narrative: str) -> dict[str, bytes]:
    from shiftwright_scenarios.exports import write_exports

    with tempfile.TemporaryDirectory() as d:
        write_exports(sc, Path(d))
        files = {f"{k}.csv": (Path(d) / f"{k}.csv").read_bytes() for k in CSV_ORDER if (Path(d) / f"{k}.csv").exists()}
    place = f"{p.city.title()}, {p.state}" if p.city else p.state
    files["README.txt"] = (
        f"{name}\n{place}\nGenerated with sector={p.sector} size={p.size} difficulty={p.difficulty} seed={p.seed}\n\n"
        f"Paste this into the chat:\n{narrative}\n\nImport order: {', '.join(f'{k}.csv' for k in CSV_ORDER)}\n"
    ).encode()
    files["ANSWER_KEY.txt"] = json.dumps(sc.expected, indent=2, default=str).encode()
    return files


def build(p: Params) -> Dataset:
    import shiftwright_scenarios

    sc = _scenario(p)
    raw_name = sc.config.store.name
    name = _clean_name(raw_name)
    narrative = sc.narrative.replace(raw_name, name)
    if has_builder():
        files = dict(shiftwright_scenarios.make_dataset(sector=p.sector, size=p.size, difficulty=p.difficulty,
                                                        state=p.state, city=p.city, seed=p.seed))
    else:
        files = _fallback_files(p, sc, name, narrative)
    return Dataset(params=p, company_name=name, sector=Sector(p.sector), jurisdiction=sc.config.store.jurisdiction,
                   narrative=narrative, files=files)


def build_zip(p: Params) -> tuple[str, bytes]:
    """(filename, zip bytes) for the download."""
    import shiftwright_scenarios

    if hasattr(shiftwright_scenarios, "make_dataset_zip"):
        data = shiftwright_scenarios.make_dataset_zip(sector=p.sector, size=p.size, difficulty=p.difficulty,
                                                      state=p.state, city=p.city, seed=p.seed)
        name = _clean_name(_scenario(p).config.store.name)
    else:
        ds = build(p)
        name = ds.company_name
        folder = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "sample_business"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fname in sorted(ds.files):
                info = zipfile.ZipInfo(f"{folder}/{fname}", date_time=(2026, 1, 1, 0, 0, 0))
                z.writestr(info, ds.files[fname], zipfile.ZIP_DEFLATED)
        data = buf.getvalue()
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") + ".zip", data

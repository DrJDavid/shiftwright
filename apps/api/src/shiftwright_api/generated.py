"""Generated sample businesses (PUNCHLIST A3) on top of WS4's dataset builder (E4):
`dataset_meta` / `make_dataset` / `make_dataset_zip` in shiftwright_scenarios.dataset."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from shiftwright_contracts.models import Jurisdiction, Sector
from shiftwright_scenarios.dataset import dataset_meta, make_dataset, make_dataset_zip

DEFAULT_PLACE = {"retail": ("TX", "austin"), "food": ("IL", "chicago")}
FIELDS = {"sector", "size", "difficulty", "state", "city", "seed"}


class BadParams(ValueError):
    pass


@dataclass(frozen=True)
class Params:
    sector: str
    size: str
    difficulty: str
    state: str
    city: Optional[str]
    seed: int  # always concrete (dataset_meta resolves a random one), so the company can be regenerated

    def as_dict(self) -> dict:
        return dict(sector=self.sector, size=self.size, difficulty=self.difficulty, state=self.state,
                    city=self.city, seed=self.seed)

    def args(self) -> tuple:
        return (self.sector, self.size, self.difficulty, self.state, self.city, self.seed)


@dataclass
class Dataset:
    params: Params
    meta: dict  # dataset_meta: company_name, folder, narrative, jurisdiction, leader_setup, ...
    files: dict[str, bytes]

    @property
    def company_name(self) -> str:
        return self.meta["company_name"]

    @property
    def narrative(self) -> str:
        return self.meta["narrative"]

    @property
    def sector(self) -> Sector:
        return Sector(self.params.sector)

    @property
    def jurisdiction(self) -> Jurisdiction:
        return Jurisdiction(**self.meta["jurisdiction"])


def parse_params(body: dict) -> tuple[Params, dict]:
    """Request body → (Params with a concrete seed, dataset_meta). BadParams (HTTP 400) on anything the
    dataset builder rejects, unknown fields, or a city without a state."""
    if not isinstance(body, dict):
        raise BadParams("Body must be a JSON object.")
    unknown = sorted(set(body) - FIELDS)
    if unknown:
        raise BadParams(f"Unknown fields: {unknown}")
    sector = body.get("sector")
    if sector is None:
        raise BadParams("sector is required: retail or food")
    state, city = body.get("state"), body.get("city")
    if state is None:
        if city is not None:
            raise BadParams("city needs a state")
        state, city = DEFAULT_PLACE.get(sector, (None, None))
    if city is not None and not (isinstance(city, str) and re.fullmatch(r"[A-Za-z][A-Za-z _.'-]{0,39}", city.strip())):
        raise BadParams(f"city must be a city name, got {city!r}")
    try:
        meta = dataset_meta(sector, body.get("size") or "S", body.get("difficulty") or "easy", state, city,
                            body.get("seed"))
    except ValueError as e:
        raise BadParams(str(e)) from e
    j = meta["jurisdiction"]
    return Params(meta["sector"], meta["size"], meta["difficulty"], j["state"], j["city"], meta["seed"]), meta


def build(p: Params, meta: Optional[dict] = None) -> Dataset:
    return Dataset(params=p, meta=meta or dataset_meta(*p.args()), files=make_dataset(*p.args()))


def build_zip(p: Params) -> tuple[str, bytes]:
    """(filename, zip bytes) for the download; the zip's folder is named after the company."""
    return f"{dataset_meta(*p.args())['folder']}.zip", make_dataset_zip(*p.args())

"""CSV import preview + commit against the db, shared by the REST routes, generated workplaces and the
`csv_import` card (which can commit a cached preview server-side)."""
from __future__ import annotations

from typing import Optional

from shiftwright_contracts.models import StoreConfig

from . import equipment, imports
from .db import ConfigInvalid, Database
from .models import ImportPreview


class CommitError(ValueError):
    def __init__(self, status: int, detail):
        super().__init__(str(detail))
        self.status, self.detail = status, detail


async def preview(db: Database, store_id: str, kind: str, data: bytes, helper_llm) -> ImportPreview:
    """Parse + propose a mapping; caches the full parse and the preview for the store. Nothing saved to config."""
    pv, rows = await imports.preview(kind, data, helper_llm)
    db.put(store_id, "import_rows", kind, rows)
    db.put(store_id, "import_preview", kind, pv.model_dump(mode="json"))
    return pv


def cached_preview(db: Database, store_id: str, kind: str) -> Optional[dict]:
    return db.get(store_id, "import_preview", kind)


def commit(db: Database, store_id: str, kind: str, mapping: dict, rows: Optional[list] = None,
           actor: str = "leader") -> tuple[StoreConfig, list[str]]:
    """Apply `rows` (default: the cached full parse) with `mapping`. Returns (config, warnings)."""
    cached = db.get(store_id, "import_rows", kind) or []
    rows = rows or []
    if not rows or (cached and len(rows) < len(cached)):  # client sent only the preview: use the full parse
        rows = cached
    if not rows:
        raise CommitError(400, "No rows to import; upload the CSV first.")
    missing = imports.unmapped_required(kind, mapping)
    if missing:
        raise CommitError(422, f"Required fields not mapped: {missing}")
    db.put(store_id, "import_preview", kind, None)  # a preview is pending only until it's committed
    warnings: list[str] = []
    extra: dict = {}
    if kind in imports.STORED_KINDS:
        existing = db.get(store_id, kind, "rows") or []
        db.put(store_id, kind, "rows", imports.stored_rows(kind, mapping, rows, existing, warnings))
        db.put(store_id, "import_warnings", kind, warnings)
        return db.get_config(store_id), warnings
    stored = {k: db.get(store_id, k, "rows") or [] for k in imports.STORED_KINDS}
    if kind == "sales_forecast" and not stored["labor_standards"]:
        raise CommitError(422, "Import labor standards first.")
    if kind == "workload" and not any(x["driver"] in ("cases", "pieces") for x in stored["labor_standards"]):
        raise CommitError(422, "Import labor standards (with a cases or pieces driver) first.")

    review = equipment.state(db, store_id)

    def fn(d):
        extra["out"] = imports.apply_rows(kind, d, mapping, rows, warnings, stored)
        extra["tagged"] = equipment.tag_in_dict(d, review)
    try:
        cfg = db.mutate(store_id, fn, f"import:{kind}", {"rows": len(rows), "mapping": mapping}, actor)
    except ConfigInvalid as e:
        raise CommitError(422, e.errors) from e
    if kind == "history" and extra.get("out") is not None:
        db.put(store_id, "history", "rows", extra["out"])
    tagged = extra.get("tagged") or []
    equipment.record_auto(db, store_id, tagged)
    if tagged:
        warnings.append(f"Tagged hazard/equipment roles (minor-labor rules use these; please confirm or reject): "
                        f"{equipment.describe(tagged)}.")
    db.put(store_id, "import_warnings", kind, warnings)
    return cfg, warnings

"""Acceptance tests for the test-company dataset builder (PUNCHLIST E4)."""
from __future__ import annotations

import inspect
import io
import sys
import zipfile
from pathlib import Path

import pytest

from shiftwright_scenarios import dataset_meta, generate, make_dataset, make_dataset_zip
from shiftwright_scenarios.exports import tm_id
from shiftwright_scenarios.dataset import DATASET_DIFFICULTIES, FILES, IMPORT_ORDER, main

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "import_packs"))
import packs_harness as h  # noqa: E402

SECTORS = ["retail", "food"]
ARGS = dict(state="IL", city="chicago", seed=42)


def _ds(sector, difficulty, size="S", **kw):
    return make_dataset(sector=sector, size=size, difficulty=difficulty, **{**ARGS, **kw})


def test_signatures_are_exact():
    order = ["sector", "size", "difficulty", "state", "city", "seed"]
    for fn in (make_dataset, make_dataset_zip, dataset_meta):
        assert list(inspect.signature(fn).parameters) == order, fn.__name__
    assert DATASET_DIFFICULTIES == ("easy", "normal", "tight", "legal_trap", "messy")
    assert IMPORT_ORDER == ("roster", "training", "availability", "forecast", "history")


@pytest.mark.parametrize("sector", SECTORS)
@pytest.mark.parametrize("difficulty", DATASET_DIFFICULTIES)
def test_files_present(sector, difficulty):
    ds = _ds(sector, difficulty)
    assert list(ds) == list(FILES)
    assert all(isinstance(v, bytes) and v for v in ds.values())
    meta = dataset_meta(sector, "S", difficulty, **ARGS)
    readme = ds["README.txt"].decode()
    assert meta["company_name"] in readme and meta["narrative"] in readme
    assert "Seed: 42" in readme
    assert "roster.csv -> training.csv -> availability.csv -> forecast.csv -> history.csv" in readme
    sc = generate(42, "S", difficulty, "IL/chicago", sector=sector)
    assert meta["narrative"] == sc.narrative.replace(sc.config.store.name, sc.config.store.name.split(" (")[0])
    assert f"({difficulty})" not in readme and f"/{difficulty})" not in readme
    assert len(ds["roster.csv"].decode().splitlines()) == len(sc.config.employees) + 1


def test_answer_key_comes_from_expected():
    sc = generate(42, "S", "legal_trap", "IL/chicago", sector="food")
    key = _ds("food", "legal_trap")["ANSWER_KEY.txt"].decode()
    names = {e.id: e.name for e in sc.config.employees}
    for k, ids in sc.expected["traps"].items():
        if k == "notes":
            assert ids in key
            continue
        assert k in key
        for eid in ids:
            assert names[eid] in key and tm_id(eid) in key
    assert "Infeasible: no" in key

    sc = generate(42, "S", "legal_trap", "IL/chicago")
    key = _ds("retail", "legal_trap")["ANSWER_KEY.txt"].decode()
    assert all(tm_id(e) in key for e in sc.expected["traps"]["minor_pit_trained"])

    sc = generate(42, "S", "messy", "IL/chicago", sector="food")
    key = _ds("food", "messy")["ANSWER_KEY.txt"].decode()
    for c in sc.expected["narrative_contradictions"]:
        assert c["statement"] in key
    for o in sc.expected["narrative_omissions"]:
        assert o["kind"] in key

    key = _ds("retail", "easy")["ANSWER_KEY.txt"].decode()
    assert "Planted traps: none" in key and "Below the minimum wage: none" in key


@pytest.mark.parametrize("sector", SECTORS)
def test_easy_imports_to_ready(sector, tmp_path):
    ds = _ds(sector, "easy")
    meta = dataset_meta(sector, "S", "easy", **ARGS)
    for name, data in ds.items():
        (tmp_path / name).write_bytes(data)
    setup = meta["leader_setup"]
    s = h.Session(str(tmp_path))
    s.create(setup)
    s.store_basics(setup)
    for kind in meta["import_order"]:
        r = s.import_file(kind, tmp_path / f"{kind}.csv", setup["manual_mappings"].get(kind))
        assert r.status == 200 and r.commit_status == 200, (kind, r.commit_detail)
    s.priorities_and_budget(setup)
    cfg = s.config()
    sc = generate(42, "S", "easy", "IL/chicago", sector=sector)
    assert len(cfg["employees"]) == len(sc.config.employees)
    readiness = s.readiness()
    assert readiness["ready"], h.failing_checks(readiness)


def test_zip_is_deterministic_and_foldered():
    z1 = make_dataset_zip("food", "S", "legal_trap", "IL", "chicago", 7)
    assert z1 == make_dataset_zip("food", "S", "legal_trap", "IL", "chicago", 7)
    assert z1 != make_dataset_zip("food", "S", "legal_trap", "IL", "chicago", 8)
    folder = dataset_meta("food", "S", "legal_trap", "IL", "chicago", 7)["folder"]
    with zipfile.ZipFile(io.BytesIO(z1)) as zf:
        assert zf.namelist() == [f"{folder}/{f}" for f in FILES]
        assert {i.date_time for i in zf.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        assert zf.read(f"{folder}/roster.csv") == make_dataset("food", "S", "legal_trap", "IL", "chicago", 7)["roster.csv"]


def test_random_seed_is_recorded_and_reproducible():
    meta = dataset_meta("retail", "S", "easy", "TX", None, None)
    assert isinstance(meta["seed"], int)
    ds = make_dataset("retail", "S", "easy", "TX", None, None)
    seed = int(ds["README.txt"].decode().split("Seed: ")[1].split()[0])
    assert make_dataset("retail", "S", "easy", "TX", None, seed) == ds


def test_city_is_optional_and_normalized():
    assert dataset_meta("retail", "S", "easy", "tx", None, 1)["jurisdiction"] == {"state": "TX", "city": None}
    m = dataset_meta("food", "S", "easy", "CA", "San Francisco", 1)
    assert m["jurisdiction"] == {"state": "CA", "city": "san-francisco"} and m["law_coverage"] == "full"
    assert "San Francisco, CA" in m["company_name"]
    m = dataset_meta("food", "S", "easy", "TX", "Round Rock", 1)
    assert m["law_coverage"] == "state_only"
    assert "state and federal" in make_dataset("food", "S", "easy", "TX", "Round Rock", 1)["README.txt"].decode()


@pytest.mark.parametrize("bad", [
    dict(sector="hotel"), dict(size="L"), dict(size="s"), dict(difficulty="infeasible"), dict(difficulty="hard"),
    dict(state="ZZ"), dict(state=""), dict(seed=-1), dict(seed="42"), dict(seed=True), dict(seed=1.5),
])
def test_bad_values_rejected(bad):
    args = dict(sector="retail", size="S", difficulty="easy", **ARGS) | bad
    for fn in (make_dataset, make_dataset_zip, dataset_meta):
        with pytest.raises(ValueError):
            fn(**args)


def test_cli_module_runs(tmp_path):
    import subprocess
    r = subprocess.run([sys.executable, "-W", "error::RuntimeWarning", "-m", "shiftwright_scenarios.make_dataset",
                        "--sector", "retail", "--size", "S", "--difficulty", "easy", "--state", "TX", "--seed", "5",
                        "--out", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "seed 5" in r.stdout and not r.stderr
    folder = dataset_meta("retail", "S", "easy", "TX", None, 5)["folder"]
    assert (tmp_path / f"{folder}.zip").read_bytes() == make_dataset_zip("retail", "S", "easy", "TX", None, 5)


def test_cli_writes_files_and_zip(tmp_path, capsys):
    main(["--sector", "food", "--size", "S", "--difficulty", "legal_trap", "--state", "IL", "--city", "chicago",
          "--seed", "42", "--out", str(tmp_path)])
    folder = dataset_meta("food", "S", "legal_trap", "IL", "chicago", 42)["folder"]
    assert sorted(p.name for p in (tmp_path / folder).iterdir()) == sorted(FILES)
    assert (tmp_path / f"{folder}.zip").read_bytes() == make_dataset_zip("food", "S", "legal_trap", "IL", "chicago", 42)
    assert "seed 42" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--sector", "hotel", "--size", "S", "--difficulty", "easy", "--state", "IL", "--out", str(tmp_path)])

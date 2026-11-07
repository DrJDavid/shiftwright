"""SQLite persistence (plain sqlite3). Configs, audit log, schedules, transcripts, outreach, messages."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import ValidationError

from shiftwright_contracts.models import Schedule, StoreConfig, ValidationReport

SCHEMA = """
CREATE TABLE IF NOT EXISTS stores (
  id TEXT PRIMARY KEY, config_json TEXT NOT NULL, config_version INTEGER NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, store_id TEXT NOT NULL, version INTEGER NOT NULL,
  tool_name TEXT NOT NULL, args_json TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedules (
  id INTEGER PRIMARY KEY AUTOINCREMENT, store_id TEXT NOT NULL, schedule_json TEXT NOT NULL,
  validation_json TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS transcripts (
  store_id TEXT PRIMARY KEY, messages_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kv (
  store_id TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL, PRIMARY KEY (store_id, kind, key));
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, store_id TEXT, direction TEXT NOT NULL, message_json TEXT NOT NULL, at TEXT NOT NULL);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class NotFound(KeyError):
    pass


class ConfigInvalid(ValueError):
    def __init__(self, errors: list[dict]):
        super().__init__(json.dumps(errors, default=str)[:2000])
        self.errors = errors


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._lock = threading.RLock()

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # -- stores -------------------------------------------------------------- #
    def create_store(self, config: StoreConfig, actor: str = "system") -> StoreConfig:
        ts = now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO stores VALUES (?,?,?,?,?)",
                (config.store.id, config.model_dump_json(), config.config_version, ts, ts),
            )
            self._audit(config.store.id, config.config_version, "create_store", {}, actor)
        return config

    def get_config(self, store_id: str) -> StoreConfig:
        rows = self._q("SELECT config_json FROM stores WHERE id=?", (store_id,))
        if not rows:
            raise NotFound(store_id)
        return StoreConfig.model_validate_json(rows[0][0])

    def mutate(
        self,
        store_id: str,
        fn: Callable[[dict], Optional[dict]],
        tool_name: str,
        args: dict,
        actor: str,
    ) -> StoreConfig:
        """Apply `fn` to the config as a JSON dict, validate against the contract, bump version, audit.

        `fn` may edit the dict in place or return a replacement. Raises ConfigInvalid with
        pydantic errors (nothing saved) when the result does not validate.
        """
        with self._lock:
            current = self.get_config(store_id)
            data = current.model_dump(mode="json")
            out = fn(data)
            if out is not None:
                data = out
            data["store"]["id"] = store_id  # the id never changes
            data["config_version"] = current.config_version + 1
            try:
                new = StoreConfig.model_validate(data)
            except ValidationError as e:
                raise ConfigInvalid(e.errors(include_url=False)) from e
            self._conn.execute(
                "UPDATE stores SET config_json=?, config_version=?, updated_at=? WHERE id=?",
                (new.model_dump_json(), new.config_version, now_iso(), store_id),
            )
            self._audit(store_id, new.config_version, tool_name, args, actor)
            return new

    def _audit(self, store_id: str, version: int, tool: str, args: dict, actor: str) -> None:
        self._conn.execute(
            "INSERT INTO audit_log (store_id, version, tool_name, args_json, actor, at) VALUES (?,?,?,?,?,?)",
            (store_id, version, tool, json.dumps(args, default=str), actor, now_iso()),
        )

    def audit_log(self, store_id: str) -> list[dict]:
        rows = self._q(
            "SELECT version, tool_name, args_json, actor, at FROM audit_log WHERE store_id=? ORDER BY id", (store_id,)
        )
        return [dict(version=r[0], tool_name=r[1], args=json.loads(r[2]), actor=r[3], at=r[4]) for r in rows]

    # -- schedules ----------------------------------------------------------- #
    def save_schedule(self, store_id: str, schedule: Schedule, validation: Optional[ValidationReport]) -> None:
        self._q(
            "INSERT INTO schedules (store_id, schedule_json, validation_json, created_at) VALUES (?,?,?,?)",
            (store_id, schedule.model_dump_json(), validation.model_dump_json() if validation else None, now_iso()),
        )

    def latest_schedule(self, store_id: str) -> tuple[Schedule, Optional[ValidationReport]]:
        rows = self._q(
            "SELECT schedule_json, validation_json FROM schedules WHERE store_id=? ORDER BY id DESC LIMIT 1",
            (store_id,),
        )
        if not rows:
            raise NotFound(store_id)
        s, v = rows[0]
        return Schedule.model_validate_json(s), (ValidationReport.model_validate_json(v) if v else None)

    # -- transcripts --------------------------------------------------------- #
    def get_transcript(self, store_id: str) -> list[dict]:
        rows = self._q("SELECT messages_json FROM transcripts WHERE store_id=?", (store_id,))
        return json.loads(rows[0][0]) if rows else []

    def save_transcript(self, store_id: str, messages: list[dict]) -> None:
        self._q(
            "INSERT INTO transcripts VALUES (?,?,?) ON CONFLICT(store_id) DO UPDATE SET "
            "messages_json=excluded.messages_json, updated_at=excluded.updated_at",
            (store_id, json.dumps(messages, default=str), now_iso()),
        )

    # -- generic per-store key/value (fix plans, outreach state, session flags) #
    def put(self, store_id: str, kind: str, key: str, value: Any) -> None:
        self._q(
            "INSERT INTO kv VALUES (?,?,?,?,?) ON CONFLICT(store_id, kind, key) DO UPDATE SET "
            "value_json=excluded.value_json, updated_at=excluded.updated_at",
            (store_id, kind, key, json.dumps(value, default=str), now_iso()),
        )

    def get(self, store_id: str, kind: str, key: str, default: Any = None) -> Any:
        rows = self._q("SELECT value_json FROM kv WHERE store_id=? AND kind=? AND key=?", (store_id, kind, key))
        return json.loads(rows[0][0]) if rows else default

    # -- messages ------------------------------------------------------------ #
    def log_message(self, msg_id: str, store_id: Optional[str], direction: str, message: dict) -> None:
        self._q(
            "INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?)",
            (msg_id, store_id, direction, json.dumps(message, default=str), now_iso()),
        )

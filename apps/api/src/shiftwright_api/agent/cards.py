"""Pending-card broker: an SSE turn awaits a card; POST /chat/card resolves it."""
from __future__ import annotations

import asyncio
from typing import Any


class CardBroker:
    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], asyncio.Future] = {}

    def open(self, store_id: str, card_id: str) -> asyncio.Future:
        fut = asyncio.get_running_loop().create_future()
        self._pending[(store_id, card_id)] = fut
        return fut

    def close(self, store_id: str, card_id: str) -> None:
        self._pending.pop((store_id, card_id), None)

    def submit(self, store_id: str, card_id: str, result: dict[str, Any]) -> bool:
        fut = self._pending.get((store_id, card_id))
        if fut is None or fut.done():
            return False
        fut.get_loop().call_soon_threadsafe(_set, fut, result)
        return True

    def cancel_all(self, store_id: str, reason: str) -> int:
        """Resolve every open card for this store as cancelled (e.g. a new turn superseded it)."""
        n = 0
        for (s, c), fut in list(self._pending.items()):
            if s == store_id and not fut.done():
                fut.get_loop().call_soon_threadsafe(_set, fut, {"cancelled": True, "reason": reason})
                n += 1
        return n

    def pending(self, store_id: str) -> list[str]:
        return [c for (s, c), f in self._pending.items() if s == store_id and not f.done()]


def _set(fut: asyncio.Future, result: dict) -> None:
    if not fut.done():
        fut.set_result(result)

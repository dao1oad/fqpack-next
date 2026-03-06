# -*- coding: utf-8 -*-

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Generic, Hashable, TypeVar

KeyT = TypeVar("KeyT", bound=Hashable)
ValueT = TypeVar("ValueT")


@dataclass
class CoalesceState(Generic[ValueT]):
    inflight: bool = False
    pending: bool = False
    latest: ValueT | None = None


class CoalescingScheduler(Generic[KeyT, ValueT]):
    """
    Per-key coalesce:
    - 同一个 key 的多次 update 只保留 latest
    - 同一个 key 同时最多 1 个 inflight
    - global inflight 达到上限时，不提交新任务，只标记 pending
    """

    def __init__(self, *, max_inflight: int, submit_fn: Callable[[KeyT, ValueT], Any]):
        self.max_inflight = max(1, int(max_inflight))
        self._submit_fn = submit_fn
        self._lock = threading.RLock()
        self._states: dict[KeyT, CoalesceState[ValueT]] = {}
        self._inflight_total = 0

    def update(self, key: KeyT, latest: ValueT) -> None:
        with self._lock:
            st = self._states.get(key)
            if st is None:
                st = CoalesceState[ValueT]()
                self._states[key] = st
            st.latest = latest
            if st.inflight:
                st.pending = True
                return
            if self._inflight_total >= self.max_inflight:
                st.pending = True
                return
            self._submit(key)

    def mark_done(self, key: KeyT) -> None:
        with self._lock:
            st = self._states.get(key)
            if st is None or not st.inflight:
                return
            st.inflight = False
            if self._inflight_total > 0:
                self._inflight_total -= 1
            if st.pending and self._inflight_total < self.max_inflight:
                st.pending = False
                self._submit(key)
            self.drain()

    def drain(self) -> None:
        """
        Try to submit other pending keys until reaching global inflight limit.
        """
        with self._lock:
            if self._inflight_total >= self.max_inflight:
                return
            for k, st in self._states.items():
                if self._inflight_total >= self.max_inflight:
                    return
                if st.pending and not st.inflight:
                    st.pending = False
                    self._submit(k)

    def _submit(self, key: KeyT) -> None:
        st = self._states[key]
        latest = st.latest
        assert latest is not None
        st.inflight = True
        self._inflight_total += 1
        self._submit_fn(key, latest)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            pending = 0
            inflight = 0
            for st in self._states.values():
                if st.pending:
                    pending += 1
                if st.inflight:
                    inflight += 1
            return {
                "keys": len(self._states),
                "pending": pending,
                "inflight": inflight,
                "inflight_total": self._inflight_total,
            }

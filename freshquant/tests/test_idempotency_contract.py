# -*- coding: utf-8 -*-
"""根④幂等/并发契约测试：S6 ladder 事件表 TTL、S7 last_triggered_price 原子合并。"""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace

sys.modules.setdefault("freshquant.message", types.ModuleType("freshquant.message"))
from freshquant.strategy.guardian_ladder import GuardianLadderState  # noqa: E402

sys.modules.pop("freshquant.message", None)


class _EventsCollection:
    def __init__(self, docs=None):
        self.docs = [dict(item) for item in docs or []]
        self.created_indexes = []
        self.last_insert = None

    def index_information(self):
        return {name: {} for (_fields, _expire, name) in self.created_indexes}

    def create_index(self, fields, expireAfterSeconds=None, name=None):
        self.created_indexes.append((list(fields), expireAfterSeconds, name))
        return name

    def insert_one(self, document):
        from pymongo.errors import DuplicateKeyError

        for doc in self.docs:
            if doc.get("_id") == document.get("_id"):
                raise DuplicateKeyError("duplicate")
        self.docs.append(dict(document))
        self.last_insert = dict(document)
        return SimpleNamespace(inserted_id=document["_id"])


class _TpStateCollection:
    def __init__(self, docs=None):
        self.docs = [dict(item) for item in docs or []]
        self.update_calls = []

    def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None

    def insert_one(self, document):
        self.docs.append(dict(document))
        return SimpleNamespace(inserted_id=str(len(self.docs)))

    def update_one(self, query, update, upsert=False):
        self.update_calls.append({"query": query, "update": update})
        for doc in self.docs:
            matched = True
            for key, value in query.items():
                if key == "$or":
                    if not any(_match_or(doc, branch) for branch in value):
                        matched = False
                        break
                elif doc.get(key) != value:
                    matched = False
                    break
            if not matched:
                continue
            for operator, fields in update.items():
                if operator == "$set":
                    _apply_set(doc, fields)
                elif operator == "$inc":
                    for path, value in fields.items():
                        current = doc.get(path) or 0
                        doc[path] = current + value
            return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)


def _match_or(doc, branch):
    for key, value in branch.items():
        if isinstance(value, dict) and "$exists" in value:
            if bool(value["$exists"]) != (_get_path(doc, key) is not None):
                return False
            continue
        if _get_path(doc, key) != value:
            return False
    return True


def _get_path(doc, path):
    node = doc
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        if part in node:
            node = node[part]
            continue
        try:
            node = node[int(part)]
        except (KeyError, ValueError, TypeError):
            return None
    return node


def _apply_set(doc, fields):
    for path, value in fields.items():
        parts = path.split(".")
        node = doc
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value


class _FixedDatabase:
    def __init__(self, collection):
        self.collection = collection

    def __getitem__(self, name):
        return self.collection


class _BuyGridDatabase:
    def __getitem__(self, name):
        return SimpleNamespace(find_one=lambda query: None)


def _build_ladder(*, events_collection, tp_state_collection):
    return GuardianLadderState(
        buy_grid_database=_BuyGridDatabase(),
        tp_database=_FixedDatabase(tp_state_collection),
        events_database=_FixedDatabase(events_collection),
    )


def test_s6_claim_event_writes_ttl_field_and_creates_ttl_index():
    events = _EventsCollection()
    ladder = _build_ladder(
        events_collection=events,
        tp_state_collection=_TpStateCollection(),
    )

    claimed = ladder._claim_event(
        code="000001", event_type="takeprofit_trigger", event_key="evt-1"
    )

    assert claimed is True
    assert events.last_insert["created_at_dt"] is not None
    assert events.created_indexes == [
        (
            [("created_at_dt", 1)],
            7 * 24 * 60 * 60,
            "ttl_guardian_ladder_events",
        )
    ]


def test_s6_claim_event_is_idempotent_and_ttl_index_created_once():
    events = _EventsCollection()
    ladder = _build_ladder(
        events_collection=events,
        tp_state_collection=_TpStateCollection(),
    )

    assert (
        ladder._claim_event(
            code="000001", event_type="takeprofit_trigger", event_key="evt-1"
        )
        is True
    )
    assert (
        ladder._claim_event(
            code="000001", event_type="takeprofit_trigger", event_key="evt-1"
        )
        is False
    )
    assert len(events.created_indexes) == 1
    assert len(events.docs) == 1


def test_s7_takeprofit_trigger_writes_last_triggered_price_in_same_atomic_set():
    events = _EventsCollection()
    tp = _TpStateCollection(docs=[{"symbol": "000001", "armed_levels": {1: True}}])
    ladder = _build_ladder(events_collection=events, tp_state_collection=tp)

    triggered = ladder.on_takeprofit_trigger(
        code="000001",
        level=1,
        event_key="tp-1",
        trigger_price=10.5,
    )

    assert triggered is True
    # _ensure_tp_state_document 的 $setOnInsert upsert + 主更新，共两次
    assert len(tp.update_calls) == 2
    update = tp.update_calls[-1]["update"]
    assert update["$set"]["last_triggered_price"] == 10.5
    assert update["$set"]["armed_levels.1"] is False
    assert update["$inc"] == {"version": 1}

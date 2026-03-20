# -*- coding: utf-8 -*-

from datetime import datetime, timezone

from freshquant.position_management.repository import PositionManagementRepository
from freshquant.position_management.symbol_position_service import (
    SingleSymbolPositionService,
)


def test_resolve_snapshot_prefers_broker_market_value_over_bar_close():
    service = SingleSymbolPositionService(
        xt_position_loader=lambda: [
            {
                "stock_code": "600000.SH",
                "volume": 1200,
                "market_value": 118000.0,
                "last_price": 98.33,
            }
        ],
        projected_position_loader=lambda: [{"code": "600000", "quantity": 800}],
    )

    snapshot = service.resolve_symbol_snapshot(
        "600000",
        {
            "symbol": "600000",
            "period": "1m",
            "data": {"close": 10.5},
            "time": "2026-03-17 10:31:00",
        },
    )

    assert snapshot["symbol"] == "600000"
    assert snapshot["quantity"] == 1200
    assert snapshot["quantity_source"] == "xt_positions"
    assert snapshot["close_price"] == 98.33
    assert snapshot["price_source"] == "xt_positions_last_price"
    assert snapshot["market_value"] == 118000.0
    assert snapshot["market_value_source"] == "xt_positions_market_value"
    assert snapshot["stale"] is False


def test_resolve_snapshot_does_not_fallback_to_projected_quantity_when_broker_position_missing():
    service = SingleSymbolPositionService(
        xt_position_loader=lambda: [],
        projected_position_loader=lambda: [{"symbol": "600000", "quantity": 800}],
    )

    snapshot = service.resolve_symbol_snapshot(
        "600000",
        {
            "symbol": "sh600000",
            "period": "1m",
            "data": {"close": 9.88},
            "time": "2026-03-17 10:32:00",
        },
    )

    assert snapshot["quantity"] == 0
    assert snapshot["quantity_source"] == "xt_positions"
    assert snapshot["market_value"] == 0.0
    assert snapshot["market_value_source"] == "no_broker_position"
    assert snapshot["stale"] is False


def test_resolve_snapshot_uses_broker_market_value_when_bar_close_missing():
    service = SingleSymbolPositionService(
        xt_position_loader=lambda: [
            {
                "stock_code": "600000.SH",
                "volume": 1200,
                "market_value": 118000.0,
                "last_price": 98.33,
            }
        ],
        projected_position_loader=lambda: [{"symbol": "600000", "quantity": 800}],
    )

    snapshot = service.resolve_symbol_snapshot("600000", None)

    assert snapshot["quantity"] == 1200
    assert snapshot["quantity_source"] == "xt_positions"
    assert snapshot["close_price"] == 98.33
    assert snapshot["price_source"] == "xt_positions_last_price"
    assert snapshot["market_value"] == 118000.0
    assert snapshot["market_value_source"] == "xt_positions_market_value"
    assert snapshot["stale"] is False


def test_resolve_snapshot_returns_zero_position_when_no_broker_snapshot_exists():
    service = SingleSymbolPositionService(
        xt_position_loader=lambda: [],
        projected_position_loader=lambda: [{"symbol": "600000", "quantity": 800}],
    )

    snapshot = service.resolve_symbol_snapshot("600000", None)

    assert snapshot["quantity"] == 0
    assert snapshot["quantity_source"] == "xt_positions"
    assert snapshot["close_price"] is None
    assert snapshot["market_value"] == 0.0
    assert snapshot["market_value_source"] == "no_broker_position"
    assert snapshot["stale"] is False


class InMemoryCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, fields):
        rows = list(self.docs)
        for key, direction in reversed(list(fields or [])):
            rows.sort(
                key=lambda item: item.get(key),
                reverse=int(direction) < 0,
            )
        return InMemoryCursor(rows)

    def limit(self, size):
        return InMemoryCursor(self.docs[: int(size)])

    def __iter__(self):
        return iter(self.docs)


class InMemoryCollection:
    def __init__(self):
        self.docs = []

    def update_one(self, query, update, upsert=False):
        target = self.find_one(query)
        if target is None:
            if not upsert:
                return None
            target = dict(query)
            self.docs.append(target)
        payload = dict((update or {}).get("$set") or {})
        target.update(payload)
        return target

    def find_one(self, query=None, sort=None):
        rows = list(self.find(query))
        if sort:
            rows = list(InMemoryCursor(rows).sort(sort))
        return dict(rows[0]) if rows else None

    def find(self, query=None):
        query = dict(query or {})
        rows = []
        for doc in self.docs:
            matched = True
            for key, value in query.items():
                if isinstance(value, dict) and "$in" in value:
                    if doc.get(key) not in set(value["$in"]):
                        matched = False
                        break
                elif doc.get(key) != value:
                    matched = False
                    break
            if matched:
                rows.append(dict(doc))
        return InMemoryCursor(rows)

    def delete_many(self, query=None):
        query = dict(query or {})
        remaining = []
        deleted = 0
        for doc in self.docs:
            matched = True
            for key, value in query.items():
                if isinstance(value, dict) and "$nin" in value:
                    if doc.get(key) in set(value["$nin"]):
                        matched = False
                        break
                elif doc.get(key) != value:
                    matched = False
                    break
            if matched:
                deleted += 1
                continue
            remaining.append(doc)
        self.docs = remaining
        return deleted


class InMemoryDatabase(dict):
    def __getitem__(self, name):
        if name not in self:
            self[name] = InMemoryCollection()
        return dict.__getitem__(self, name)


def _fixed_now():
    return datetime(2026, 3, 17, 2, 35, tzinfo=timezone.utc)


def test_symbol_snapshot_round_trip_uses_repository_storage():
    repository = PositionManagementRepository(database=InMemoryDatabase())
    service = SingleSymbolPositionService(
        repository=repository,
        xt_position_loader=lambda: [
            {
                "stock_code": "600000.SH",
                "volume": 1200,
                "market_value": 118000.0,
            }
        ],
        projected_position_loader=lambda: [],
        now_provider=_fixed_now,
    )

    saved = service.refresh_from_bar_close(
        {
            "symbol": "sh600000",
            "period": "1m",
            "data": {"close": 10.5},
            "time": "2026-03-17 10:31:00",
        }
    )

    fetched = service.get_symbol_snapshot("600000.SH")
    rows = service.list_symbol_snapshots(["600000"])

    assert saved["symbol"] == "600000"
    assert saved["market_value"] == 118000.0
    assert fetched["market_value_source"] == "xt_positions_market_value"
    assert rows[0]["symbol"] == "600000"


def test_refresh_all_from_positions_removes_stale_snapshots_missing_from_broker_truth():
    repository = PositionManagementRepository(database=InMemoryDatabase())
    repository.upsert_symbol_snapshot(
        {
            "symbol": "600000",
            "quantity": 1200,
            "market_value": 118000.0,
            "market_value_source": "xt_positions_market_value",
        }
    )
    service = SingleSymbolPositionService(
        repository=repository,
        xt_position_loader=lambda: [
            {
                "stock_code": "000001.SZ",
                "volume": 500,
                "market_value": 6000.0,
            }
        ],
        projected_position_loader=lambda: [],
        now_provider=_fixed_now,
    )

    rows = service.refresh_all_from_positions()

    assert [item["symbol"] for item in rows] == ["000001"]
    assert repository.get_symbol_snapshot("600000") is None

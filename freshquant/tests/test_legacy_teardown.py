# -*- coding: utf-8 -*-
"""6b legacy 拆表（C2）测试。

核心断言（Devin C2 放行标准）：
1. compare 不干净（mismatch）且未显式 --confirm-residue → drop 拒绝执行；
2. broker 与 V2 不一致（V2 覆盖缺失）→ drop 拒绝执行（即使有 confirm）；
3. compare 零差异 → drop 执行，且 legacy_teardown_drop 事件前必有同 SHA 的
   legacy_teardown_compare 事件（命令内顺序强制）；
4. 差异全部归因 compat 陈旧残留（V2=broker）且 --confirm-residue → drop 执行；
5. 默认 dry-run：只出 compare 证据，不删除任何集合。
"""

from __future__ import annotations

from types import SimpleNamespace


class FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.delete_calls = 0

    def find(self, query=None):
        return [dict(item) for item in self.rows]

    def delete_many(self, query=None):
        self.delete_calls += 1
        before = len(self.rows)
        self.rows = []
        return SimpleNamespace(deleted_count=before)


class FakeBusinessDatabase:
    def __init__(self, *, compat_rows=None, broker_rows=None):
        self.stock_fills_compat = FakeCollection(compat_rows)
        self.stock_fills = FakeCollection()
        self.xt_positions = FakeCollection(broker_rows)

    def __getitem__(self, name):
        return getattr(self, name)


class FakeOrderDatabase:
    def __init__(self):
        self.om_buy_lots = FakeCollection([{"_id": "b1"}])
        self.om_lot_slices = FakeCollection([{"_id": "s1"}])
        self.om_sell_allocations = FakeCollection([{"_id": "a1"}])

    def __getitem__(self, name):
        return getattr(self, name)


class FakeRuntimeLogger:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(dict(event))
        return True


class FakeRepository:
    def __init__(self, entries):
        self.entries = list(entries or [])

    def list_position_entries(self, *, symbol=None, entry_ids=None, status=None):
        rows = list(self.entries)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        return [dict(item) for item in rows]


def _entry(symbol, quantity, price=10.0, amount_adjust=1.0):
    return {
        "entry_id": f"entry_{symbol}",
        "symbol": symbol,
        "remaining_quantity": quantity,
        "original_quantity": quantity,
        "entry_price": price,
        "buy_price_real": price,
        "amount": round(price * quantity, 2),
        "amount_adjust": amount_adjust,
        "date": 20260101,
        "time": "09:30:00",
        "trade_time": 1,
        "stock_code": f"{symbol}.SZ",
    }


def _run(
    *,
    entries,
    compat_rows,
    broker_rows,
    allow_residue=False,
    execute=False,
    archive_dir=None,
    tmp_path,
):
    from freshquant.order_management.legacy_teardown import run_legacy_teardown

    logger = FakeRuntimeLogger()
    business_db = FakeBusinessDatabase(
        compat_rows=compat_rows,
        broker_rows=broker_rows,
    )
    order_db = FakeOrderDatabase()
    result = run_legacy_teardown(
        archive_dir=str(tmp_path) if archive_dir is None else archive_dir,
        allow_residue=allow_residue,
        execute=execute,
        runtime_logger=logger,
        repository=FakeRepository(entries),
        database=order_db,
        business_database=business_db,
    )
    return result, logger, business_db, order_db


def test_teardown_drops_when_compare_is_clean(tmp_path):
    """C2-3：compare 零差异 → drop，compare 事件先于 drop 事件（同 SHA）。"""

    result, logger, business_db, order_db = _run(
        entries=[_entry("000001", 300)],
        compat_rows=[
            {"symbol": "000001", "quantity": 300, "price": 10.0, "amount_adjust": 1.0}
        ],
        broker_rows=[{"stock_code": "000001.SZ", "can_use_volume": 300}],
        execute=True,
        tmp_path=tmp_path,
    )

    assert result["status"] == "dropped"
    assert order_db.om_buy_lots.rows == []
    assert order_db.om_lot_slices.rows == []
    assert order_db.om_sell_allocations.rows == []
    assert business_db.stock_fills_compat.rows == []
    assert business_db.stock_fills.rows == []

    codes = [event["reason_code"] for event in logger.events]
    assert codes == ["legacy_teardown_compare", "legacy_teardown_drop"]
    compare_event = logger.events[0]["payload"]
    drop_event = logger.events[1]["payload"]
    assert compare_event["sha"] == drop_event["sha"]
    assert drop_event["compare_snapshot_path"] == compare_event["snapshot_path"]


def test_teardown_refuses_drop_when_compare_not_clean(tmp_path):
    """C2-1：compare 不干净且未 confirm → 拒绝 drop（不删任何集合）。"""

    result, logger, business_db, order_db = _run(
        entries=[_entry("000001", 300)],
        compat_rows=[
            {"symbol": "000001", "quantity": 200, "price": 10.0, "amount_adjust": 1.0}
        ],
        broker_rows=[{"stock_code": "000001.SZ", "can_use_volume": 300}],
        execute=True,
        tmp_path=tmp_path,
    )

    assert result["status"] == "blocked"
    assert "legacy_teardown_blocked" in [e["reason_code"] for e in logger.events]
    assert order_db.om_buy_lots.rows, "拒绝 drop 时不得删除任何集合"
    assert business_db.stock_fills_compat.rows


def test_teardown_refuses_drop_when_broker_inconsistent(tmp_path):
    """C2-2：broker 有持仓而 V2 覆盖缺失 → 拒绝 drop（即使 confirm）。"""

    result, logger, _, order_db = _run(
        entries=[],
        compat_rows=[],
        broker_rows=[{"stock_code": "688772.SZ", "can_use_volume": 24881}],
        allow_residue=True,
        execute=True,
        tmp_path=tmp_path,
    )

    assert result["status"] == "blocked"
    assert order_db.om_buy_lots.rows


def test_teardown_allows_residue_when_v2_matches_broker(tmp_path):
    """C2-4：差异全部归因 compat 陈旧残留（V2=broker）且 confirm → drop。"""

    result, logger, business_db, order_db = _run(
        entries=[],
        compat_rows=[
            {
                "symbol": "688772",
                "quantity": 24881,
                "price": 10.749121,
                "amount_adjust": 1.0,
            }
        ],
        broker_rows=[],
        allow_residue=True,
        execute=True,
        tmp_path=tmp_path,
    )

    assert result["status"] == "dropped"
    assert business_db.stock_fills_compat.rows == []
    assert order_db.om_buy_lots.rows == []


def test_teardown_defaults_to_dry_run(tmp_path):
    """C2-5：默认 dry-run：只出 compare 证据，不删除任何集合。"""

    result, logger, business_db, order_db = _run(
        entries=[_entry("000001", 300)],
        compat_rows=[
            {"symbol": "000001", "quantity": 300, "price": 10.0, "amount_adjust": 1.0}
        ],
        broker_rows=[{"stock_code": "000001.SZ", "can_use_volume": 300}],
        execute=False,
        tmp_path=tmp_path,
    )

    assert result["status"] == "dry_run_ready"
    assert [e["reason_code"] for e in logger.events] == ["legacy_teardown_compare"]
    assert order_db.om_buy_lots.rows
    assert business_db.stock_fills_compat.rows

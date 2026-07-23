from __future__ import annotations

from collections.abc import Iterable, Mapping

import pandas as pd
import pytest

from freshquant.market_data.xtdata import qfq


class _Cursor:
    def __init__(self, rows: Iterable[Mapping]):
        self.rows = [dict(row) for row in rows]

    def sort(self, field, direction):
        self.rows.sort(key=lambda row: row.get(field), reverse=int(direction) < 0)
        return self

    def __iter__(self):
        return iter(self.rows)


class _Collection:
    def __init__(self, db, name, rows=()):
        self.db = db
        self.name = name
        self.rows = [dict(row) for row in rows]

    def find(self, query=None, projection=None):
        query = query or {}
        rows = []
        for row in self.rows:
            matched = True
            for key, expected in query.items():
                value = row.get(key)
                if isinstance(expected, dict) and "$in" in expected:
                    matched = value in expected["$in"]
                elif value != expected:
                    matched = False
                if not matched:
                    break
            if matched:
                if projection:
                    excluded = {
                        key for key, enabled in projection.items() if not enabled
                    }
                    if any(enabled for enabled in projection.values()):
                        rows.append(
                            {
                                key: row[key]
                                for key, enabled in projection.items()
                                if enabled and key in row
                            }
                        )
                    else:
                        rows.append(
                            {
                                key: value
                                for key, value in row.items()
                                if key not in excluded
                            }
                        )
                else:
                    rows.append(dict(row))
        return _Cursor(rows)

    def find_one(self, query=None, projection=None):
        return next(iter(self.find(query, projection)), None)

    def insert_many(self, rows, ordered=False):
        self.rows.extend(dict(row) for row in rows)

    def delete_many(self, query=None):
        query = query or {}
        before = len(self.rows)
        self.rows = [
            row
            for row in self.rows
            if not all(row.get(k) == v for k, v in query.items())
        ]
        return type("Result", (), {"deleted_count": before - len(self.rows)})()

    def create_index(self, *args, **kwargs):
        return "idx"

    def rename(self, target_name, dropTarget=False):
        if dropTarget:
            self.db.collections.pop(target_name, None)
        self.db.collections[target_name] = _Collection(self.db, target_name, self.rows)
        self.db.collections.pop(self.name, None)

    def update_one(self, query, update, upsert=False):
        if self.name == qfq.READY_COLLECTION:
            self.db.ready_writes += 1
            if self.db.fail_ready_on == self.db.ready_writes:
                raise RuntimeError("ready marker unavailable")
        values = dict(update.get("$set", {}))
        for row in self.rows:
            if all(row.get(key) == value for key, value in query.items()):
                row.update(values)
                return
        if upsert:
            self.rows.append({**query, **values})


class _DB:
    def __init__(self, **collections):
        self.collections = {}
        self.fail_ready_on = None
        self.ready_writes = 0
        for name, rows in collections.items():
            self.collections[name] = _Collection(self, name, rows)

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection(self, name))

    def drop_collection(self, name):
        self.collections.pop(name, None)


def _bars(*dates):
    return pd.DataFrame(
        {
            "time": list(dates),
            "close": [10.0, 9.0, 9.1][: len(dates)],
            "preClose": [9.8, 8.0, 9.0][: len(dates)],
        }
    )


def test_compute_preclose_adj_uses_actual_xtdata_axis():
    result = qfq.compute_preclose_adj(
        _bars("2026-01-02", "2026-01-05", "2026-01-06"), code="000001"
    )

    assert result["date"].tolist() == ["2026-01-02", "2026-01-05", "2026-01-06"]
    assert result["adj"].tolist() == pytest.approx([0.8, 1.0, 1.0])
    assert result["code"].tolist() == ["000001"] * 3


def test_normalize_xtdata_field_table_payload():
    payload = {
        "time": pd.DataFrame(
            [["2026-01-02", "2026-01-05"]], index=["000001.SZ"], columns=[0, 1]
        ),
        "close": pd.DataFrame([[10.0, 9.0]], index=["000001.SZ"], columns=[0, 1]),
        "preClose": pd.DataFrame([[9.8, 8.0]], index=["000001.SZ"], columns=[0, 1]),
    }

    result = qfq.normalize_xtdata_bars(payload, code="000001.SZ")
    assert result[["date", "close", "preClose"]].to_dict("records") == [
        {"date": "2026-01-02", "close": 10.0, "preClose": 9.8},
        {"date": "2026-01-05", "close": 9.0, "preClose": 8.0},
    ]


def test_load_factor_universe_excludes_non_trading_open_fund():
    db = _DB(
        etf_list=[
            {"code": "510050", "name": "交易型ETF", "sec": "etf_cn"},
            {"code": "160001", "name": "开放式联接基金", "sec": "fund_cn"},
        ]
    )

    result = qfq.load_factor_universe(kind="etf", db=db)
    assert result["codes"] == ["510050"]
    assert result["excluded"] == [{"code": "160001", "reason": "non_trading_open_fund"}]


def test_factor_universe_uses_shared_etf_classification_for_52_and_53():
    db = _DB(
        etf_list=[
            {"code": "520000", "name": "ETF 52", "sec": "etf_cn"},
            {"code": "530001", "name": "ETF 53", "sec": "etf_cn"},
        ],
        stock_list=[
            {"code": "000001", "name": "Stock"},
            {"code": "520000", "name": "ETF in stock list"},
            {"code": "530001", "name": "ETF in stock list"},
        ],
    )

    assert qfq.load_factor_universe(kind="etf", db=db)["codes"] == [
        "520000",
        "530001",
    ]
    stock = qfq.load_factor_universe(kind="stock", db=db)
    assert stock["codes"] == ["000001"]
    assert stock["excluded"] == [
        {"code": "520000", "reason": "etf_like_code"},
        {"code": "530001", "reason": "etf_like_code"},
    ]


def test_sync_stock_uses_bfq_bounds_and_publishes_marker():
    db = _DB(
        stock_list=[{"code": "000001", "name": "Stock"}],
        stock_day=[
            {"code": "000001", "date": "2026-01-02"},
            {"code": "000001", "date": "2026-01-05"},
        ],
    )
    calls = []

    def loader(code, *, start_time, end_time):
        calls.append((code, start_time, end_time))
        return _bars("2026-01-02", "2026-01-05")

    result = qfq.sync_stock_adj_all(db=db, bars_loader=loader)
    assert calls == [("000001", "20260102", "20260105")]
    assert result["by_scope"]["stock"]["audit"]["ok"] is True
    assert db["stock_adj"].rows == [
        {"code": "000001", "date": "2026-01-02", "adj": 0.8},
        {"code": "000001", "date": "2026-01-05", "adj": 1.0},
    ]
    marker = db["qfq_ready"].rows[0]
    assert marker["source"] == qfq.QFQ_SOURCE
    assert marker["writer"] == qfq.QFQ_WRITER
    assert marker["status"] == "ready"


def test_sync_fails_closed_when_bfq_date_is_missing():
    db = _DB(
        stock_list=[{"code": "000001"}],
        stock_day=[
            {"code": "000001", "date": "2026-01-02"},
            {"code": "000001", "date": "2026-01-05"},
        ],
    )

    with pytest.raises(qfq.QFQSyncError) as error:
        qfq.sync_stock_adj_all(
            db=db,
            bars_loader=lambda code, **kwargs: _bars("2026-01-02"),
        )

    assert qfq.QFQ_DATA_NOT_READY in str(error.value)
    assert not db["stock_adj"].rows
    assert not db["qfq_ready"].rows


def test_sync_fails_closed_when_xtdata_returns_extra_date():
    db = _DB(
        stock_list=[{"code": "000001"}],
        stock_day=[{"code": "000001", "date": "2026-01-02"}],
    )

    with pytest.raises(qfq.QFQSyncError):
        qfq.sync_stock_adj_all(
            db=db,
            bars_loader=lambda code, **kwargs: _bars("2026-01-01", "2026-01-02"),
        )
    assert not db["stock_adj"].rows
    assert not db["qfq_ready"].rows


def test_ready_marker_write_failure_is_not_swallowed():
    db = _DB()
    db.fail_ready_on = 1

    with pytest.raises(qfq.QFQSyncError, match="staging marker write failed"):
        qfq.publish_factor_snapshot(
            db=db,
            collection_name="stock_adj",
            documents=[{"code": "000001", "date": "2026-01-02", "adj": 1.0}],
            expected_dates_by_code={"000001": ["2026-01-02"]},
            included_codes=["000001"],
        )
    assert not db["stock_adj"].rows
    assert not db["qfq_ready"].rows


def test_final_ready_marker_failure_leaves_publishing_state():
    db = _DB()
    db.fail_ready_on = 2

    with pytest.raises(qfq.QFQSyncError, match="ready marker write failed"):
        qfq.publish_factor_snapshot(
            db=db,
            collection_name="stock_adj",
            documents=[{"code": "000001", "date": "2026-01-02", "adj": 1.0}],
            expected_dates_by_code={"000001": ["2026-01-02"]},
            included_codes=["000001"],
        )
    assert db["stock_adj"].rows
    assert db["qfq_ready"].rows[0]["status"] == "publishing"


def test_incremental_run_rebuilds_full_bfq_axis():
    db = _DB(
        stock_list=[{"code": "000001"}],
        stock_day=[
            {"code": "000001", "date": "2026-01-02"},
            {"code": "000001", "date": "2026-01-05"},
        ],
    )
    calls = []

    def loader(code, *, start_time, end_time):
        calls.append((start_time, end_time))
        return _bars("2026-01-02", "2026-01-05")

    qfq.sync_stock_adj_all(
        db=db,
        bars_loader=loader,
        start_time="20260105",
        end_time="20260105",
        incremental=True,
    )
    assert calls == [("20260102", "20260105")]


def test_incremental_run_downloads_only_terminal_overlap_and_rescales_prefix():
    db = _DB(
        stock_list=[{"code": "000001"}],
        stock_day=[
            {"code": "000001", "date": "2026-01-02"},
            {"code": "000001", "date": "2026-01-05"},
        ],
    )
    first_calls = []

    def first_loader(code, *, start_time, end_time):
        first_calls.append((start_time, end_time))
        return pd.DataFrame(
            {
                "time": ["2026-01-02", "2026-01-05"],
                "close": [10.0, 9.0],
                "preClose": [9.8, 8.0],
            }
        )

    qfq.sync_stock_adj_all(db=db, bars_loader=first_loader)
    db["stock_day"].rows.append({"code": "000001", "date": "2026-01-06"})
    incremental_calls = []

    def incremental_loader(code, *, start_time, end_time):
        incremental_calls.append((start_time, end_time))
        return pd.DataFrame(
            {
                "time": ["2026-01-05", "2026-01-06"],
                "close": [9.0, 9.1],
                "preClose": [8.0, 8.0],
            }
        )

    result = qfq.sync_stock_adj_all(
        db=db,
        bars_loader=incremental_loader,
        incremental=True,
    )

    assert first_calls == [("20260102", "20260105")]
    assert incremental_calls == [("20260105", "20260106")]
    assert result["by_scope"]["stock"]["mode_counts"] == {
        "incremental": 1,
        "full": 0,
    }
    rows = {row["date"]: row["adj"] for row in db["stock_adj"].rows}
    assert rows["2026-01-02"] == pytest.approx(0.8 * (8.0 / 9.0))
    assert rows["2026-01-05"] == pytest.approx(8.0 / 9.0)
    assert rows["2026-01-06"] == pytest.approx(1.0)

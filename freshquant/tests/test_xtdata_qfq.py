from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from freshquant.market_data.xtdata import qfq


def _get_path(document, path):
    value = document
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _set_path(document, path, value):
    target = document
    parts = path.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def _matches(document, query):
    for key, expected in (query or {}).items():
        value = _get_path(document, key)
        if isinstance(expected, Mapping):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$lte" in expected and not (
                value is not None and value <= expected["$lte"]
            ):
                return False
            if "$gte" in expected and not (
                value is not None and value >= expected["$gte"]
            ):
                return False
        elif value != expected:
            return False
    return True


class _Result:
    def __init__(self, *, matched_count=0, deleted_count=0):
        self.matched_count = matched_count
        self.modified_count = matched_count
        self.deleted_count = deleted_count


class _Cursor:
    def __init__(self, rows: Iterable[Mapping]):
        self.rows = [dict(row) for row in rows]

    def sort(self, field, direction):
        self.rows.sort(
            key=lambda row: _get_path(row, field), reverse=int(direction) < 0
        )
        return self

    def __iter__(self):
        return iter(self.rows)


class _Collection:
    def __init__(self, db, name, rows=()):
        self.db = db
        self.name = name
        self.rows = [dict(row) for row in rows]
        self.writes = 0

    def find(self, query=None, projection=None):
        rows = []
        for source in self.rows:
            if not _matches(source, query or {}):
                continue
            row = dict(source)
            if projection:
                included = [key for key, enabled in projection.items() if enabled]
                if included:
                    row = {key: row[key] for key in included if key in row}
                else:
                    row = {
                        key: value
                        for key, value in row.items()
                        if projection.get(key, 1)
                    }
            rows.append(row)
        return _Cursor(rows)

    def find_one(self, query=None, projection=None, sort=None):
        cursor = self.find(query, projection)
        if sort:
            for field, direction in reversed(sort):
                cursor.sort(field, direction)
        return next(iter(cursor), None)

    def distinct(self, field):
        return list(
            {_get_path(row, field) for row in self.rows if _get_path(row, field)}
        )

    def insert_one(self, document):
        self.rows.append(dict(document))
        self.writes += 1
        return _Result(matched_count=1)

    def insert_many(self, documents, ordered=False):
        values = [dict(document) for document in documents]
        self.rows.extend(values)
        self.writes += len(values)
        return _Result(matched_count=len(values))

    def delete_many(self, query=None):
        before = len(self.rows)
        self.rows = [row for row in self.rows if not _matches(row, query or {})]
        deleted = before - len(self.rows)
        self.writes += deleted
        return _Result(deleted_count=deleted)

    def delete_one(self, query=None):
        for index, row in enumerate(self.rows):
            if not _matches(row, query or {}):
                continue
            self.rows.pop(index)
            self.writes += 1
            return _Result(deleted_count=1)
        return _Result()

    def update_one(self, query, update, upsert=False):
        if self.db.fail_marker_cas and self.name == qfq.READY_COLLECTION:
            return _Result()
        for row in self.rows:
            if not _matches(row, query):
                continue
            for path, value in update.get("$set", {}).items():
                _set_path(row, path, value)
            self.writes += 1
            return _Result(matched_count=1)
        if upsert:
            row = {
                key: value
                for key, value in query.items()
                if not isinstance(value, Mapping) and "." not in key
            }
            for path, value in update.get("$setOnInsert", {}).items():
                _set_path(row, path, value)
            for path, value in update.get("$set", {}).items():
                _set_path(row, path, value)
            self.rows.append(row)
            self.writes += 1
            return _Result(matched_count=1)
        return _Result()

    def create_index(self, *args, **kwargs):
        return kwargs.get("name", "idx")

    def count_documents(self, query):
        return len(list(self.find(query)))


class _DB:
    def __init__(self, **collections):
        self.collections = {}
        self.fail_marker_cas = False
        for name, rows in collections.items():
            self.collections[name] = _Collection(self, name, rows)

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection(self, name))


def _bars(rows):
    return pd.DataFrame(rows, columns=["time", "close", "preClose"])


def _loader_for(rows_by_code):
    def load(code, *, start_time, end_time):
        start = pd.Timestamp(start_time).strftime("%Y-%m-%d")
        end = pd.Timestamp(end_time).strftime("%Y-%m-%d")
        rows = [row for row in rows_by_code[code] if start <= str(row[0])[:10] <= end]
        return _bars(rows)

    return load


def _stock_db(dates, *, code="000001"):
    return _DB(
        stock_list=[{"code": code, "name": "Stock"}],
        stock_day=[{"code": code, "date": date} for date in dates],
    )


def test_compute_preclose_adj_uses_actual_xtdata_axis():
    result = qfq.compute_preclose_adj(
        _bars(
            [
                ("2026-01-02", 10.0, 0.0),
                ("2026-01-05", 9.0, 8.0),
                ("2026-01-06", 9.1, 9.0),
            ]
        ),
        code="000001",
    )

    assert result["date"].tolist() == ["2026-01-02", "2026-01-05", "2026-01-06"]
    assert result["adj"].tolist() == pytest.approx([0.8, 1.0, 1.0])


@pytest.mark.parametrize("first_preclose", [0.0, float("nan")])
def test_first_preclose_is_unused(first_preclose):
    result = qfq.compute_preclose_adj(
        _bars(
            [
                ("2026-01-02", 10.0, first_preclose),
                ("2026-01-05", 10.0, 10.0),
            ]
        ),
        code="000001",
    )
    assert result["adj"].tolist() == [1.0, 1.0]


@pytest.mark.parametrize("used_preclose", [0.0, float("nan"), float("inf")])
def test_used_preclose_must_be_positive_and_finite(used_preclose):
    with pytest.raises(qfq.QFQSyncError, match="used preClose"):
        qfq.compute_preclose_adj(
            _bars(
                [
                    ("2026-01-02", 10.0, 0.0),
                    ("2026-01-05", 10.0, used_preclose),
                ]
            ),
            code="000001",
        )


@pytest.mark.parametrize("close", [0.0, float("nan"), float("inf")])
def test_close_must_be_positive_and_finite_even_for_single_bar(close):
    with pytest.raises(qfq.QFQSyncError, match="close values"):
        qfq.compute_preclose_adj(
            _bars([("2026-01-02", close, 0.0)]),
            code="000001",
        )


def test_normalize_xtdata_field_table_payload():
    payload = {
        "time": pd.DataFrame(
            [["2026-01-02", "2026-01-05"]], index=["000001.SZ"], columns=[0, 1]
        ),
        "close": pd.DataFrame([[10.0, 9.0]], index=["000001.SZ"], columns=[0, 1]),
        "preClose": pd.DataFrame([[0.0, 8.0]], index=["000001.SZ"], columns=[0, 1]),
    }

    result = qfq.normalize_xtdata_bars(payload, code="000001.SZ")
    assert result[["date", "close", "preClose"]].to_dict("records") == [
        {"date": "2026-01-02", "close": 10.0, "preClose": 0.0},
        {"date": "2026-01-05", "close": 9.0, "preClose": 8.0},
    ]


def test_normalize_xtdata_field_table_uses_trading_date_columns():
    payload = {
        "time": pd.DataFrame(
            [[670608000000]],
            index=["000001.SZ"],
            columns=["19910403"],
        ),
        "close": pd.DataFrame([[14.6]], index=["000001.SZ"], columns=["19910403"]),
        "preClose": pd.DataFrame([[0.0]], index=["000001.SZ"], columns=["19910403"]),
    }

    result = qfq.normalize_xtdata_bars(payload, code="000001.SZ")

    assert result["date"].tolist() == ["1991-04-03"]


def test_normalize_xtdata_empty_field_table_reports_no_daily_bars():
    empty = pd.DataFrame(index=["158000.SZ"])

    with pytest.raises(qfq.QFQSyncError, match="returned no daily bars") as caught:
        qfq.normalize_xtdata_bars(
            {"time": empty, "close": empty, "preClose": empty},
            code="158000.SZ",
        )

    assert caught.value.stats == {
        "failure": "source_empty_bars",
        "code": "158000",
    }


@pytest.mark.parametrize(
    "value",
    [
        "2026-01-02",
        "20260102",
        20260102,
        1767312000,
        1767312000000,
        date(2026, 1, 2),
        datetime(2026, 1, 2, 15, 30),
        pd.Timestamp("2026-01-02"),
    ],
)
def test_canonical_date_values_use_fast_path(monkeypatch, value):
    monkeypatch.setattr(
        qfq,
        "_parse_timestamp",
        lambda _value: (_ for _ in ()).throw(
            AssertionError("canonical dates must not use pandas parsing")
        ),
    )

    assert qfq._date_key(value) == "2026-01-02"


def test_normalize_xtdata_epoch_uses_shanghai_trading_date():
    result = qfq.normalize_xtdata_bars(
        pd.DataFrame({"time": [670608000000], "close": [14.6], "preClose": [0.0]}),
        code="000001.SZ",
    )

    assert result["date"].tolist() == ["1991-04-03"]


@pytest.mark.parametrize("code", ["920001", "430001", "830001"])
def test_to_xt_code_maps_beijing_markets(code):
    assert qfq.to_xt_code(code) == f"{code}.BJ"


def test_factor_universe_includes_historical_codes_and_excludes_real_indexes():
    db = _DB(
        stock_list=[{"code": "000001"}],
        stock_day=[
            {"code": "000001", "date": "2026-01-02"},
            {"code": "600999", "date": "2010-01-04"},
        ],
        stock_adj=[{"code": "601999", "date": "2011-01-04", "adj": 1.0}],
        etf_list=[{"code": "510050", "name": "ETF"}],
        index_day=[
            {"code": "510050", "date": "2026-01-02"},
            {"code": "159995", "date": "2026-01-02"},
            {"code": "000001", "date": "2026-01-02"},
            {"code": "399001", "date": "2026-01-02"},
        ],
    )

    assert qfq.load_factor_universe(kind="stock", db=db)["codes"] == [
        "000001",
        "600999",
        "601999",
    ]
    assert qfq.load_factor_universe(kind="etf", db=db)["codes"] == [
        "159995",
        "510050",
    ]


def test_load_bfq_dates_sorts_in_memory_without_mongo_date_sort():
    class _UnsortedCursor:
        def sort(self, *_args, **_kwargs):
            raise AssertionError("Mongo date sort must not bypass the code index")

        def __iter__(self):
            return iter(
                [
                    {"date": "2026-01-05"},
                    {"date": "2026-01-02"},
                    {"date": "2026-01-05"},
                ]
            )

    class _BfqCollection:
        def find(self, query, projection):
            assert query == {"code": "000001"}
            assert projection == {
                "_id": 0,
                "date": 1,
                "vol": 1,
                "volume": 1,
                "amount": 1,
            }
            return _UnsortedCursor()

    db = _DB()
    db.collections["stock_day"] = _BfqCollection()

    assert qfq.load_bfq_dates(kind="stock", code="000001", db=db) == [
        "2026-01-02",
        "2026-01-05",
    ]


def test_load_bfq_dates_excludes_qasu_tiny_volume_amount_sentinel():
    db = _DB(
        stock_day=[
            {
                "code": "000001",
                "date": "1991-09-29",
                "vol": 930.0,
                "amount": 1_355_000.0,
            },
            {
                "code": "000001",
                "date": "1991-09-30",
                "open": 14.55,
                "high": 14.65,
                "low": 14.5,
                "close": 14.6,
                "vol": 5.877471754e-39,
                "amount": 5.877471754e-39,
            },
            {
                "code": "000001",
                "date": "1991-10-01",
                "vol": 0.0,
                "amount": 0.0,
            },
            {
                "code": "000001",
                "date": "1991-10-02",
                "vol": 5.877471754e-39,
                "amount": 1.0,
            },
        ]
    )

    assert qfq.load_bfq_dates(kind="stock", code="000001", db=db) == [
        "1991-09-29",
        "1991-10-01",
        "1991-10-02",
    ]


def test_load_bfq_dates_excludes_rows_before_initial_share_capital_date():
    db = _DB(
        stock_day=[
            {"code": "000012", "date": "1992-01-07", "vol": 820.0},
            {"code": "000012", "date": "1992-02-28", "vol": 232.0},
        ],
        stock_xdxr=[
            {
                "code": "000012",
                "date": "1992-02-28",
                "category": 5,
                "shares_before": 0.0,
                "shares_after": 10_753.25,
            }
        ],
    )

    assert qfq.load_bfq_dates(kind="stock", code="000012", db=db) == ["1992-02-28"]


def test_later_capital_change_does_not_define_a_listing_boundary():
    db = _DB(
        stock_day=[{"code": "000012", "date": "1992-01-07"}],
        stock_xdxr=[
            {
                "code": "000012",
                "date": "1992-02-28",
                "category": 5,
                "shares_before": 100.0,
                "shares_after": 200.0,
            }
        ],
    )

    assert qfq.load_bfq_dates(kind="stock", code="000012", db=db) == ["1992-01-07"]


def test_stock_falls_back_to_xtdata_open_date_when_initial_capital_is_missing():
    db = _DB(
        stock_list=[{"code": "000028", "name": "Stock"}],
        stock_day=[
            {"code": "000028", "date": "1993-06-01"},
            {"code": "000028", "date": "1993-08-09"},
        ],
    )

    result = qfq.sync_stock_adj_all(
        target_date="1993-08-09",
        db=db,
        bars_loader=_loader_for({"000028": [("1993-08-09", 10.0, 0.0)]}),
        listing_date_loader=lambda _code: "1993-08-09",
    )

    coverage = result["by_scope"]["stock"]["coverage"]
    assert coverage["prelisting_rows_excluded"] == 1
    assert coverage["prelisting"][0]["listing_date"] == "1993-08-09"
    assert [row["date"] for row in db["stock_adj_qfq_a"].rows] == ["1993-08-09"]


def test_stock_initial_capital_date_takes_priority_over_xtdata_open_date():
    calls = []
    db = _DB(
        stock_list=[{"code": "000028", "name": "Stock"}],
        stock_day=[
            {"code": "000028", "date": "1993-08-09"},
            {"code": "000028", "date": "1993-09-01"},
        ],
        stock_xdxr=[
            {
                "code": "000028",
                "date": "1993-09-01",
                "category": 5,
                "shares_before": 0.0,
                "shares_after": 100.0,
            }
        ],
    )

    result = qfq.sync_stock_adj_all(
        target_date="1993-09-01",
        db=db,
        bars_loader=_loader_for({"000028": [("1993-09-01", 10.0, 0.0)]}),
        listing_date_loader=lambda code: calls.append(code) or "1993-08-09",
    )

    assert calls == []
    assert result["by_scope"]["stock"]["coverage"]["prelisting_rows_excluded"] == 1
    assert [row["date"] for row in db["stock_adj_qfq_a"].rows] == ["1993-09-01"]


def test_audit_checks_terminal_factor_and_recurrence():
    bars = _bars(
        [
            ("2026-01-02", 10.0, 0.0),
            ("2026-01-05", 9.0, 8.0),
        ]
    )
    valid = [
        {"code": "000001", "date": "2026-01-02", "adj": 0.8},
        {"code": "000001", "date": "2026-01-05", "adj": 1.0},
    ]
    assert qfq.audit_factor_snapshot(
        valid,
        expected_dates_by_code={"000001": ["2026-01-02", "2026-01-05"]},
        included_codes=["000001"],
        require_exact_dates=True,
        bars_by_code={"000001": bars},
    )["ok"]

    invalid = [dict(row) for row in valid]
    invalid[0]["adj"] = 0.9
    audit = qfq.audit_factor_snapshot(
        invalid,
        expected_dates_by_code={"000001": ["2026-01-02", "2026-01-05"]},
        included_codes=["000001"],
        require_exact_dates=True,
        bars_by_code={"000001": bars},
    )
    assert audit["recurrence_errors"] == [("000001", "2026-01-02")]

    invalid[-1]["adj"] = 0.5
    audit = qfq.audit_factor_snapshot(
        invalid,
        expected_dates_by_code={"000001": ["2026-01-02", "2026-01-05"]},
        included_codes=["000001"],
        require_exact_dates=True,
    )
    assert audit["terminal_not_one"] == ["000001"]


def test_source_audit_classifies_bfq_factor_without_xtdata_as_source_missing():
    audit = qfq.audit_factor_snapshot(
        [
            {"code": "000001", "date": "2026-01-02", "adj": 1.0},
            {"code": "000001", "date": "2026-01-05", "adj": 1.0},
        ],
        expected_dates_by_code={"000001": ["2026-01-02", "2026-01-05"]},
        included_codes=["000001"],
        require_exact_dates=True,
        bars_by_code={"000001": _bars([("2026-01-02", 10.0, 0.0)])},
    )

    assert audit["ok"] is False
    assert audit["source_missing_dates"] == [("000001", "2026-01-05")]
    assert audit["extra_dates"] == []


def test_bootstrap_builds_both_slots_before_atomic_marker_insert():
    dates = ["2026-01-02", "2026-01-05"]
    db = _stock_db(dates)
    loader = _loader_for({"000001": [(dates[0], 10.0, 0.0), (dates[1], 9.0, 8.0)]})

    result = qfq.sync_stock_adj_all(target_date=dates[-1], db=db, bars_loader=loader)

    assert result["by_scope"]["stock"]["mode"] == "bootstrap"
    rows_a = db["stock_adj_qfq_a"].rows
    rows_b = db["stock_adj_qfq_b"].rows
    assert rows_a == rows_b
    marker = db["qfq_ready"].rows[0]
    assert set(marker) == {
        "scope",
        "active_slot",
        "slots",
        "source",
        "schema_version",
    }
    assert marker["active_slot"] == "a"
    assert marker["slots"]["a"]["status"] == "ready"
    assert marker["slots"]["b"]["status"] == "ready"
    assert marker["slots"]["a"]["collection"] == "stock_adj_qfq_a"
    assert marker["slots"]["b"]["collection"] == "stock_adj_qfq_b"


def test_bootstrap_publishes_audited_source_empty_exclusions():
    target = "2026-01-02"
    db = _DB(
        stock_list=[
            {"code": code, "name": "Stock"} for code in ("000001", "000002", "000003")
        ],
        stock_day=[
            {"code": code, "date": target} for code in ("000001", "000002", "000003")
        ],
    )

    def loader(code, **_kwargs):
        if code in {"000002", "000003"}:
            return pd.DataFrame()
        return _bars([(target, 10.0, 0.0)])

    result = qfq.sync_stock_adj_all(target_date=target, db=db, bars_loader=loader)

    scope = result["by_scope"]["stock"]
    exclusions = [
        {"code": "000002", "reason": "source_empty_bars"},
        {"code": "000003", "reason": "source_empty_bars"},
    ]
    assert scope["codes"] == 1
    assert scope["coverage"]["source_empty_bars_excluded"] == 2
    assert scope["coverage"]["source_empty_bars"] == exclusions
    assert {row["code"] for row in db["stock_adj_qfq_a"].rows} == {"000001"}
    assert {row["code"] for row in db["stock_adj_qfq_b"].rows} == {"000001"}
    marker = db["qfq_ready"].rows[0]
    assert marker["slots"]["a"]["source_exclusions"] == exclusions
    assert marker["slots"]["b"]["source_exclusions"] == exclusions
    assert (
        marker["slots"]["a"]["source_exclusions"]
        is not marker["slots"]["b"]["source_exclusions"]
    )


def test_bootstrap_excludes_primary_history_prefix_no_progress():
    dates = ["2026-01-02", "2026-01-05"]
    codes = ("000001", "000002")
    db = _DB(
        stock_list=[{"code": code} for code in codes],
        stock_day=[{"code": code, "date": value} for code in codes for value in dates],
    )

    def loader(code, **_kwargs):
        if code == "000002":
            raise qfq.QFQSyncError(
                "history prefix unavailable",
                stats={"failure": "history_prefix_no_progress"},
            )
        return _bars([(dates[0], 10.0, 0.0), (dates[1], 10.0, 10.0)])

    result = qfq.sync_stock_adj_all(target_date=dates[-1], db=db, bars_loader=loader)

    exclusion = {"code": "000002", "reason": "source_prefix_unavailable"}
    scope = result["by_scope"]["stock"]
    assert scope["coverage"]["source_prefix_unavailable_excluded"] == 1
    assert scope["coverage"]["source_prefix_unavailable"] == [exclusion]
    for slot in ("a", "b"):
        assert scope["marker"]["slots"][slot]["source_exclusions"] == [exclusion]
        assert {row["code"] for row in db[f"stock_adj_qfq_{slot}"].rows} == {"000001"}
    full = qfq.audit_qfq_slot(
        scope="stock",
        slot="a",
        db=db,
        codes=["000002"],
        bars_loader=loader,
    )
    assert full["ok"] is True


def test_marker_source_exclusions_are_validated_and_backward_compatible():
    db = _stock_db(["2026-01-02"])
    qfq.sync_stock_adj_all(
        target_date="2026-01-02",
        db=db,
        bars_loader=_loader_for({"000001": [("2026-01-02", 10.0, 0.0)]}),
    )
    marker = db["qfq_ready"].rows[0]
    for slot in ("a", "b"):
        marker["slots"][slot].pop("source_exclusions")
    assert qfq.validate_qfq_marker(marker, scope="stock")["active_slot"] == "a"

    marker["slots"]["a"]["source_exclusions"] = [
        {"code": "000001", "reason": "source_adjustment_gap_unproven"}
    ]
    assert qfq.validate_qfq_marker(marker, scope="stock")["active_slot"] == "a"

    marker["slots"]["a"]["source_exclusions"] = [
        {"code": "000001", "reason": "source_empty_bars"},
        {"code": "000001", "reason": "source_empty_bars"},
    ]
    with pytest.raises(qfq.QFQSyncError, match="duplicated"):
        qfq.validate_qfq_marker(marker, scope="stock")

    marker["slots"]["a"]["source_exclusions"] = [
        {"code": "000001", "reason": "prefix_gap"}
    ]
    with pytest.raises(qfq.QFQSyncError, match="reason is invalid"):
        qfq.validate_qfq_marker(marker, scope="stock")


def test_source_empty_exclusion_structure_and_full_audits_are_strict():
    target = "2026-01-02"
    db = _DB(
        stock_list=[{"code": "000001"}, {"code": "000002"}],
        stock_day=[
            {"code": "000001", "date": target},
            {"code": "000002", "date": target},
        ],
    )

    def bootstrap_loader(code, **_kwargs):
        return _bars([(target, 10.0, 0.0)]) if code == "000001" else pd.DataFrame()

    qfq.sync_stock_adj_all(target_date=target, db=db, bars_loader=bootstrap_loader)

    structure = qfq.audit_qfq_slot(scope="stock", slot="a", db=db, codes=["000002"])
    assert structure["ok"] is True
    assert structure["codes"] == 1
    assert structure["source_exclusions"] == [
        {"code": "000002", "reason": "source_empty_bars"}
    ]

    full = qfq.audit_qfq_slot(
        scope="stock",
        slot="a",
        db=db,
        codes=["000002"],
        bars_loader=lambda *_args, **_kwargs: pd.DataFrame(),
    )
    assert full["ok"] is True

    recovered = qfq.audit_qfq_slot(
        scope="stock",
        slot="a",
        db=db,
        codes=["000002"],
        bars_loader=lambda *_args, **_kwargs: _bars([(target, 10.0, 0.0)]),
    )
    assert recovered["ok"] is False
    assert recovered["failures"][0]["audit"] == {
        "ok": False,
        "stale_source_exclusion": True,
        "rebuild_required": True,
        "expected_reason": "source_empty_bars",
        "observed_reason": None,
    }

    db["stock_adj_qfq_a"].rows.append({"code": "000002", "date": target, "adj": 1.0})
    residue = qfq.audit_qfq_slot(scope="stock", slot="a", db=db, codes=["000002"])
    assert residue["ok"] is False
    assert residue["failures"][0]["audit"]["source_exclusion_residue"] == 1


def test_source_exclusion_audit_collects_unclassified_source_errors():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    codes = ("000002", "000003")
    db = _DB(
        stock_list=[{"code": code} for code in codes],
        stock_day=[{"code": code, "date": value} for code in codes for value in dates],
    )
    exclusions = [
        {"code": code, "reason": "source_adjustment_gap_unproven"} for code in codes
    ]

    def loader(code, **_kwargs):
        if code == "000002":
            return _bars([(dates[-1], 10.0, 0.0)])
        return pd.DataFrame()

    audit = qfq.audit_qfq_slot(
        scope="stock",
        slot="a",
        db=db,
        factor_asof=dates[-1],
        bars_loader=loader,
        source_exclusions=exclusions,
    )

    assert audit["ok"] is False
    assert audit["failed"] == 2
    failures = {item["code"]: item["audit"] for item in audit["failures"]}
    assert failures["000002"] == {
        "ok": False,
        "stale_source_exclusion": True,
        "rebuild_required": True,
        "expected_reason": "source_adjustment_gap_unproven",
        "observed_reason": None,
    }
    assert failures["000003"]["observed_reason"] == "source_empty_bars"


def test_full_scope_audit_includes_exclusions_outside_current_universe():
    target = "2026-01-02"
    db = _stock_db([target])
    loader = _loader_for({"000001": [(target, 10.0, 0.0)]})
    qfq.sync_stock_adj_all(target_date=target, db=db, bars_loader=loader)
    marker = db["qfq_ready"].rows[0]
    outside = {"code": "000999", "reason": "source_empty_bars"}
    marker["slots"]["a"]["source_exclusions"] = [outside]
    db["stock_adj_qfq_a"].rows.append({"code": "000999", "date": target, "adj": 1.0})

    residue = qfq.audit_qfq_slot(scope="stock", slot="a", db=db)
    assert residue["codes"] == 2
    assert residue["failures"][0] == {
        "code": "000999",
        "audit": {"ok": False, "source_exclusion_residue": 1},
    }

    db["stock_adj_qfq_a"].rows = [
        row for row in db["stock_adj_qfq_a"].rows if row["code"] != "000999"
    ]
    full = qfq.audit_qfq_slot(scope="stock", slot="a", db=db, bars_loader=loader)
    assert full["codes"] == 2
    assert full["failures"][0]["code"] == "000999"
    assert full["failures"][0]["audit"] == {
        "ok": False,
        "stale_source_exclusion": True,
        "rebuild_required": True,
        "expected_reason": "source_empty_bars",
        "observed_reason": None,
    }

    requested_current = qfq.audit_qfq_slot(
        scope="stock", slot="a", db=db, codes=["000001"], bars_loader=loader
    )
    assert requested_current["ok"] is True
    assert requested_current["codes"] == 1
    requested_exclusion = qfq.audit_qfq_slot(
        scope="stock", slot="a", db=db, codes=["000999"]
    )
    assert requested_exclusion["ok"] is True
    assert requested_exclusion["codes"] == 1


def test_empty_front_ratio_proof_remains_fail_closed():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    db = _stock_db(dates)
    none_loader = _loader_for({"000001": [(dates[0], 10.0, 0.0), (dates[2], 8.0, 9.0)]})

    with pytest.raises(qfq.QFQSyncError, match="returned no daily bars") as caught:
        qfq.sync_stock_adj_all(
            target_date=dates[-1],
            db=db,
            bars_loader=none_loader,
            front_ratio_loader=lambda *_args, **_kwargs: pd.DataFrame(),
        )

    assert caught.value.stats["source_role"] == "front_ratio_proof"
    assert not db["qfq_ready"].rows


def test_history_prefix_no_progress_from_front_ratio_proof_remains_fail_closed():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    db = _stock_db(dates)
    none_loader = _loader_for({"000001": [(dates[0], 10.0, 0.0), (dates[2], 8.0, 9.0)]})

    def front_loader(*_args, **_kwargs):
        raise qfq.QFQSyncError(
            "proof history prefix unavailable",
            stats={"failure": "history_prefix_no_progress"},
        )

    with pytest.raises(qfq.QFQSyncError) as caught:
        qfq.sync_stock_adj_all(
            target_date=dates[-1],
            db=db,
            bars_loader=none_loader,
            front_ratio_loader=front_loader,
        )

    assert caught.value.stats["failure"] == "history_prefix_no_progress"
    assert caught.value.stats["source_role"] == "front_ratio_proof"
    assert not db["qfq_ready"].rows


def test_bootstrap_computes_on_xtdata_superset_then_projects_to_bfq_axis():
    expected_dates = ["2026-01-02", "2026-01-06"]
    db = _stock_db(expected_dates)
    loader = _loader_for(
        {
            "000001": [
                ("2026-01-02", 10.0, 0.0),
                ("2026-01-05", 9.0, 8.0),
                ("2026-01-06", 9.0, 9.0),
            ]
        }
    )

    qfq.sync_stock_adj_all(target_date=expected_dates[-1], db=db, bars_loader=loader)

    rows = db["stock_adj_qfq_a"].rows
    assert [row["date"] for row in rows] == expected_dates
    assert [row["adj"] for row in rows] == pytest.approx([0.8, 1.0])
    assert qfq.audit_qfq_slot(scope="stock", slot="a", db=db, bars_loader=loader)["ok"]


def test_bootstrap_fails_when_valid_bfq_date_is_missing_from_xtdata():
    dates = ["2026-01-02", "2026-01-05"]
    db = _stock_db(dates)
    loader = _loader_for({"000001": [(dates[0], 10.0, 0.0)]})

    with pytest.raises(qfq.QFQSyncError, match="unbounded XTData source gap"):
        qfq.sync_stock_adj_all(target_date=dates[-1], db=db, bars_loader=loader)

    assert not db["qfq_ready"].rows


def test_bootstrap_bridges_bounded_source_gap_with_constant_front_ratio():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    db = _stock_db(dates)
    none_loader = _loader_for({"000001": [(dates[0], 10.0, 0.0), (dates[2], 8.0, 9.0)]})
    front_ratio_loader = _loader_for(
        {"000001": [(dates[0], 5.0, 0.0), (dates[2], 4.0, 4.5)]}
    )

    result = qfq.sync_stock_adj_all(
        target_date=dates[-1],
        db=db,
        bars_loader=none_loader,
        front_ratio_loader=front_ratio_loader,
    )

    rows = db["stock_adj_qfq_a"].rows
    assert [row["date"] for row in rows] == dates
    assert [row["adj"] for row in rows] == [1.0, 1.0, 1.0]
    coverage = result["by_scope"]["stock"]["coverage"]
    assert coverage["source_gap_rows_bridged"] == 1
    assert coverage["codes_with_source_gaps"] == 1
    assert coverage["source_gaps"][0]["windows"][0]["dates"] == [dates[1]]

    audit = qfq.audit_qfq_slot(
        scope="stock",
        slot="a",
        db=db,
        bars_loader=none_loader,
        front_ratio_loader=front_ratio_loader,
    )
    assert audit["ok"]
    assert audit["coverage"]["source_gap_rows_bridged"] == 1


def test_source_gap_that_crosses_adjustment_has_stable_failure_code():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    none_loader = _loader_for({"000001": [(dates[0], 10.0, 0.0), (dates[2], 8.0, 9.0)]})
    changed_front_ratio = _loader_for(
        {"000001": [(dates[0], 5.0, 0.0), (dates[2], 3.2, 4.5)]}
    )

    with pytest.raises(qfq.QFQSyncError, match="crosses an adjustment") as caught:
        qfq._project_preclose_adj_to_bfq_dates(
            none_loader("000001", start_time=dates[0], end_time=dates[-1]),
            code="000001",
            expected_dates=dates,
            front_ratio_bars=changed_front_ratio(
                "000001", start_time=dates[0], end_time=dates[-1]
            ),
        )

    assert caught.value.stats["failure"] == "source_adjustment_gap_unproven"


def test_bootstrap_excludes_unproven_adjustment_gap_and_audits_same_reason():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    codes = ("000001", "000002")
    db = _DB(
        stock_list=[{"code": code} for code in codes],
        stock_day=[{"code": code, "date": value} for code in codes for value in dates],
    )
    none_payload = {
        "000001": [
            (dates[0], 10.0, 0.0),
            (dates[1], 10.0, 10.0),
            (dates[2], 10.0, 10.0),
        ],
        "000002": [(dates[0], 10.0, 0.0), (dates[2], 8.0, 9.0)],
    }
    front_payload = {
        "000001": [
            (dates[0], 5.0, 0.0),
            (dates[1], 5.0, 5.0),
            (dates[2], 5.0, 5.0),
        ],
        "000002": [(dates[0], 5.0, 0.0), (dates[2], 3.2, 4.5)],
    }
    none_loader = _loader_for(none_payload)
    front_loader = _loader_for(front_payload)

    result = qfq.sync_stock_adj_all(
        target_date=dates[-1],
        db=db,
        bars_loader=none_loader,
        front_ratio_loader=front_loader,
    )

    exclusion = {"code": "000002", "reason": "source_adjustment_gap_unproven"}
    scope = result["by_scope"]["stock"]
    assert scope["coverage"]["source_adjustment_gap_unproven_excluded"] == 1
    assert scope["coverage"]["source_adjustment_gap_unproven"] == [exclusion]
    assert {row["code"] for row in db["stock_adj_qfq_a"].rows} == {"000001"}
    assert {row["code"] for row in db["stock_adj_qfq_b"].rows} == {"000001"}
    for slot in ("a", "b"):
        assert scope["marker"]["slots"][slot]["source_exclusions"] == [exclusion]

    structure = qfq.audit_qfq_slot(scope="stock", slot="a", db=db, codes=["000002"])
    assert structure["ok"] is True
    assert structure["coverage"]["source_adjustment_gap_unproven"] == [exclusion]
    full = qfq.audit_qfq_slot(
        scope="stock",
        slot="a",
        db=db,
        codes=["000002"],
        bars_loader=none_loader,
        front_ratio_loader=front_loader,
    )
    assert full["ok"] is True

    none_payload["000002"] = []
    different_reason = qfq.audit_qfq_slot(
        scope="stock",
        slot="a",
        db=db,
        codes=["000002"],
        bars_loader=none_loader,
        front_ratio_loader=front_loader,
    )
    assert different_reason["ok"] is False
    assert different_reason["failures"][0]["audit"] == {
        "ok": False,
        "stale_source_exclusion": True,
        "rebuild_required": True,
        "expected_reason": "source_adjustment_gap_unproven",
        "observed_reason": "source_empty_bars",
    }

    none_payload["000002"] = [(dates[0], 10.0, 0.0), (dates[2], 8.0, 9.0)]
    front_payload["000002"] = [(dates[0], 5.0, 0.0), (dates[2], 4.0, 4.5)]
    recovered_proof = qfq.audit_qfq_slot(
        scope="stock",
        slot="a",
        db=db,
        codes=["000002"],
        bars_loader=none_loader,
        front_ratio_loader=front_loader,
    )
    assert recovered_proof["ok"] is False
    assert recovered_proof["failures"][0]["audit"] == {
        "ok": False,
        "stale_source_exclusion": True,
        "rebuild_required": True,
        "expected_reason": "source_adjustment_gap_unproven",
        "observed_reason": None,
    }


def test_bootstrap_rejects_unbounded_source_gap():
    dates = ["2026-01-02", "2026-01-05"]
    db = _stock_db(dates)

    with pytest.raises(qfq.QFQSyncError, match="unbounded XTData source gap"):
        qfq.sync_stock_adj_all(
            target_date=dates[-1],
            db=db,
            bars_loader=_loader_for({"000001": [(dates[1], 10.0, 0.0)]}),
        )

    assert not db["qfq_ready"].rows


def test_bootstrap_reports_prelisting_bfq_exclusion():
    db = _DB(
        stock_list=[{"code": "000012", "name": "Stock"}],
        stock_day=[
            {"code": "000012", "date": "1992-01-07", "vol": 820.0},
            {"code": "000012", "date": "1992-02-28", "vol": 232.0},
        ],
        stock_xdxr=[
            {
                "code": "000012",
                "date": "1992-02-28",
                "category": 5,
                "shares_before": 0.0,
                "shares_after": 10_753.25,
            }
        ],
    )

    result = qfq.sync_stock_adj_all(
        target_date="1992-02-28",
        db=db,
        bars_loader=_loader_for({"000012": [("1992-02-28", 10.5, 0.0)]}),
    )

    coverage = result["by_scope"]["stock"]["coverage"]
    assert coverage["prelisting_rows_excluded"] == 1
    assert coverage["codes_with_prelisting_rows"] == 1
    assert coverage["prelisting"] == [
        {
            "code": "000012",
            "listing_date": "1992-02-28",
            "rows": 1,
            "dates": ["1992-01-07"],
        }
    ]
    assert [row["date"] for row in db["stock_adj_qfq_a"].rows] == ["1992-02-28"]


def test_bootstrap_skips_sentinel_only_etf_with_audited_reason():
    sentinel = 5.877471754e-39
    db = _DB(
        etf_list=[
            {"code": "158000", "name": "Placeholder ETF"},
            {"code": "510050", "name": "Tradable ETF"},
        ],
        index_day=[
            {
                "code": "158000",
                "date": "2026-07-30",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "vol": sentinel,
                "amount": sentinel,
            },
            {
                "code": "158000",
                "date": "2026-07-31",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "vol": sentinel,
                "amount": sentinel,
            },
            {
                "code": "510050",
                "date": "2026-07-31",
                "vol": 100.0,
                "amount": 250.0,
            },
        ],
    )
    calls = []

    def loader(code, *, start_time, end_time):
        calls.append((code, start_time, end_time))
        return _bars([("2026-07-31", 2.5, 0.0)])

    result = qfq.sync_etf_adj_all(target_date="2026-07-31", db=db, bars_loader=loader)

    assert [call[0] for call in calls] == ["510050"]
    coverage = result["by_scope"]["etf"]["coverage"]
    assert coverage["sentinel_rows_excluded"] == 2
    assert coverage["codes_with_sentinel_rows"] == 1
    assert coverage["skipped_codes"] == 1
    assert coverage["skipped"][0] == {
        "code": "158000",
        "reason": "sentinel_only_bfq_history",
        "sentinel_rows": 2,
    }


def test_bootstrap_does_not_classify_near_miss_sentinel_as_lifecycle_skip():
    sentinel = 5.877471754e-39
    db = _DB(
        etf_list=[
            {"code": "159001", "name": "Control ETF"},
            {"code": "510050", "name": "Tradable ETF"},
        ],
        index_day=[
            {"code": "159001", "date": "2026-07-31"},
            {
                "code": "510050",
                "date": "2026-07-31",
                "vol": sentinel,
                "amount": 1.0,
            },
        ],
    )
    empty = pd.DataFrame(index=["510050.SH"])

    result = qfq.sync_etf_adj_all(
        target_date="2026-07-31",
        db=db,
        bars_loader=lambda code, **_kwargs: (
            _bars([("2026-07-31", 1.0, 0.0)])
            if code == "159001"
            else {
                "time": empty,
                "close": empty,
                "preClose": empty,
            }
        ),
    )

    coverage = result["by_scope"]["etf"]["coverage"]
    assert coverage["sentinel_rows_excluded"] == 0
    assert coverage["source_empty_bars"] == [
        {"code": "510050", "reason": "source_empty_bars"}
    ]

    assert db["qfq_ready"].rows[0]["active_slot"] == "a"


def test_bootstrap_classifies_nontrading_history_before_open_date_as_terminal():
    loaded_codes = []
    sentinel = 5.877471754e-39
    db = _DB(
        etf_list=[
            {"code": "161022", "name": "Converted ETF"},
            {"code": "510050", "name": "Tradable ETF"},
        ],
        index_day=[
            {
                "code": "161022",
                "date": "2026-07-30",
                "vol": sentinel,
                "amount": sentinel,
            },
            {
                "code": "161022",
                "date": "2026-07-31",
                "vol": sentinel,
                "amount": sentinel,
            },
            {"code": "161022", "date": "2020-01-02"},
            {"code": "161022", "date": "2020-01-03"},
            {"code": "510050", "date": "2026-07-31"},
        ],
    )

    def load_bars(code, *, start_time, end_time):
        loaded_codes.append(code)
        return _bars([("2026-07-31", 2.5, 0.0)])

    result = qfq.sync_etf_adj_all(
        target_date="2026-07-31",
        db=db,
        bars_loader=load_bars,
        listing_date_loader=lambda code: {
            "open_date": "2024-01-31" if code == "161022" else "2005-02-23",
            "is_trading": False,
        },
    )

    coverage = result["by_scope"]["etf"]["coverage"]
    assert loaded_codes == ["510050"]
    assert coverage["sentinel_rows_excluded"] == 2
    assert coverage["prelisting_rows_excluded"] == 0
    assert coverage["terminal_history_rows_excluded"] == 2
    assert coverage["terminal_history"][0]["reason"] == "nontrading_terminal_history"
    assert coverage["skipped"] == [
        {
            "code": "161022",
            "reason": "nontrading_terminal_history",
            "sentinel_rows": 2,
            "terminal_history_rows": 2,
            "open_date": "2024-01-31",
        }
    ]


def test_open_date_after_bfq_without_terminal_proof_uses_source_empty_exclusion():
    db = _DB(
        etf_list=[
            {"code": "159001", "name": "Control ETF"},
            {"code": "161022", "name": "ETF"},
        ],
        index_day=[
            {"code": "159001", "date": "2026-07-31"},
            {"code": "161022", "date": "2024-01-30"},
        ],
    )

    result = qfq.sync_etf_adj_all(
        target_date="2026-07-31",
        db=db,
        bars_loader=lambda code, **_kwargs: (
            _bars([("2026-07-31", 1.0, 0.0)]) if code == "159001" else pd.DataFrame()
        ),
        listing_date_loader=lambda code: {
            "open_date": "2024-01-31" if code == "161022" else "2005-02-23",
            "is_trading": True,
        },
    )

    coverage = result["by_scope"]["etf"]["coverage"]
    assert coverage["terminal_history_rows_excluded"] == 0
    assert coverage["prelisting_rows_excluded"] == 0
    assert coverage["source_empty_bars"] == [
        {"code": "161022", "reason": "source_empty_bars"}
    ]


def test_missing_etf_open_date_keeps_prefix_bfq_rows_fail_closed():
    db = _DB(
        etf_list=[{"code": "161022", "name": "ETF"}],
        index_day=[
            {"code": "161022", "date": "2020-01-02"},
            {"code": "161022", "date": "2024-01-31"},
        ],
    )

    with pytest.raises(qfq.QFQSyncError, match="unbounded XTData source gap"):
        qfq.sync_etf_adj_all(
            target_date="2024-01-31",
            db=db,
            bars_loader=_loader_for({"161022": [("2024-01-31", 1.0, 0.0)]}),
            listing_date_loader=lambda _code: None,
        )

    assert not db["qfq_ready"].rows


def test_audit_rejects_factor_rows_for_terminal_history():
    db = _DB(
        etf_list=[
            {"code": "161022", "name": "Converted ETF"},
            {"code": "510050", "name": "Tradable ETF"},
        ],
        index_day=[
            {"code": "161022", "date": "2020-01-02"},
            {
                "code": "161022",
                "date": "2026-07-31",
                "vol": 5.877471754e-39,
                "amount": 5.877471754e-39,
            },
            {"code": "510050", "date": "2026-07-31"},
        ],
        etf_adj_qfq_a=[
            {"code": "161022", "date": "2020-01-02", "adj": 1.0},
            {"code": "510050", "date": "2026-07-31", "adj": 1.0},
        ],
    )

    audit = qfq.audit_qfq_slot(
        scope="etf",
        slot="a",
        db=db,
        factor_asof="2026-07-31",
        listing_date_loader=lambda code: {
            "open_date": "2024-01-31" if code == "161022" else "2005-02-23",
            "is_trading": code != "161022",
        },
    )

    assert audit["ok"] is False
    assert audit["failures"][0]["code"] == "161022"
    assert audit["failures"][0]["audit"]["extra_dates"] == [("161022", "2020-01-02")]


def test_bootstrap_failure_never_creates_ready_marker():
    db = _stock_db(["2026-01-02"])

    with pytest.raises(RuntimeError, match="download failed"):
        qfq.sync_stock_adj_all(
            target_date="2026-01-02",
            db=db,
            bars_loader=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("download failed")
            ),
        )

    assert not db["qfq_ready"].rows
    assert not db["qfq_writer_locks"].rows


def test_live_writer_lease_blocks_bootstrap_before_shadow_write():
    now = datetime(2026, 1, 2, 8, 0, tzinfo=timezone.utc)
    db = _stock_db(["2026-01-02"])
    db["qfq_writer_locks"].rows.append(
        {
            "scope": "stock",
            "owner_id": "other-writer",
            "acquired_at": "2026-01-02T07:55:00Z",
            "updated_at": "2026-01-02T07:59:00Z",
            "expires_at": "2026-01-02T08:30:00Z",
        }
    )

    with pytest.raises(qfq.QFQSyncError, match="writer lease is held"):
        qfq.sync_stock_adj_all(
            target_date="2026-01-02",
            db=db,
            bars_loader=_loader_for({"000001": [("2026-01-02", 10.0, 0.0)]}),
            now_provider=lambda: now,
        )

    assert not db["stock_adj_qfq_a"].rows
    assert not db["qfq_ready"].rows


def test_stale_writer_lease_is_reclaimed_and_released():
    now = datetime(2026, 1, 2, 8, 0, tzinfo=timezone.utc)
    db = _stock_db(["2026-01-02"])
    db["qfq_writer_locks"].rows.append(
        {
            "scope": "stock",
            "owner_id": "crashed-writer",
            "acquired_at": "2026-01-02T06:00:00Z",
            "updated_at": "2026-01-02T06:00:00Z",
            "expires_at": "2026-01-02T07:00:00Z",
        }
    )

    qfq.sync_stock_adj_all(
        target_date="2026-01-02",
        db=db,
        bars_loader=_loader_for({"000001": [("2026-01-02", 10.0, 0.0)]}),
        now_provider=lambda: now,
    )

    assert qfq.resolve_active_slot(scope="stock", db=db)["slot"] == "a"
    assert not db["qfq_writer_locks"].rows


def test_writer_lease_heartbeats_while_one_loader_call_is_blocked(monkeypatch):
    db = _stock_db(["2026-01-02"])
    loader_started = threading.Event()
    background_refresh = threading.Event()
    main_thread = threading.current_thread()
    original_refresh = qfq._refresh_writer_lease

    def observe_refresh(**kwargs):
        if loader_started.is_set() and threading.current_thread() is not main_thread:
            background_refresh.set()
        return original_refresh(**kwargs)

    def blocking_loader(*_args, **_kwargs):
        loader_started.set()
        assert background_refresh.wait(timeout=1.0)
        return _bars([("2026-01-02", 10.0, 0.0)])

    monkeypatch.setattr(qfq, "_refresh_writer_lease", observe_refresh)

    qfq.sync_stock_adj_all(
        target_date="2026-01-02",
        db=db,
        bars_loader=blocking_loader,
        writer_heartbeat_seconds=0.01,
    )

    assert background_refresh.is_set()
    assert not db["qfq_writer_locks"].rows


def test_writer_lease_fences_publish_from_background_heartbeat_failure(monkeypatch):
    refresh_started = threading.Event()
    allow_failure = threading.Event()
    published = threading.Event()
    errors = []

    def failing_refresh(**_kwargs):
        refresh_started.set()
        assert allow_failure.wait(timeout=1.0)
        raise RuntimeError("lease lost")

    monkeypatch.setattr(qfq, "_refresh_writer_lease", failing_refresh)
    heartbeat = qfq._WriterLeaseHeartbeat(
        db=object(),
        scope="stock",
        owner_id="writer",
        lease_seconds=30,
        heartbeat_seconds=0.01,
    )
    heartbeat.start()
    assert refresh_started.wait(timeout=1.0)

    def run_publish():
        try:
            heartbeat.run_fenced_publish(lambda: published.set())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    publish_thread = threading.Thread(target=run_publish)
    publish_thread.start()
    allow_failure.set()
    publish_thread.join(timeout=1.0)
    heartbeat.stop()

    assert not publish_thread.is_alive()
    assert not published.is_set()
    assert len(errors) == 1
    assert isinstance(errors[0], qfq.QFQSyncError)


def test_bootstrap_heartbeat_failure_before_publish_does_not_create_marker(monkeypatch):
    db = _stock_db(["2026-01-02"])

    def fail_fenced_publish(self, callback):
        self._failure = RuntimeError("lease lost")
        return original_fenced_publish(self, callback)

    original_fenced_publish = qfq._WriterLeaseHeartbeat.run_fenced_publish
    monkeypatch.setattr(
        qfq._WriterLeaseHeartbeat,
        "run_fenced_publish",
        fail_fenced_publish,
    )

    with pytest.raises(qfq.QFQSyncError, match="heartbeat failed"):
        qfq.sync_stock_adj_all(
            target_date="2026-01-02",
            db=db,
            bars_loader=_loader_for({"000001": [("2026-01-02", 10.0, 0.0)]}),
        )

    assert not db["qfq_ready"].rows


def test_update_heartbeat_failure_before_publish_keeps_active_marker(monkeypatch):
    dates = ["2026-01-02", "2026-01-05"]
    payload = {"000001": [(dates[0], 10.0, 0.0)]}
    db = _stock_db(dates[:1])
    loader = _loader_for(payload)
    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=loader)
    active_before = qfq.resolve_active_slot(scope="stock", db=db)
    payload["000001"].append((dates[1], 10.0, 10.0))
    db["stock_day"].rows.append({"code": "000001", "date": dates[1]})

    def fail_fenced_publish(self, callback):
        self._failure = RuntimeError("lease lost")
        return original_fenced_publish(self, callback)

    original_fenced_publish = qfq._WriterLeaseHeartbeat.run_fenced_publish
    monkeypatch.setattr(
        qfq._WriterLeaseHeartbeat,
        "run_fenced_publish",
        fail_fenced_publish,
    )

    with pytest.raises(qfq.QFQSyncError, match="heartbeat failed"):
        qfq.sync_stock_adj_all(
            target_date=dates[1],
            db=db,
            bars_loader=loader,
            min_grace_seconds=0,
        )

    active_after = qfq.resolve_active_slot(scope="stock", db=db)
    assert active_after["slot"] == active_before["slot"]
    assert active_after["factor_asof"] == active_before["factor_asof"]


def test_inactive_slot_catches_up_from_its_own_terminal_without_writing_active():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    rows = [
        (date, 10.0, 0.0 if index == 0 else 10.0) for index, date in enumerate(dates)
    ]
    db = _stock_db(dates[:1])
    loader = _loader_for({"000001": rows})
    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=loader)
    db["stock_day"].rows.extend({"code": "000001", "date": date} for date in dates[1:])
    active_writes_before = db["stock_adj_qfq_a"].writes

    result = qfq.sync_stock_adj_all(
        target_date=dates[-1],
        db=db,
        bars_loader=loader,
        min_grace_seconds=0,
    )

    assert result["by_scope"]["stock"]["stats"]["incremental"] == 1
    assert db["stock_adj_qfq_a"].writes == active_writes_before
    assert [row["date"] for row in db["stock_adj_qfq_b"].rows] == dates
    assert qfq.resolve_active_slot(scope="stock", db=db)["slot"] == "b"


def test_incremental_update_projects_xtdata_superset_to_bfq_dates():
    bfq_dates = ["2026-01-02", "2026-01-06"]
    payload = {"000001": [(bfq_dates[0], 10.0, 0.0)]}
    db = _stock_db(bfq_dates[:1])
    loader = _loader_for(payload)
    qfq.sync_stock_adj_all(target_date=bfq_dates[0], db=db, bars_loader=loader)
    payload["000001"] = [
        (bfq_dates[0], 10.0, 0.0),
        ("2026-01-05", 11.0, 10.0),
        (bfq_dates[1], 12.0, 11.0),
    ]
    db["stock_day"].rows.append({"code": "000001", "date": bfq_dates[1]})

    result = qfq.sync_stock_adj_all(
        target_date=bfq_dates[1],
        db=db,
        bars_loader=loader,
        min_grace_seconds=0,
    )

    assert result["by_scope"]["stock"]["stats"]["incremental"] == 1
    assert [row["date"] for row in db["stock_adj_qfq_b"].rows] == bfq_dates
    assert [row["adj"] for row in db["stock_adj_qfq_b"].rows] == [1.0, 1.0]


def test_incremental_update_bridges_bounded_source_gap():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    none_payload = {"000001": [(dates[0], 10.0, 0.0)]}
    front_payload = {"000001": [(dates[0], 5.0, 0.0)]}
    db = _stock_db(dates[:1])
    none_loader = _loader_for(none_payload)
    front_loader = _loader_for(front_payload)
    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=none_loader)
    db["stock_day"].rows.extend(
        {"code": "000001", "date": value} for value in dates[1:]
    )
    none_payload["000001"] = [(dates[0], 10.0, 0.0), (dates[2], 8.0, 9.0)]
    front_payload["000001"] = [(dates[0], 5.0, 0.0), (dates[2], 4.0, 4.5)]

    result = qfq.sync_stock_adj_all(
        target_date=dates[-1],
        db=db,
        bars_loader=none_loader,
        front_ratio_loader=front_loader,
        min_grace_seconds=0,
    )

    assert result["by_scope"]["stock"]["stats"]["incremental"] == 1
    assert result["by_scope"]["stock"]["coverage"]["source_gap_rows_bridged"] == 1
    assert [row["date"] for row in db["stock_adj_qfq_b"].rows] == dates
    assert [row["adj"] for row in db["stock_adj_qfq_b"].rows] == [1.0, 1.0, 1.0]


def test_update_excludes_unproven_adjustment_gap_from_inactive_slot():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    codes = ("000001", "000002")
    db = _DB(
        stock_list=[{"code": code} for code in codes],
        stock_day=[{"code": code, "date": dates[0]} for code in codes],
    )
    none_payload = {code: [(dates[0], 10.0, 0.0)] for code in codes}
    front_payload = {code: [(dates[0], 5.0, 0.0)] for code in codes}
    none_loader = _loader_for(none_payload)
    front_loader = _loader_for(front_payload)
    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=none_loader)
    db["stock_day"].rows.extend(
        {"code": code, "date": value} for code in codes for value in dates[1:]
    )
    none_payload["000001"] = [
        (dates[0], 10.0, 0.0),
        (dates[1], 10.0, 10.0),
        (dates[2], 10.0, 10.0),
    ]
    none_payload["000002"] = [(dates[0], 10.0, 0.0), (dates[2], 8.0, 9.0)]
    front_payload["000002"] = [(dates[0], 5.0, 0.0), (dates[2], 3.2, 4.5)]

    result = qfq.sync_stock_adj_all(
        target_date=dates[-1],
        db=db,
        bars_loader=none_loader,
        front_ratio_loader=front_loader,
        min_grace_seconds=0,
    )

    exclusion = {"code": "000002", "reason": "source_adjustment_gap_unproven"}
    scope = result["by_scope"]["stock"]
    assert scope["stats"]["source_adjustment_gap_unproven_excluded"] == 1
    assert scope["coverage"]["source_adjustment_gap_unproven"] == [exclusion]
    assert scope["marker"]["active_slot"] == "b"
    assert scope["marker"]["slots"]["a"]["source_exclusions"] == []
    assert scope["marker"]["slots"]["b"]["source_exclusions"] == [exclusion]
    assert {row["code"] for row in db["stock_adj_qfq_a"].rows} == set(codes)
    assert {row["code"] for row in db["stock_adj_qfq_b"].rows} == {"000001"}


def test_update_excludes_primary_history_prefix_no_progress():
    dates = ["2026-01-02", "2026-01-05"]
    codes = ("000001", "000002")
    db = _DB(
        stock_list=[{"code": code} for code in codes],
        stock_day=[{"code": code, "date": dates[0]} for code in codes],
    )
    prefix_unavailable = False

    def loader(code, **_kwargs):
        if prefix_unavailable and code == "000002":
            raise qfq.QFQSyncError(
                "history prefix unavailable",
                stats={"failure": "history_prefix_no_progress"},
            )
        return _bars(
            [(value, 10.0, 0.0 if value == dates[0] else 10.0) for value in dates]
        )

    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=loader)
    db["stock_day"].rows.extend({"code": code, "date": dates[1]} for code in codes)
    prefix_unavailable = True

    result = qfq.sync_stock_adj_all(
        target_date=dates[-1],
        db=db,
        bars_loader=loader,
        min_grace_seconds=0,
    )

    exclusion = {"code": "000002", "reason": "source_prefix_unavailable"}
    scope = result["by_scope"]["stock"]
    assert scope["stats"]["source_prefix_unavailable_excluded"] == 1
    assert scope["coverage"]["source_prefix_unavailable"] == [exclusion]
    assert scope["marker"]["slots"]["a"]["source_exclusions"] == []
    assert scope["marker"]["slots"]["b"]["source_exclusions"] == [exclusion]
    assert {row["code"] for row in db["stock_adj_qfq_b"].rows} == {"000001"}


def test_update_rejects_snapshot_when_all_codes_are_source_excluded():
    dates = ["2026-01-02", "2026-01-05"]
    codes = ("000001", "000002")
    db = _DB(
        stock_list=[{"code": code} for code in codes],
        stock_day=[{"code": code, "date": dates[0]} for code in codes],
    )
    prefix_unavailable = False

    def loader(_code, **_kwargs):
        if prefix_unavailable:
            raise qfq.QFQSyncError(
                "history prefix unavailable",
                stats={"failure": "history_prefix_no_progress"},
            )
        return _bars([(dates[0], 10.0, 0.0)])

    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=loader)
    db["stock_day"].rows.extend({"code": code, "date": dates[1]} for code in codes)
    prefix_unavailable = True

    with pytest.raises(qfq.QFQSyncError, match="no included QFQ codes") as caught:
        qfq.sync_stock_adj_all(
            target_date=dates[-1],
            db=db,
            bars_loader=loader,
            min_grace_seconds=0,
        )

    assert len(caught.value.stats["source_exclusions"]) == 2
    marker = db["qfq_ready"].rows[0]
    assert marker["active_slot"] == "a"
    assert marker["slots"]["a"]["status"] == "ready"
    assert marker["slots"]["b"]["status"] == "failed"
    assert {row["code"] for row in db["stock_adj_qfq_a"].rows} == set(codes)
    assert not db["stock_adj_qfq_b"].rows


def test_incremental_update_reloads_context_when_tail_starts_on_source_gap():
    dates = [
        "2026-01-02",
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-08",
        "2026-01-09",
        "2026-01-12",
    ]
    none_payload = {
        "000001": [
            (value, 10.0, 0.0 if index == 0 else 10.0)
            for index, value in enumerate(dates)
            if value != dates[3]
        ]
    }
    front_payload = {
        "000001": [
            (value, 5.0, 0.0 if index == 0 else 5.0)
            for index, value in enumerate(dates)
            if value != dates[3]
        ]
    }
    db = _stock_db(dates[:-1])
    none_loader = _loader_for(none_payload)
    front_loader = _loader_for(front_payload)
    qfq.sync_stock_adj_all(
        target_date=dates[-2],
        db=db,
        bars_loader=none_loader,
        front_ratio_loader=front_loader,
    )
    db["stock_day"].rows.append({"code": "000001", "date": dates[-1]})

    result = qfq.sync_stock_adj_all(
        target_date=dates[-1],
        db=db,
        bars_loader=none_loader,
        front_ratio_loader=front_loader,
        tail_days=3,
        min_grace_seconds=0,
    )

    assert result["by_scope"]["stock"]["stats"]["incremental"] == 1
    assert result["by_scope"]["stock"]["coverage"]["source_gap_rows_bridged"] == 1
    assert [row["date"] for row in db["stock_adj_qfq_b"].rows] == dates


def test_update_excludes_full_range_empty_source_and_recovery_clears_it():
    dates = ["2026-01-02", "2026-01-05"]
    codes = ("000001", "000002")
    db = _DB(
        stock_list=[{"code": code} for code in codes],
        stock_day=[{"code": code, "date": dates[0]} for code in codes],
    )
    source_empty = False

    def loader(code, *, start_time, end_time):
        if source_empty and code == "000002":
            return pd.DataFrame()
        start = pd.Timestamp(start_time).strftime("%Y-%m-%d")
        end = pd.Timestamp(end_time).strftime("%Y-%m-%d")
        return _bars(
            [
                (value, 10.0, 0.0 if value == dates[0] else 10.0)
                for value in dates
                if start <= value <= end
            ]
        )

    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=loader)
    source_empty = True
    db["stock_day"].rows.extend({"code": code, "date": dates[1]} for code in codes)

    excluded = qfq.sync_stock_adj_all(
        target_date=dates[1], db=db, bars_loader=loader, min_grace_seconds=0
    )

    marker = excluded["by_scope"]["stock"]["marker"]
    assert marker["active_slot"] == "b"
    assert marker["slots"]["a"]["source_exclusions"] == []
    assert marker["slots"]["b"]["source_exclusions"] == [
        {"code": "000002", "reason": "source_empty_bars"}
    ]
    assert {row["code"] for row in db["stock_adj_qfq_b"].rows} == {"000001"}

    rolled_back = qfq.rollback_active_slot(scope="stock", db=db)
    assert rolled_back["active_slot"] == "a"
    assert rolled_back["slots"]["a"]["source_exclusions"] == []
    assert {row["code"] for row in db["stock_adj_qfq_a"].rows} == set(codes)

    source_empty = False
    recovered = qfq.sync_stock_adj_all(
        target_date=dates[1], db=db, bars_loader=loader, min_grace_seconds=0
    )
    active = recovered["by_scope"]["stock"]["marker"]
    assert active["active_slot"] == "b"
    assert active["slots"]["b"]["source_exclusions"] == []
    assert {row["code"] for row in db["stock_adj_qfq_b"].rows} == set(codes)


def test_tail_empty_is_rechecked_over_full_history_before_exclusion():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
    db = _stock_db(dates[:-1])

    def loader(code, *, start_time, end_time):
        del code
        start = pd.Timestamp(start_time).strftime("%Y-%m-%d")
        end = pd.Timestamp(end_time).strftime("%Y-%m-%d")
        if start != dates[0]:
            return pd.DataFrame()
        return _bars(
            [
                (value, 10.0, 0.0 if value == dates[0] else 10.0)
                for value in dates
                if start <= value <= end
            ]
        )

    qfq.sync_stock_adj_all(target_date=dates[-2], db=db, bars_loader=loader)
    db["stock_day"].rows.append({"code": "000001", "date": dates[-1]})

    result = qfq.sync_stock_adj_all(
        target_date=dates[-1],
        db=db,
        bars_loader=loader,
        tail_days=2,
        min_grace_seconds=0,
    )

    scope = result["by_scope"]["stock"]
    assert scope["stats"]["full"] == 1
    assert scope["stats"]["source_empty_bars_excluded"] == 0
    assert scope["marker"]["slots"]["b"]["source_exclusions"] == []
    assert [row["date"] for row in db["stock_adj_qfq_b"].rows] == dates


def test_tail_audit_reloads_context_when_window_starts_on_source_gap():
    dates = [
        "2026-01-02",
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-08",
        "2026-01-09",
    ]
    none_loader = _loader_for(
        {
            "000001": [
                (value, 10.0, 0.0 if index == 0 else 10.0)
                for index, value in enumerate(dates)
                if value != dates[3]
            ]
        }
    )
    front_loader = _loader_for(
        {
            "000001": [
                (value, 5.0, 0.0 if index == 0 else 5.0)
                for index, value in enumerate(dates)
                if value != dates[3]
            ]
        }
    )
    db = _stock_db(dates)
    qfq.sync_stock_adj_all(
        target_date=dates[-1],
        db=db,
        bars_loader=none_loader,
        front_ratio_loader=front_loader,
    )

    audit = qfq.audit_qfq_slot(
        scope="stock",
        slot="a",
        db=db,
        bars_loader=none_loader,
        front_ratio_loader=front_loader,
        source_tail_days=3,
    )

    assert audit["ok"]
    assert audit["coverage"]["source_gap_rows_bridged"] == 1


def test_xtdata_only_corporate_action_day_forces_full_rebuild():
    bfq_dates = ["2026-01-02", "2026-01-06"]
    payload = {"000001": [(bfq_dates[0], 10.0, 0.0)]}
    db = _stock_db(bfq_dates[:1])
    loader = _loader_for(payload)
    qfq.sync_stock_adj_all(target_date=bfq_dates[0], db=db, bars_loader=loader)
    payload["000001"] = [
        (bfq_dates[0], 10.0, 0.0),
        ("2026-01-05", 9.0, 8.0),
        (bfq_dates[1], 9.0, 9.0),
    ]
    db["stock_day"].rows.append({"code": "000001", "date": bfq_dates[1]})

    result = qfq.sync_stock_adj_all(
        target_date=bfq_dates[1],
        db=db,
        bars_loader=loader,
        min_grace_seconds=0,
    )

    assert result["by_scope"]["stock"]["stats"]["full"] == 1
    factors = {row["date"]: row["adj"] for row in db["stock_adj_qfq_b"].rows}
    assert factors == pytest.approx({bfq_dates[0]: 0.8, bfq_dates[1]: 1.0})


def test_company_action_rebuilds_only_inactive_code_history():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    rows = [
        (dates[0], 10.0, 0.0),
        (dates[1], 10.0, 10.0),
        (dates[2], 9.0, 8.0),
    ]
    db = _stock_db(dates[:1])
    loader = _loader_for({"000001": rows})
    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=loader)
    db["stock_day"].rows.extend({"code": "000001", "date": date} for date in dates[1:])
    active_rows = [dict(row) for row in db["stock_adj_qfq_a"].rows]

    result = qfq.sync_stock_adj_all(
        target_date=dates[-1],
        db=db,
        bars_loader=loader,
        min_grace_seconds=0,
    )

    stats = result["by_scope"]["stock"]["stats"]
    assert stats["full"] == 1
    assert db["stock_adj_qfq_a"].rows == active_rows
    factors = {row["date"]: row["adj"] for row in db["stock_adj_qfq_b"].rows}
    assert factors == pytest.approx({dates[0]: 0.8, dates[1]: 0.8, dates[2]: 1.0})


def test_failed_inactive_build_keeps_active_and_marks_inactive_failed():
    dates = ["2026-01-02", "2026-01-05"]
    rows = [(dates[0], 10.0, 0.0), (dates[1], 10.0, 10.0)]
    db = _stock_db(dates[:1])
    qfq.sync_stock_adj_all(
        target_date=dates[0], db=db, bars_loader=_loader_for({"000001": rows})
    )
    db["stock_day"].rows.append({"code": "000001", "date": dates[1]})
    marker_before = qfq.get_qfq_marker(scope="stock", db=db)

    with pytest.raises(RuntimeError, match="tail failed"):
        qfq.sync_stock_adj_all(
            target_date=dates[1],
            db=db,
            min_grace_seconds=0,
            bars_loader=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("tail failed")
            ),
        )

    marker_after = qfq.get_qfq_marker(scope="stock", db=db)
    assert marker_after["active_slot"] == marker_before["active_slot"]
    assert marker_after["slots"]["b"]["status"] == "failed"


def test_failed_inactive_build_is_retried_and_published():
    dates = ["2026-01-02", "2026-01-05"]
    rows = [(dates[0], 10.0, 0.0), (dates[1], 10.0, 10.0)]
    db = _stock_db(dates[:1])
    loader = _loader_for({"000001": rows})
    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=loader)
    db["stock_day"].rows.append({"code": "000001", "date": dates[1]})

    with pytest.raises(RuntimeError, match="tail failed"):
        qfq.sync_stock_adj_all(
            target_date=dates[1],
            db=db,
            min_grace_seconds=0,
            bars_loader=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("tail failed")
            ),
        )

    result = qfq.sync_stock_adj_all(
        target_date=dates[1],
        db=db,
        bars_loader=loader,
        min_grace_seconds=0,
    )

    assert result["by_scope"]["stock"]["mode"] == "update"
    assert qfq.resolve_active_slot(scope="stock", db=db)["slot"] == "b"


def test_interrupted_build_is_recovered_only_after_writer_lease_acquisition():
    dates = ["2026-01-02", "2026-01-05"]
    rows = [(dates[0], 10.0, 0.0), (dates[1], 10.0, 10.0)]
    db = _stock_db(dates[:1])
    loader = _loader_for({"000001": rows})
    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=loader)
    db["stock_day"].rows.append({"code": "000001", "date": dates[1]})
    db["qfq_ready"].rows[0]["slots"]["b"]["status"] = "building"

    result = qfq.sync_stock_adj_all(
        target_date=dates[1],
        db=db,
        bars_loader=loader,
        min_grace_seconds=0,
    )

    assert result["by_scope"]["stock"]["mode"] == "update"
    assert qfq.resolve_active_slot(scope="stock", db=db)["slot"] == "b"


def test_historical_bfq_axis_change_rebuilds_inactive_code():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
    rows = [
        (date, 10.0, 0.0 if index == 0 else 10.0) for index, date in enumerate(dates)
    ]
    db = _stock_db([dates[0], dates[2]])
    payload = {"000001": [rows[0], rows[2]]}
    loader = _loader_for(payload)
    qfq.sync_stock_adj_all(target_date=dates[2], db=db, bars_loader=loader)
    payload["000001"] = rows
    db["stock_day"].rows.extend(
        [
            {"code": "000001", "date": dates[1]},
            {"code": "000001", "date": dates[3]},
        ]
    )

    result = qfq.sync_stock_adj_all(
        target_date=dates[3],
        db=db,
        bars_loader=loader,
        min_grace_seconds=0,
    )

    assert result["by_scope"]["stock"]["stats"]["full"] == 1
    assert [row["date"] for row in db["stock_adj_qfq_b"].rows] == dates


def test_forced_full_rebuild_repairs_revision_older_than_tail_window():
    dates = (
        pd.date_range("2026-01-02", periods=71, freq="B").strftime("%Y-%m-%d").tolist()
    )
    rows = [
        [date_value, 10.0, 0.0 if index == 0 else 10.0]
        for index, date_value in enumerate(dates)
    ]
    payload = {"000001": [tuple(row) for row in rows[:70]]}
    db = _stock_db(dates[:70])
    loader = _loader_for(payload)
    qfq.sync_stock_adj_all(target_date=dates[69], db=db, bars_loader=loader)

    rows[1][2] = 8.0
    payload["000001"] = [tuple(row) for row in rows]
    db["stock_day"].rows.append({"code": "000001", "date": dates[70]})
    daily = qfq.sync_stock_adj_all(
        target_date=dates[70],
        db=db,
        bars_loader=loader,
        min_grace_seconds=0,
    )
    assert daily["by_scope"]["stock"]["stats"]["incremental"] == 1
    assert db["stock_adj_qfq_b"].rows[0]["adj"] == pytest.approx(1.0)

    rebuilt = qfq.sync_stock_adj_all(
        target_date=dates[70],
        db=db,
        bars_loader=loader,
        min_grace_seconds=0,
        force_full_rebuild=True,
    )

    assert rebuilt["by_scope"]["stock"]["stats"]["full"] == 1
    repaired = {row["date"]: row["adj"] for row in db["stock_adj_qfq_a"].rows}
    assert repaired[dates[0]] == pytest.approx(0.8)


def test_forced_full_rebuild_rejects_explicit_code_subset():
    with pytest.raises(ValueError, match="codes must be omitted"):
        qfq.sync_stock_adj_all(
            target_date="2026-01-05",
            codes=["000001"],
            force_full_rebuild=True,
        )


def test_forced_full_rebuild_rejects_factor_asof_regression():
    dates = ["2026-01-02", "2026-01-05"]
    rows = [(dates[0], 10.0, 0.0), (dates[1], 10.0, 10.0)]
    db = _stock_db(dates)
    loader = _loader_for({"000001": rows})
    qfq.sync_stock_adj_all(target_date=dates[1], db=db, bars_loader=loader)

    with pytest.raises(qfq.QFQSyncError, match="predates active snapshot"):
        qfq.sync_stock_adj_all(
            target_date=dates[0],
            db=db,
            bars_loader=loader,
            min_grace_seconds=0,
            force_full_rebuild=True,
        )

    assert qfq.resolve_active_slot(scope="stock", db=db)["factor_asof"] == dates[1]


def test_forced_full_rebuild_removes_codes_outside_current_universe():
    dates = ["2026-01-02", "2026-01-05"]
    rows = [(dates[0], 10.0, 0.0), (dates[1], 10.0, 10.0)]
    db = _stock_db(dates[:1])
    loader = _loader_for({"000001": rows})
    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=loader)
    db["stock_adj_qfq_b"].rows.append({"code": "600999", "date": dates[0], "adj": 1.0})
    db["stock_day"].rows.append({"code": "000001", "date": dates[1]})

    result = qfq.sync_stock_adj_all(
        target_date=dates[1],
        db=db,
        bars_loader=loader,
        min_grace_seconds=0,
        force_full_rebuild=True,
    )

    assert result["by_scope"]["stock"]["stats"]["stale_codes_removed"] == 1
    assert {row["code"] for row in db["stock_adj_qfq_b"].rows} == {"000001"}
    assert qfq.resolve_active_slot(scope="stock", db=db)["slot"] == "b"


def test_source_audit_detects_recurrence_corruption_that_structure_audit_misses():
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    rows = [
        (dates[0], 10.0, 0.0),
        (dates[1], 9.0, 8.0),
        (dates[2], 9.0, 9.0),
    ]
    db = _stock_db(dates)
    loader = _loader_for({"000001": rows})
    qfq.sync_stock_adj_all(target_date=dates[-1], db=db, bars_loader=loader)
    db["stock_adj_qfq_a"].rows[0]["adj"] = 0.123456

    structure = qfq.audit_qfq_slot(scope="stock", slot="a", db=db)
    source = qfq.audit_qfq_slot(scope="stock", slot="a", db=db, bars_loader=loader)

    assert structure["ok"] is True
    assert structure["audit_mode"] == "structure"
    assert source["ok"] is False
    assert source["audit_mode"] == "full_source"
    assert source["failures"][0]["audit"]["recurrence_errors"]


def test_stale_inactive_code_fails_closed_and_keeps_active():
    dates = ["2026-01-02", "2026-01-05"]
    rows = [(dates[0], 10.0, 0.0), (dates[1], 10.0, 10.0)]
    db = _stock_db(dates[:1])
    loader = _loader_for({"000001": rows})
    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=loader)
    db["stock_adj_qfq_b"].rows.append({"code": "600999", "date": dates[0], "adj": 1.0})
    db["stock_day"].rows.append({"code": "000001", "date": dates[1]})

    with pytest.raises(qfq.QFQSyncError, match="outside BFQ universe"):
        qfq.sync_stock_adj_all(
            target_date=dates[1],
            db=db,
            bars_loader=loader,
            min_grace_seconds=0,
        )

    marker = qfq.get_qfq_marker(scope="stock", db=db)
    assert marker["active_slot"] == "a"
    assert marker["slots"]["b"]["status"] == "failed"


def test_index_creation_failure_marks_claimed_inactive_slot_failed():
    dates = ["2026-01-02", "2026-01-05"]
    rows = [(dates[0], 10.0, 0.0), (dates[1], 10.0, 10.0)]
    db = _stock_db(dates[:1])
    loader = _loader_for({"000001": rows})
    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=loader)
    db["stock_day"].rows.append({"code": "000001", "date": dates[1]})

    def fail_index(*args, **kwargs):
        raise RuntimeError("duplicate factor rows")

    db["stock_adj_qfq_b"].create_index = fail_index

    with pytest.raises(RuntimeError, match="duplicate factor rows"):
        qfq.sync_stock_adj_all(
            target_date=dates[1],
            db=db,
            bars_loader=loader,
            min_grace_seconds=0,
        )

    marker = qfq.get_qfq_marker(scope="stock", db=db)
    assert marker["active_slot"] == "a"
    assert marker["slots"]["b"]["status"] == "failed"


def test_marker_cas_failure_keeps_old_active_visible():
    dates = ["2026-01-02", "2026-01-05"]
    rows = [(dates[0], 10.0, 0.0), (dates[1], 10.0, 10.0)]
    db = _stock_db(dates[:1])
    loader = _loader_for({"000001": rows})
    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=loader)
    db["stock_day"].rows.append({"code": "000001", "date": dates[1]})
    original_update = db["qfq_ready"].update_one
    calls = 0

    def fail_publish(query, update, upsert=False):
        nonlocal calls
        calls += 1
        if calls == 2:
            return _Result()
        return original_update(query, update, upsert=upsert)

    db["qfq_ready"].update_one = fail_publish

    with pytest.raises(qfq.QFQSyncError, match="CAS publish lost"):
        qfq.sync_stock_adj_all(
            target_date=dates[1],
            db=db,
            bars_loader=loader,
            min_grace_seconds=0,
        )

    assert qfq.resolve_active_slot(scope="stock", db=db)["slot"] == "a"


def test_marker_switch_and_rollback_rebind_live_intraday_override():
    target_date = "2026-01-02"
    db = _stock_db([target_date])
    loader = _loader_for({"000001": [(target_date, 10.0, 0.0)]})
    qfq.sync_stock_adj_all(target_date=target_date, db=db, bars_loader=loader)
    active_a = qfq.resolve_active_slot(scope="stock", db=db)
    db["stock_adj_intraday"].rows.append(
        {
            "code": "000001",
            "trade_date": "2026-01-05",
            "base_anchor_date": target_date,
            "base_snapshot_id": active_a["snapshot_id"],
            "base_factor_asof": active_a["factor_asof"],
            "anchor_scale": 0.8,
            "updated_at": "override-v1",
        }
    )

    updated = qfq.sync_stock_adj_all(
        target_date=target_date,
        db=db,
        bars_loader=loader,
        force_full_rebuild=True,
        min_grace_seconds=0,
    )

    active_b = updated["by_scope"]["stock"]["marker"]["slots"]["b"]
    override = db["stock_adj_intraday"].rows[0]
    assert override["base_snapshot_id"] == active_b["snapshot_id"]
    assert override["base_factor_asof"] == active_b["factor_asof"]
    assert override["anchor_scale"] == pytest.approx(0.8)

    rolled_back = qfq.rollback_active_slot(scope="stock", db=db)

    override = db["stock_adj_intraday"].rows[0]
    assert rolled_back["active_slot"] == "a"
    assert override["base_snapshot_id"] == active_a["snapshot_id"]
    assert override["base_factor_asof"] == active_a["factor_asof"]
    assert override["anchor_scale"] == pytest.approx(0.8)


def test_rollback_keeps_future_override_already_bound_to_target_snapshot():
    dates = ["2026-01-02", "2026-01-05"]
    db = _stock_db(dates[:1])
    loader = _loader_for({"000001": [(dates[0], 10.0, 0.0), (dates[1], 10.0, 10.0)]})
    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=loader)
    active_a = qfq.resolve_active_slot(scope="stock", db=db)
    db["stock_adj_intraday"].rows.append(
        {
            "code": "000001",
            "trade_date": dates[1],
            "base_anchor_date": dates[0],
            "base_snapshot_id": active_a["snapshot_id"],
            "base_factor_asof": active_a["factor_asof"],
            "anchor_scale": 0.8,
            "updated_at": "override-v1",
        }
    )
    db["stock_day"].rows.append({"code": "000001", "date": dates[1]})

    updated = qfq.sync_stock_adj_all(
        target_date=dates[1],
        db=db,
        bars_loader=loader,
        min_grace_seconds=0,
    )

    override_before = dict(db["stock_adj_intraday"].rows[0])
    assert updated["by_scope"]["stock"]["marker"]["active_slot"] == "b"
    assert override_before["base_snapshot_id"] == active_a["snapshot_id"]

    rolled_back = qfq.rollback_active_slot(scope="stock", db=db)

    assert rolled_back["active_slot"] == "a"
    assert db["stock_adj_intraday"].rows[0] == override_before


def test_marker_cas_failure_restores_intraday_override_binding():
    target_date = "2026-01-02"
    db = _stock_db([target_date])
    loader = _loader_for({"000001": [(target_date, 10.0, 0.0)]})
    qfq.sync_stock_adj_all(target_date=target_date, db=db, bars_loader=loader)
    active = qfq.resolve_active_slot(scope="stock", db=db)
    db["stock_adj_intraday"].rows.append(
        {
            "code": "000001",
            "trade_date": "2026-01-05",
            "base_anchor_date": target_date,
            "base_snapshot_id": active["snapshot_id"],
            "base_factor_asof": active["factor_asof"],
            "anchor_scale": 0.8,
            "updated_at": "override-v1",
        }
    )
    original_update = db["qfq_ready"].update_one
    calls = 0

    def fail_publish(query, update, upsert=False):
        nonlocal calls
        calls += 1
        if calls == 2:
            return _Result()
        return original_update(query, update, upsert=upsert)

    db["qfq_ready"].update_one = fail_publish

    with pytest.raises(qfq.QFQSyncError, match="CAS publish lost"):
        qfq.sync_stock_adj_all(
            target_date=target_date,
            db=db,
            bars_loader=loader,
            force_full_rebuild=True,
            min_grace_seconds=0,
        )

    override = db["stock_adj_intraday"].rows[0]
    assert qfq.resolve_active_slot(scope="stock", db=db)["slot"] == "a"
    assert override["base_snapshot_id"] == active["snapshot_id"]
    assert override["base_factor_asof"] == active["factor_asof"]
    assert override["anchor_scale"] == pytest.approx(0.8)


def test_marker_publish_exception_after_commit_keeps_rebound_override():
    target_date = "2026-01-02"
    db = _stock_db([target_date])
    loader = _loader_for({"000001": [(target_date, 10.0, 0.0)]})
    qfq.sync_stock_adj_all(target_date=target_date, db=db, bars_loader=loader)
    active = qfq.resolve_active_slot(scope="stock", db=db)
    db["stock_adj_intraday"].rows.append(
        {
            "code": "000001",
            "trade_date": "2026-01-05",
            "base_anchor_date": target_date,
            "base_snapshot_id": active["snapshot_id"],
            "base_factor_asof": active["factor_asof"],
            "anchor_scale": 0.8,
            "updated_at": "override-v1",
        }
    )
    original_update = db["qfq_ready"].update_one
    calls = 0

    def lose_publish_response(query, update, upsert=False):
        nonlocal calls
        calls += 1
        result = original_update(query, update, upsert=upsert)
        if calls == 2:
            raise RuntimeError("publish response lost")
        return result

    db["qfq_ready"].update_one = lose_publish_response

    updated = qfq.sync_stock_adj_all(
        target_date=target_date,
        db=db,
        bars_loader=loader,
        force_full_rebuild=True,
        min_grace_seconds=0,
    )

    active_b = updated["by_scope"]["stock"]["marker"]["slots"]["b"]
    override = db["stock_adj_intraday"].rows[0]
    assert updated["by_scope"]["stock"]["marker"]["active_slot"] == "b"
    assert override["base_snapshot_id"] == active_b["snapshot_id"]
    assert override["base_factor_asof"] == active_b["factor_asof"]


def test_rollback_marker_exception_restores_source_override_binding():
    target_date = "2026-01-02"
    db = _stock_db([target_date])
    loader = _loader_for({"000001": [(target_date, 10.0, 0.0)]})
    qfq.sync_stock_adj_all(target_date=target_date, db=db, bars_loader=loader)
    active = qfq.resolve_active_slot(scope="stock", db=db)
    db["stock_adj_intraday"].rows.append(
        {
            "code": "000001",
            "trade_date": "2026-01-05",
            "base_anchor_date": target_date,
            "base_snapshot_id": active["snapshot_id"],
            "base_factor_asof": active["factor_asof"],
            "anchor_scale": 0.8,
            "updated_at": "override-v1",
        }
    )

    def fail_rollback_update(*_args, **_kwargs):
        raise RuntimeError("rollback update failed")

    db["qfq_ready"].update_one = fail_rollback_update

    with pytest.raises(qfq.QFQSyncError, match="rollback marker failed"):
        qfq.rollback_active_slot(scope="stock", db=db)

    override = db["stock_adj_intraday"].rows[0]
    assert qfq.resolve_active_slot(scope="stock", db=db)["slot"] == "a"
    assert override["base_snapshot_id"] == active["snapshot_id"]
    assert override["base_factor_asof"] == active["factor_asof"]
    assert override["anchor_scale"] == pytest.approx(0.8)


def test_rebind_ignores_inactive_intraday_override_statuses():
    target_date = "2026-01-02"
    db = _stock_db([target_date])
    loader = _loader_for({"000001": [(target_date, 10.0, 0.0)]})
    qfq.sync_stock_adj_all(target_date=target_date, db=db, bars_loader=loader)
    inactive_overrides = [
        {
            "code": code,
            "trade_date": "2026-01-05",
            "base_anchor_date": target_date,
            "base_snapshot_id": "stale-snapshot",
            "anchor_scale": 0.8,
            "status": status,
        }
        for code, status in zip(
            ("000002", "000003", "000004"),
            ("expired", "disabled", "failed"),
            strict=True,
        )
    ]
    db["stock_adj_intraday"].rows.extend(inactive_overrides)

    updated = qfq.sync_stock_adj_all(
        target_date=target_date,
        db=db,
        bars_loader=loader,
        force_full_rebuild=True,
        min_grace_seconds=0,
    )

    assert updated["by_scope"]["stock"]["marker"]["active_slot"] == "b"
    assert db["stock_adj_intraday"].rows == inactive_overrides


def test_rollback_swaps_only_between_ready_slots():
    dates = ["2026-01-02", "2026-01-05"]
    rows = [(dates[0], 10.0, 0.0), (dates[1], 10.0, 10.0)]
    db = _stock_db(dates[:1])
    loader = _loader_for({"000001": rows})
    qfq.sync_stock_adj_all(target_date=dates[0], db=db, bars_loader=loader)
    db["stock_day"].rows.append({"code": "000001", "date": dates[1]})
    qfq.sync_stock_adj_all(
        target_date=dates[1], db=db, bars_loader=loader, min_grace_seconds=0
    )

    assert qfq.rollback_active_slot(scope="stock", db=db)["active_slot"] == "a"
    db["qfq_ready"].rows[0]["slots"]["b"]["status"] = "building"
    with pytest.raises(qfq.QFQSyncError, match="rollback slot is not ready"):
        qfq.rollback_active_slot(scope="stock", db=db)


def test_rollback_refreshes_activation_time_for_reader_grace():
    db = _stock_db(["2026-01-02"])
    loader = _loader_for({"000001": [("2026-01-02", 10.0, 0.0)]})
    qfq.sync_stock_adj_all(target_date="2026-01-02", db=db, bars_loader=loader)
    republished_at = datetime(2026, 1, 6, 8, 0, tzinfo=timezone.utc)

    marker = qfq.rollback_active_slot(
        scope="stock", db=db, now_provider=lambda: republished_at
    )

    assert marker["active_slot"] == "b"
    assert marker["slots"]["b"]["published_at"] == "2026-01-06T08:00:00Z"


def test_rollback_respects_live_writer_lease():
    now = datetime(2026, 1, 6, 8, 0, tzinfo=timezone.utc)
    db = _stock_db(["2026-01-02"])
    loader = _loader_for({"000001": [("2026-01-02", 10.0, 0.0)]})
    qfq.sync_stock_adj_all(target_date="2026-01-02", db=db, bars_loader=loader)
    db["qfq_writer_locks"].rows.append(
        {
            "scope": "stock",
            "owner_id": "active-builder",
            "expires_at": "2026-01-06T09:00:00Z",
        }
    )

    with pytest.raises(qfq.QFQSyncError, match="writer lease is held"):
        qfq.rollback_active_slot(scope="stock", db=db, now_provider=lambda: now)

    assert qfq.resolve_active_slot(scope="stock", db=db)["slot"] == "a"


def test_reader_grace_blocks_immediate_reuse_of_old_active_slot():
    dates = ["2026-01-02", "2026-01-05"]
    rows = [(dates[0], 10.0, 0.0), (dates[1], 10.0, 10.0)]
    db = _stock_db(dates[:1])
    now = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
    qfq.sync_stock_adj_all(
        target_date=dates[0],
        db=db,
        bars_loader=_loader_for({"000001": rows}),
        now_provider=lambda: now,
    )
    db["stock_day"].rows.append({"code": "000001", "date": dates[1]})

    with pytest.raises(qfq.QFQSyncError, match="grace period"):
        qfq.sync_stock_adj_all(
            target_date=dates[1],
            db=db,
            bars_loader=_loader_for({"000001": rows}),
            now_provider=lambda: now + timedelta(seconds=299),
        )


def test_xtdata_client_uses_configured_port_and_none_dividend(monkeypatch):
    calls = []

    class _XtData:
        def connect(self, *, port):
            calls.append(("connect", port))

        def download_history_data(self, *args):
            calls.append(("download", args))

        def get_market_data(self, **kwargs):
            calls.append(("get", kwargs))
            return {"000001.SZ": _bars([("2026-01-02", 10.0, 0.0)])}

    monkeypatch.setattr(
        qfq,
        "bootstrap_config",
        SimpleNamespace(xtdata=SimpleNamespace(port=58611)),
    )
    client = qfq.XtDataQfqClient(_XtData())
    result = client.load_daily_bars(
        "000001", start_time="20260102", end_time="20260102"
    )

    assert len(result) == 1
    assert calls[0] == ("connect", 58611)
    assert calls[-1][1]["dividend_type"] == "none"
    assert calls[-1][1]["fill_data"] is False

    client.load_front_ratio_bars("000001", start_time="20260102", end_time="20260102")
    assert calls[-1][1]["dividend_type"] == "front_ratio"


def test_xtdata_client_loads_and_validates_instrument_open_date():
    calls = []

    class _XtData:
        def connect(self, *, port):
            calls.append(("connect", port))

        def get_instrument_detail(self, code):
            calls.append(("detail", code))
            return {
                "000028.SZ": {"OpenDate": "19930809", "IsTrading": True},
                "161022.SZ": {"OpenDate": 20240131, "IsTrading": False},
                "510050.SH": {"OpenDate": "20241340", "IsTrading": False},
            }[code]

    client = qfq.XtDataQfqClient(_XtData(), port=58612)

    assert client.load_open_date("000028") == "1993-08-09"
    assert client.load_listing_metadata("161022") == {
        "open_date": "2024-01-31",
        "is_trading": False,
    }
    assert client.load_open_date("510050") is None
    assert calls == [
        ("connect", 58612),
        ("detail", "000028.SZ"),
        ("detail", "161022.SZ"),
        ("detail", "510050.SH"),
    ]


def test_sync_uses_same_default_client_for_bars_and_listing_date():
    calls = []

    class _Client:
        def load_daily_bars(self, code, *, start_time, end_time):
            calls.append(("bars", code))
            return _bars([("1993-08-09", 10.0, 0.0)])

        def load_front_ratio_bars(self, code, *, start_time, end_time):
            raise AssertionError("no source gap")

        def load_listing_metadata(self, code):
            calls.append(("listing_metadata", code))
            return {"open_date": "1993-08-09", "is_trading": True}

    db = _DB(
        stock_list=[{"code": "000028", "name": "Stock"}],
        stock_day=[
            {"code": "000028", "date": "1993-06-01"},
            {"code": "000028", "date": "1993-08-09"},
        ],
    )

    qfq.sync_stock_adj_all(target_date="1993-08-09", db=db, xtdata_client=_Client())

    assert ("bars", "000028") in calls
    assert calls.count(("listing_metadata", "000028")) == 3


def test_custom_bars_loader_does_not_implicitly_connect_for_open_date():
    class _Client:
        def load_listing_metadata(self, _code):
            raise AssertionError("custom source must stay isolated")

    db = _stock_db(["2026-01-02"])

    qfq.sync_stock_adj_all(
        target_date="2026-01-02",
        db=db,
        bars_loader=_loader_for({"000001": [("2026-01-02", 10.0, 0.0)]}),
        xtdata_client=_Client(),
    )


def test_xtdata_client_downloads_missing_history_prefix():
    calls = []

    class _XtData:
        def connect(self, *, port):
            calls.append(("connect", port))

        def download_history_data(self, *args):
            calls.append(("download", args))

        def get_market_data(self, **kwargs):
            calls.append(("get", kwargs))
            download_count = sum(call[0] == "download" for call in calls)
            rows = [
                ("2024-09-03", 10.0, 10.0),
                ("2026-07-31", 10.0, 10.0),
            ]
            if download_count > 1:
                rows.insert(0, ("1994-01-04", 10.0, 10.0))
            if download_count > 2:
                rows.insert(0, ("1991-01-29", 10.0, 0.0))
            return {"000002.SZ": _bars(rows)}

    result = qfq.XtDataQfqClient(_XtData()).load_daily_bars(
        "000002", start_time="19910129", end_time="20260731"
    )

    assert result["date"].tolist() == [
        "1991-01-29",
        "1994-01-04",
        "2024-09-03",
        "2026-07-31",
    ]
    assert [call for call in calls if call[0] == "download"] == [
        ("download", ("000002.SZ", "1d", "19910129", "20260731")),
        ("download", ("000002.SZ", "1d", "19910129", "20240902")),
        ("download", ("000002.SZ", "1d", "19910129", "19940103")),
    ]


def test_xtdata_client_fails_when_history_prefix_makes_no_progress():
    class _XtData:
        def connect(self, *, port):
            pass

        def download_history_data(self, *args):
            pass

        def get_market_data(self, **kwargs):
            return {
                "000002.SZ": _bars(
                    [
                        ("2024-09-03", 10.0, 0.0),
                        ("2026-07-31", 10.0, 10.0),
                    ]
                )
            }

    with pytest.raises(qfq.QFQSyncError, match="prefix download made no progress"):
        qfq.XtDataQfqClient(_XtData()).load_daily_bars(
            "000002", start_time="19910129", end_time="20260731"
        )


def test_real_xtdata_stock_and_etf_action_fixtures():
    fixture_path = Path(__file__).parent / "fixtures" / "qfq_xtdata_real_samples.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert payload["source"].startswith("XTData")
    for sample in payload["samples"]:
        bars = pd.DataFrame(sample["bars"])
        factors = qfq.compute_preclose_adj(bars, code=sample["code"])
        merged = bars.merge(factors[["date", "adj"]], on="date")
        event = merged.loc[merged["date"] == sample["event_date"]].iloc[0]
        adjusted_close = float(event["close"]) * float(event["adj"])
        assert adjusted_close == pytest.approx(
            sample["expected_event_qfq_close"], abs=1e-12
        )
        assert adjusted_close == pytest.approx(
            sample["front_reference_normalized_close"],
            abs=sample["front_tolerance"],
        )


def test_normalize_xtdata_bars_marks_invalid_close_as_source_exclusion():
    bars = _bars(
        [
            ("2026-01-02", 0.0, 0.0),
            ("2026-01-05", 0.0, 0.0),
            ("2026-01-06", 0.0, 0.0),
        ]
    )
    with pytest.raises(qfq.QFQSyncError, match="invalid close") as caught:
        qfq.normalize_xtdata_bars(bars, code="000004.SZ")
    assert caught.value.stats["failure"] == "source_invalid_close"


def test_normalize_xtdata_bars_marks_invalid_used_preclose_as_source_exclusion():
    bars = _bars(
        [
            ("2026-01-02", 10.0, 0.0),
            ("2026-01-05", 9.0, 0.0),
            ("2026-01-06", 9.1, 9.0),
        ]
    )
    with pytest.raises(qfq.QFQSyncError, match="invalid used preClose") as caught:
        qfq.normalize_xtdata_bars(bars, code="000004.SZ")
    assert caught.value.stats["failure"] == "source_invalid_close"


def test_source_exclusion_reason_recognizes_invalid_close():
    error = qfq.QFQSyncError(
        "invalid close values for code=000004.SZ",
        stats={"failure": "source_invalid_close"},
    )
    assert qfq._source_exclusion_reason(error) == "source_invalid_close"


def test_bootstrap_excludes_source_invalid_close_and_publishes_marker():
    target = "2026-01-05"
    db = _DB(
        stock_list=[
            {"code": code, "name": "Stock"} for code in ("000001", "000004", "000005")
        ],
        stock_day=[
            {"code": code, "date": target} for code in ("000001", "000004", "000005")
        ],
    )

    def loader(code, **_kwargs):
        if code == "000004":
            return _bars([(target, 0.0, 0.0)])
        if code == "000005":
            return _bars([("2026-01-02", 5.0, 0.0), (target, 4.0, 5.0)])
        return _bars([(target, 10.0, 0.0)])

    result = qfq.sync_stock_adj_all(target_date=target, db=db, bars_loader=loader)

    scope = result["by_scope"]["stock"]
    exclusions = [{"code": "000004", "reason": "source_invalid_close"}]
    assert scope["codes"] == 2
    assert scope["coverage"]["source_invalid_close_excluded"] == 1
    assert scope["coverage"]["source_invalid_close"] == exclusions
    assert {row["code"] for row in db["stock_adj_qfq_a"].rows} == {
        "000001",
        "000005",
    }
    assert {row["code"] for row in db["stock_adj_qfq_b"].rows} == {
        "000001",
        "000005",
    }
    marker = db["qfq_ready"].rows[0]
    assert marker["slots"]["a"]["source_exclusions"] == exclusions
    assert marker["slots"]["b"]["source_exclusions"] == exclusions

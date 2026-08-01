from __future__ import annotations

import json
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
            assert projection == {"_id": 0, "date": 1}
            return _UnsortedCursor()

    db = _DB()
    db.collections["stock_day"] = _BfqCollection()

    assert qfq.load_bfq_dates(kind="stock", code="000001", db=db) == [
        "2026-01-02",
        "2026-01-05",
    ]


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

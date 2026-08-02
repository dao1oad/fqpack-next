from __future__ import annotations

import inspect

import pandas as pd
import pytest

import freshquant.data.qfq_reader as qfq_reader
from freshquant.data.qfq_reader import (
    QFQDataNotReadyError,
    apply_qfq_to_bars,
    resolve_qfq_read_metadata,
    resolve_qfq_scope_metadata,
)


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def sort(self, key, direction):
        self.rows.sort(key=lambda row: row.get(key), reverse=direction < 0)
        return self

    def __iter__(self):
        return iter(self.rows)


class _Collection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find_one(self, query=None, projection=None, **_kwargs):
        rows = list(self.find(query, projection))
        return rows[0] if rows else None

    def find(self, query=None, projection=None):
        rows = [row for row in self.rows if _matches(row, query or {})]
        if projection:
            included = {key for key, enabled in projection.items() if enabled}
            if included:
                rows = [
                    {key: value for key, value in row.items() if key in included}
                    for row in rows
                ]
            else:
                excluded = {key for key, enabled in projection.items() if not enabled}
                rows = [
                    {key: value for key, value in row.items() if key not in excluded}
                    for row in rows
                ]
        return _Cursor(rows)


class _Database:
    def __init__(self, **collections):
        self.collections = {
            name: _Collection(rows) for name, rows in collections.items()
        }

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


def _matches(row, query):
    for key, expected in query.items():
        actual = row.get(key)
        if isinstance(expected, dict):
            if "$gte" in expected and actual < expected["$gte"]:
                return False
            if "$lte" in expected and actual > expected["$lte"]:
                return False
        elif actual != expected:
            return False
    return True


def _slot(scope, slot, snapshot, *, factor_asof="2026-07-31", exclusions=None):
    return {
        "collection": f"{scope}_adj_qfq_{slot}",
        "snapshot_id": snapshot,
        "factor_asof": factor_asof,
        "status": "ready",
        "published_at": (
            "2026-07-31T15:59:00+08:00" if slot == "a" else "2026-07-31T16:00:00+08:00"
        ),
        "source_exclusions": list(exclusions or []),
    }


def _marker(*, active="a", factor_asof="2026-07-31", exclusions=None):
    return {
        "scope": "stock",
        "active_slot": active,
        "slots": {
            "a": _slot(
                "stock",
                "a",
                "snapshot-a",
                factor_asof=factor_asof,
                exclusions=exclusions if active == "a" else None,
            ),
            "b": _slot(
                "stock",
                "b",
                "snapshot-b",
                factor_asof=factor_asof,
                exclusions=exclusions if active == "b" else None,
            ),
        },
        "source": "xtdata_preclose",
        "schema_version": 1,
    }


def _bars(*dates):
    return pd.DataFrame(
        {
            "datetime": [pd.Timestamp(f"{value} 10:00:00") for value in dates],
            "open": [10.0] * len(dates),
            "high": [11.0] * len(dates),
            "low": [9.0] * len(dates),
            "close": [10.5] * len(dates),
        }
    )


def test_reader_uses_only_marker_selected_active_slot():
    db = _Database(
        qfq_ready=[
            _marker(
                active="b",
                exclusions=[{"code": "999999", "reason": "source_empty_bars"}],
            )
        ],
        stock_adj_qfq_a=[
            {"code": "000001", "date": "2026-07-30", "adj": 0.1},
            {"code": "000001", "date": "2026-07-31", "adj": 0.1},
        ],
        stock_adj_qfq_b=[
            {"code": "000001", "date": "2026-07-30", "adj": 0.5},
            {"code": "000001", "date": "2026-07-31", "adj": 1.0},
        ],
    )

    result, metadata = apply_qfq_to_bars(
        _bars("2026-07-30", "2026-07-31"),
        scope="stock",
        code="sz000001",
        db=db,
    )

    assert result["open"].tolist() == [5.0, 10.0]
    assert metadata.collection == "stock_adj_qfq_b"
    assert metadata.snapshot_id == "snapshot-b"
    assert metadata.effective_version == "snapshot-b"
    assert metadata.active_slot == "b"
    assert metadata.published_at == "2026-07-31T16:00:00+08:00"
    assert metadata.source_exclusions == (
        {"code": "999999", "reason": "source_empty_bars"},
    )


def test_reader_resolves_marker_again_after_active_slot_switch():
    marker = _marker(active="a")
    db = _Database(
        qfq_ready=[marker],
        stock_adj_qfq_a=[{"code": "000001", "date": "2026-07-31", "adj": 0.5}],
        stock_adj_qfq_b=[{"code": "000001", "date": "2026-07-31", "adj": 0.8}],
    )
    first, _metadata = apply_qfq_to_bars(
        _bars("2026-07-31"), scope="stock", code="000001", db=db
    )
    marker["active_slot"] = "b"
    second, _metadata = apply_qfq_to_bars(
        _bars("2026-07-31"), scope="stock", code="000001", db=db
    )

    assert first["open"].tolist() == [5.0]
    assert second["open"].tolist() == [8.0]


def test_scope_metadata_resolves_active_snapshot_on_every_call():
    marker = _marker(
        active="a",
        exclusions=[{"code": "999999", "reason": "source_empty_bars"}],
    )
    db = _Database(qfq_ready=[marker])

    first = resolve_qfq_scope_metadata(scope="stock", trade_date="2026-07-31", db=db)
    marker["active_slot"] = "b"
    second = resolve_qfq_scope_metadata(scope="stock", trade_date="2026-07-31", db=db)

    assert first.snapshot_id == "snapshot-a"
    assert first.collection == "stock_adj_qfq_a"
    assert first.effective_version == "snapshot-a"
    assert first.active_slot == "a"
    assert first.published_at == "2026-07-31T15:59:00+08:00"
    assert first.source_exclusions == (
        {"code": "999999", "reason": "source_empty_bars"},
    )
    assert first.override_version is None
    assert second.snapshot_id == "snapshot-b"
    assert second.collection == "stock_adj_qfq_b"
    assert second.effective_version == "snapshot-b"
    assert second.active_slot == "b"
    assert second.published_at == "2026-07-31T16:00:00+08:00"
    assert second.source_exclusions == ()
    assert second.override_version is None


@pytest.mark.parametrize("resolver", ["scope", "code"])
def test_reader_rejects_active_snapshot_without_published_at(resolver):
    marker = _marker()
    marker["slots"]["a"].pop("published_at")
    db = _Database(qfq_ready=[marker])

    with pytest.raises(QFQDataNotReadyError, match="metadata is incomplete"):
        if resolver == "scope":
            resolve_qfq_scope_metadata(scope="stock", db=db)
        else:
            resolve_qfq_read_metadata(scope="stock", code="000001", db=db)


def test_read_metadata_rejects_invalid_nonempty_trade_date():
    db = _Database(qfq_ready=[_marker()])

    with pytest.raises(QFQDataNotReadyError, match="trade_date is invalid"):
        resolve_qfq_read_metadata(
            scope="stock", code="000001", trade_date="not-a-date", db=db
        )


def test_scope_metadata_normalizes_source_exclusion_codes(monkeypatch):
    active = {
        "scope": "stock",
        "slot": "a",
        **_slot("stock", "a", "snapshot-a"),
        "source_exclusions": [
            {"code": "SZ000001", "reason": "source_empty_bars", "rows": 0}
        ],
    }
    monkeypatch.setattr(
        "freshquant.market_data.xtdata.qfq.resolve_active_slot",
        lambda **_kwargs: active,
    )

    metadata = resolve_qfq_scope_metadata(scope="stock", db=_Database())

    assert metadata.source_exclusions == (
        {"code": "000001", "reason": "source_empty_bars", "rows": 0},
    )


@pytest.mark.parametrize("resolver", ["scope", "code"])
def test_reader_maps_malformed_source_exclusion_to_not_ready(monkeypatch, resolver):
    active = {
        "scope": "stock",
        "slot": "a",
        **_slot("stock", "a", "snapshot-a"),
        "source_exclusions": [object()],
    }
    monkeypatch.setattr(
        "freshquant.market_data.xtdata.qfq.resolve_active_slot",
        lambda **_kwargs: active,
    )

    with pytest.raises(QFQDataNotReadyError, match="exclusions are malformed"):
        if resolver == "scope":
            resolve_qfq_scope_metadata(scope="stock", db=_Database())
        else:
            resolve_qfq_read_metadata(scope="stock", code="000001", db=_Database())


def test_strict_factor_path_has_no_fillna_one_fallback():
    assert "fillna(1.0)" not in inspect.getsource(qfq_reader._read_factor_series)


def test_scope_metadata_rejects_trade_date_after_factor_asof_without_override():
    db = _Database(
        qfq_ready=[_marker()],
        stock_adj_intraday=[
            {
                "code": "000001",
                "trade_date": "2026-08-01",
                "base_snapshot_id": "snapshot-a",
                "anchor_scale": 1.0,
                "updated_at": "override-v1",
            }
        ],
    )

    with pytest.raises(QFQDataNotReadyError, match="scope freeze") as exc_info:
        resolve_qfq_scope_metadata(scope="stock", trade_date="2026-08-01", db=db)

    assert exc_info.value.code == ""
    assert exc_info.value.missing_dates == ("2026-08-01",)


@pytest.mark.parametrize(
    "database",
    [
        _Database(),
        _Database(qfq_ready=[{**_marker(), "source": "legacy"}]),
    ],
)
def test_reader_fails_closed_when_ready_marker_is_missing_or_invalid(database):
    with pytest.raises(QFQDataNotReadyError, match="QFQ_DATA_NOT_READY"):
        apply_qfq_to_bars(
            _bars("2026-07-31"), scope="stock", code="000001", db=database
        )


def test_reader_fails_closed_on_factor_coverage_gap():
    db = _Database(qfq_ready=[_marker()], stock_adj_qfq_a=[])

    with pytest.raises(QFQDataNotReadyError) as exc_info:
        apply_qfq_to_bars(
            _bars("2026-07-30", "2026-07-31"),
            scope="stock",
            code="000001",
            db=db,
        )

    assert exc_info.value.missing_dates == ("2026-07-30", "2026-07-31")


def test_reader_fails_closed_for_active_source_exclusion():
    db = _Database(
        qfq_ready=[
            _marker(exclusions=[{"code": "000001", "reason": "source_empty_bars"}])
        ]
    )

    scope_metadata = resolve_qfq_scope_metadata(scope="stock", db=db)
    assert scope_metadata.source_exclusions == (
        {"code": "000001", "reason": "source_empty_bars"},
    )

    with pytest.raises(QFQDataNotReadyError, match="excluded"):
        resolve_qfq_read_metadata(scope="stock", code="000001", db=db)


def test_matching_override_is_snapshot_bound_and_versions_the_result():
    db = _Database(
        qfq_ready=[_marker()],
        stock_adj_qfq_a=[{"code": "000001", "date": "2026-07-31", "adj": 1.0}],
        stock_adj_intraday=[
            {
                "code": "000001",
                "trade_date": "2026-08-01",
                "base_snapshot_id": "snapshot-a",
                "base_factor_asof": "2026-07-31",
                "anchor_scale": 0.8,
                "updated_at": "override-v2",
            }
        ],
    )

    result, metadata = apply_qfq_to_bars(
        _bars("2026-07-31", "2026-08-01"),
        scope="stock",
        code="000001",
        db=db,
    )

    assert result["open"].tolist() == [8.0, 10.0]
    assert metadata.effective_version == "snapshot-a:override-v2"
    assert metadata.active_slot == "a"
    assert metadata.published_at == "2026-07-31T15:59:00+08:00"


def test_stale_override_never_applies_to_a_new_snapshot():
    db = _Database(
        qfq_ready=[_marker(active="b")],
        stock_adj_qfq_b=[{"code": "000001", "date": "2026-07-31", "adj": 1.0}],
        stock_adj_intraday=[
            {
                "code": "000001",
                "trade_date": "2026-08-01",
                "base_snapshot_id": "snapshot-a",
                "anchor_scale": 0.8,
                "updated_at": "override-v1",
            }
        ],
    )

    with pytest.raises(QFQDataNotReadyError, match="snapshot mismatch"):
        apply_qfq_to_bars(
            _bars("2026-07-31", "2026-08-01"),
            scope="stock",
            code="000001",
            db=db,
        )


def test_reader_requires_override_for_date_after_factor_asof():
    db = _Database(
        qfq_ready=[_marker()],
        stock_adj_qfq_a=[{"code": "000001", "date": "2026-07-31", "adj": 1.0}],
    )

    with pytest.raises(QFQDataNotReadyError, match="override is missing") as exc_info:
        apply_qfq_to_bars(
            _bars("2026-07-31", "2026-08-01"),
            scope="stock",
            code="000001",
            db=db,
        )

    assert exc_info.value.missing_dates == ("2026-08-01",)


def test_reader_rejects_more_than_one_date_beyond_factor_asof():
    db = _Database(
        qfq_ready=[_marker()],
        stock_adj_qfq_a=[{"code": "000001", "date": "2026-07-31", "adj": 1.0}],
        stock_adj_intraday=[
            {
                "code": "000001",
                "trade_date": "2026-08-03",
                "base_snapshot_id": "snapshot-a",
                "base_factor_asof": "2026-07-31",
                "anchor_scale": 1.0,
                "updated_at": "override-v3",
            }
        ],
    )

    with pytest.raises(QFQDataNotReadyError, match="behind"):
        apply_qfq_to_bars(
            _bars("2026-07-31", "2026-08-01", "2026-08-03"),
            scope="stock",
            code="000001",
            db=db,
        )

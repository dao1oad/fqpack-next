from __future__ import annotations

import math

import pytest

from freshquant.backtest.clx.snapshot import (
    QUALITY_ADJ_MISSING,
    QUALITY_ADJ_REBUILT_VERIFIED,
    QUALITY_AMOUNT_INVALID,
    QUALITY_EXCLUDED_CLX,
    QUALITY_EXCLUDED_MATCHING,
    QUALITY_SENTINEL_VOLUME_NORMALIZED,
    SnapshotError,
    SnapshotSpec,
    _build_code_frame,
    _canonical_json,
    _code_bucket,
    _date_stamp,
    _read_universe,
    _sha256_bytes,
    _snapshot_identity_payload,
    publish_snapshot,
)


def _day(
    code: str,
    trade_date: str,
    *,
    close: float = 14.6,
    volume: float = 5.877471754e-39,
    amount: float = 509.3999938965,
) -> dict[str, object]:
    return {
        "code": code,
        "date": trade_date,
        "date_stamp": _date_stamp(trade_date),
        "open": close - 0.05,
        "high": close + 0.05,
        "low": close - 0.10,
        "close": close,
        "vol": volume,
        "amount": amount,
    }


def test_snapshot_spec_freezes_ordered_unique_universe() -> None:
    spec = SnapshotSpec(
        start_date="1991-01-01",
        as_of="2026-07-21",
        codes=("600000", "000001", "600000"),
    )
    assert spec.codes == ("000001", "600000")

    with pytest.raises(ValueError, match="start_date"):
        SnapshotSpec(start_date="2026-07-22", as_of="2026-07-21")
    with pytest.raises(ValueError, match="six digits"):
        SnapshotSpec(start_date="2026-01-01", as_of="2026-07-21", codes=("1",))


class _FakeCollection:
    def __init__(self, *, distinct_codes=(), list_docs=()):
        self.distinct_codes = list(distinct_codes)
        self.list_docs = list(list_docs)

    def distinct(self, field, query):
        assert field == "code"
        assert "date_stamp" in query
        return self.distinct_codes

    def find(self, query, projection, sort):
        del projection, sort
        selected = set(query["code"]["$in"])
        return [doc for doc in self.list_docs if doc["code"] in selected]


def test_universe_comes_from_historical_bars_and_left_joins_current_metadata() -> None:
    database = {
        "stock_day": _FakeCollection(distinct_codes=("600999", "000001")),
        "stock_list": _FakeCollection(
            list_docs=({"code": "000001", "name": "A", "sse": "sz", "sec": "stock_cn"},)
        ),
    }
    rows = _read_universe(
        database, SnapshotSpec(start_date="2000-01-01", as_of="2026-07-21")
    )
    assert [row["code"] for row in rows] == ["000001", "600999"]
    assert rows[0]["in_current_stock_list"] is True
    assert rows[1] == {
        "code": "600999",
        "name": None,
        "exchange": None,
        "security_type": None,
        "volunit": None,
        "decimal_point": None,
        "in_current_stock_list": False,
    }


def test_verified_gap_rebuilds_qfq_and_normalizes_sentinel_volume() -> None:
    evidence = {
        ("000001", "1991-09-30"): {
            "previous": {"date": "1991-09-29", "adj": 0.0086870453},
            "following_within_as_of": {"date": "1991-10-03", "adj": 0.0086870453},
        }
    }
    frame, audit = _build_code_frame(
        code="000001",
        day_docs=[_day("000001", "1991-09-30")],
        adj_docs=[],
        gap_evidence=evidence,
    )
    row = frame.row(0, named=True)
    assert row["raw_volume"] == 0.0
    assert row["volume_shares"] == 0.0
    assert row["raw_amount"] == 0.0
    assert row["adj_factor"] == 0.0086870453
    assert row["adjustment_status"] == "REBUILT_VERIFIED"
    assert row["trade_year"] == 1991
    assert row["code_bucket"] == _code_bucket("000001")
    assert math.isclose(
        row["qfq_close"], row["raw_close"] * row["adj_factor"], rel_tol=0, abs_tol=1e-15
    )
    assert row["quality_mask"] & QUALITY_ADJ_MISSING
    assert row["quality_mask"] & QUALITY_ADJ_REBUILT_VERIFIED
    assert row["quality_mask"] & QUALITY_SENTINEL_VOLUME_NORMALIZED
    assert not row["quality_mask"] & QUALITY_EXCLUDED_CLX
    assert audit[0]["disposition"] == "REBUILT_VERIFIED"


def test_recent_gap_is_retained_raw_but_quarantined_from_both_domains() -> None:
    frame, audit = _build_code_frame(
        code="301234",
        day_docs=[_day("301234", "2026-07-21", close=34.0)],
        adj_docs=[],
        gap_evidence={
            ("301234", "2026-07-21"): {
                "previous": {"date": "2026-07-07", "adj": 1.0},
                "following_within_as_of": None,
            }
        },
    )
    row = frame.row(0, named=True)
    assert row["raw_close"] == 34.0
    assert row["adj_factor"] is None
    assert row["qfq_close"] is None
    assert row["quality_mask"] & QUALITY_EXCLUDED_CLX
    assert row["quality_mask"] & QUALITY_EXCLUDED_MATCHING
    assert audit[0]["disposition"] == "EXCLUDED_ADJ_GAP"


def test_invalid_amount_is_null_and_excluded_from_matching_only() -> None:
    frame, _ = _build_code_frame(
        code="600000",
        day_docs=[_day("600000", "2020-01-02", volume=100.0, amount=-1.0)],
        adj_docs=[{"code": "600000", "date": "2020-01-02", "adj": 0.5}],
        gap_evidence={},
    )
    row = frame.row(0, named=True)
    assert row["raw_amount"] is None
    assert row["adjustment_status"] == "EXACT"
    assert row["quality_mask"] & QUALITY_AMOUNT_INVALID
    assert row["quality_mask"] & QUALITY_EXCLUDED_MATCHING
    assert not row["quality_mask"] & QUALITY_EXCLUDED_CLX


def test_unknown_adjustment_gap_is_a_hard_data_contract_error() -> None:
    with pytest.raises(SnapshotError, match="unexpected missing stock_adj"):
        _build_code_frame(
            code="600000",
            day_docs=[_day("600000", "2020-01-02")],
            adj_docs=[],
            gap_evidence={},
        )


def test_rebuild_requires_equal_neighbor_factors() -> None:
    with pytest.raises(SnapshotError, match="neighboring adj factors disagree"):
        _build_code_frame(
            code="000001",
            day_docs=[_day("000001", "1991-09-30")],
            adj_docs=[],
            gap_evidence={
                ("000001", "1991-09-30"): {
                    "previous": {"date": "1991-09-29", "adj": 0.5},
                    "following_within_as_of": {"date": "1991-10-03", "adj": 0.6},
                }
            },
        )


def test_snapshot_id_identity_changes_when_bar_content_changes_at_same_count() -> None:
    common = {
        "spec": {
            "start_date": "2020-01-01",
            "as_of": "2020-01-02",
            "codes": ["000001"],
        },
        "source_state": {"stock_day": {"count": 2, "max_date": "2020-01-02"}},
        "calendar_file": {
            "path": "calendar/part.parquet",
            "sha256": "calendar",
            "rows": 2,
        },
        "universe_file": {
            "path": "universe/part.parquet",
            "sha256": "universe",
            "rows": 1,
        },
        "adjustment_gaps_file": {
            "path": "quality/adjustment_gaps.parquet",
            "sha256": "gaps",
            "rows": 0,
        },
        "observed_adj_gaps": [],
        "parquet_writer": {"library": "polars", "version": "test"},
    }
    first = _snapshot_identity_payload(
        **common,
        bar_files=[
            {"path": "bars/code=000001/part.parquet", "sha256": "first", "rows": 2}
        ],
    )
    second = _snapshot_identity_payload(
        **common,
        bar_files=[
            {"path": "bars/code=000001/part.parquet", "sha256": "second", "rows": 2}
        ],
    )
    assert _sha256_bytes(_canonical_json(first)) != _sha256_bytes(
        _canonical_json(second)
    )


def test_canonical_publication_requires_confirmed_quiet_window(tmp_path) -> None:
    with pytest.raises(SnapshotError, match="quiet_window_confirmed"):
        publish_snapshot(
            None,
            tmp_path,
            SnapshotSpec(start_date="2020-01-01", as_of="2020-01-02"),
        )

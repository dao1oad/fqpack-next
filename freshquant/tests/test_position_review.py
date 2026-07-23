from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from threading import Barrier, Lock
from time import sleep
from zoneinfo import ZoneInfo

from flask import Flask

from freshquant.order_management.execution_archive import (
    build_account_partition,
)
from freshquant.position_review.replay import review_requests
from freshquant.position_review.repository import PositionReviewRepository
from freshquant.position_review.runtime_repository import (
    PositionReviewRuntimeRepository,
)
from freshquant.position_review.service import (
    PositionReviewService,
    _associate_canonical_trades,
    _build_timeline,
)
from freshquant.rear.position_review.routes import position_review_bp

_TZ = ZoneInfo("Asia/Shanghai")


def _epoch(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=_TZ).timestamp())


class FakePositionReviewRepository:
    def __init__(self):
        self.symbol = "002262"
        self.requests = [
            {
                "request_id": "req_first",
                "action": "sell",
                "source": "strategy",
                "trace_id": "trc_first",
                "intent_id": "int_first",
                "symbol": self.symbol,
                "price": 22.41,
                "quantity": 2300,
                "strategy_context": {
                    "guardian_sell_sources": {
                        "requested_quantity": 2300,
                        "submit_quantity": 2300,
                        "entries": [{"entry_id": "entry_low", "quantity": 2300}],
                    }
                },
                "created_at": "2026-04-29T02:14:04+00:00",
            },
            {
                "request_id": "req_second",
                "action": "sell",
                "source": "strategy",
                "trace_id": "trc_second",
                "intent_id": "int_second",
                "symbol": self.symbol,
                "price": 22.43,
                "quantity": 4500,
                "strategy_context": {
                    "guardian_sell_sources": {
                        "requested_quantity": 4500,
                        "submit_quantity": 4500,
                        "entries": [
                            {"entry_id": "entry_low", "quantity": 2300},
                            {"entry_id": "entry_high", "quantity": 2200},
                        ],
                    }
                },
                "created_at": "2026-04-29T02:33:04+00:00",
            },
        ]
        self.orders = [
            {
                "internal_order_id": "ord_first",
                "request_id": "req_first",
                "broker_order_id": "1477443585",
                "symbol": self.symbol,
                "side": "sell",
                "state": "FILLED",
                "submitted_at": "2026-04-29T10:14:05",
            },
            {
                "internal_order_id": "ord_second",
                "request_id": "req_second",
                "broker_order_id": "1477443586",
                "symbol": self.symbol,
                "side": "sell",
                "state": "FILLED",
                "submitted_at": "2026-04-29T10:33:05",
            },
        ]
        self.xt_trades = [
            {
                "traded_id": "trade_first",
                "order_id": 1477443585,
                "stock_code": "002262.SZ",
                "order_type": 31,
                "traded_volume": 2300,
                "traded_price": 22.41,
                "traded_time": _epoch("2026-04-29T10:14:07"),
            },
            {
                "traded_id": "trade_second",
                "order_id": 1477443586,
                "stock_code": "002262.SZ",
                "order_type": 31,
                "traded_volume": 4500,
                "traded_price": 22.43,
                "traded_time": _epoch("2026-04-29T10:33:07"),
            },
        ]
        self.fills = [
            {
                "execution_fill_id": "fill_first",
                "request_id": "req_first",
                "internal_order_id": "ord_first",
                "broker_trade_id": "trade_first",
                "symbol": self.symbol,
                "side": "sell",
                "quantity": 2300,
                "price": 22.41,
                "trade_time": _epoch("2026-04-29T10:14:07"),
            },
            {
                "execution_fill_id": "fill_second",
                "request_id": "req_second",
                "internal_order_id": "ord_second",
                "broker_trade_id": "trade_second",
                "symbol": self.symbol,
                "side": "sell",
                "quantity": 4500,
                "price": 22.43,
                "trade_time": _epoch("2026-04-29T10:33:07"),
            },
            {
                # Same reused broker id/request, but a foreign symbol. A review
                # repository bug must not be able to count it.
                "execution_fill_id": "fill_polluted",
                "request_id": "req_first",
                "internal_order_id": "ord_first",
                "broker_trade_id": "trade_foreign",
                "symbol": "512800",
                "side": "sell",
                "quantity": 275400,
                "price": 0.808,
                "trade_time": _epoch("2026-07-21T10:00:00"),
            },
        ]
        self.trade_facts = [
            {
                "trade_fact_id": "fact_first",
                "internal_order_id": "ord_first",
                "broker_trade_id": "trade_first",
                "symbol": self.symbol,
                "side": "sell",
                "quantity": 2300,
                "price": 22.41,
                "trade_time": _epoch("2026-04-29T10:14:07"),
            },
            {
                "trade_fact_id": "fact_second",
                "internal_order_id": "ord_second",
                "broker_trade_id": "trade_second",
                "symbol": self.symbol,
                "side": "sell",
                "quantity": 4500,
                "price": 22.43,
                "trade_time": _epoch("2026-04-29T10:33:07"),
            },
        ]
        self.entries = [
            {
                "entry_id": "entry_high",
                "symbol": self.symbol,
                "entry_price": 22.41,
                "original_quantity": 2200,
                "remaining_quantity": 0,
                "trade_time": _epoch("2026-04-17T10:47:08"),
            },
            {
                "entry_id": "entry_low",
                "symbol": self.symbol,
                "entry_price": 21.32,
                "original_quantity": 2300,
                "remaining_quantity": 0,
                "trade_time": _epoch("2026-04-23T13:37:07"),
            },
        ]
        self.slices = [
            {
                "entry_slice_id": "slice_high",
                "entry_id": "entry_high",
                "symbol": self.symbol,
                "guardian_price": 22.41,
                "original_quantity": 2200,
                "remaining_quantity": 0,
            },
            {
                "entry_slice_id": "slice_low",
                "entry_id": "entry_low",
                "symbol": self.symbol,
                "guardian_price": 21.32,
                "original_quantity": 2300,
                "remaining_quantity": 0,
            },
        ]

    def list_symbols(self):
        return [self.symbol]

    def list_xt_trades(self, symbol=None):
        return deepcopy(self.xt_trades)

    def list_xt_positions(self, symbol=None):
        return [{"stock_code": "002262.SZ", "volume": 22300}]

    def list_stock_signals(self, symbol=None):
        return [
            {
                "code": self.symbol,
                "name": "恩华药业",
                "position": "SELL_SHORT",
                "price": 22.41,
                "remark": "回拉中枢下跌",
                "fire_time": datetime.fromisoformat("2026-04-29T10:14:00+08:00"),
            }
        ]

    def list_order_requests(self, symbol=None):
        return deepcopy(self.requests)

    def list_orders(self, symbol=None, *, request_ids=None):
        return deepcopy(self.orders)

    def list_execution_fills(self, symbol, *, request_ids=None):
        return deepcopy(self.fills)

    def list_trade_facts(self, symbol, *, internal_order_ids=None):
        return deepcopy(self.trade_facts)

    def list_position_entries(self, symbol):
        return deepcopy(self.entries)

    def list_entry_slices(self, symbol):
        return deepcopy(self.slices)

    def list_exit_allocations(self, *, entry_ids, trade_fact_ids=None):
        return []

    def list_pm_decisions(self, symbol):
        return [
            {
                "decision_id": "pm_first",
                "trace_id": "trc_first",
                "intent_id": "int_first",
                "symbol": symbol,
                "allowed": True,
            },
            {
                "decision_id": "pm_second",
                "trace_id": "trc_second",
                "intent_id": "int_second",
                "symbol": symbol,
                "allowed": True,
            },
        ]


class FakeRuntimeRepository:
    def list_guardian_events(self, symbol):
        assert symbol == "002262"
        threshold = {
            "last_fill_price": 21.32,
            "top_river_price": 21.5332,
        }
        return {
            "available": True,
            "error": None,
            "items": [
                {
                    "trace_id": "trc_first",
                    "node": "price_threshold_check",
                    "decision_context": {"threshold": threshold},
                },
                {
                    # The runtime trace is stale. Only its historical 1% rule
                    # ratio is reused; inventory is independently replayed.
                    "trace_id": "trc_second",
                    "node": "price_threshold_check",
                    "decision_context": {"threshold": threshold},
                },
            ],
        }


def test_enhua_april_29_replay_detects_second_sell_as_non_compliant():
    service = PositionReviewService(
        repository=FakePositionReviewRepository(),
        runtime_repository=FakeRuntimeRepository(),
        name_resolver=lambda symbol: "恩华药业",
    )

    detail = service.get_symbol_detail("002262.SZ")
    by_id = {item["request_id"]: item for item in detail["reviews"]}

    assert by_id["req_first"]["expected"]["quantity"] == 2300
    assert by_id["req_first"]["actual"]["filled_quantity"] == 2300
    assert by_id["req_first"]["verdict"] == "PASS"
    assert by_id["req_first"]["execution_status"] == "filled"
    assert by_id["req_first"]["quantities"] == {
        "requested": 2300,
        "expected": 2300,
        "filled": 2300,
        "delta": 0,
    }
    assert by_id["req_second"]["expected"]["lowest_guardian_price"] == 22.41
    assert by_id["req_second"]["expected"]["threshold_price"] == 22.6341
    assert by_id["req_second"]["expected"]["quantity"] == 0
    assert by_id["req_second"]["actual"]["filled_quantity"] == 4500
    assert by_id["req_second"]["verdict"] == "FAIL"
    assert by_id["req_second"]["quantities"]["delta"] == 4500
    assert "threshold_not_met" in by_id["req_second"]["reason_codes"]
    assert "duplicate_source_entry" in by_id["req_second"]["reason_codes"]
    assert detail["summary"]["sell_quantity"] == 6800
    assert detail["summary"]["initial_position_quantity"] == 29100
    assert (
        detail["summary"]["initial_position_source"]
        == "derived_from_current_position_and_execution_history"
    )
    assert detail["charts"]["cumulative_quantity"][0] == {
        "time": "2026-04-29T10:14:06+08:00",
        "value": 29100,
        "point_type": "derived_initial",
        "assumption": True,
        "source": "derived_from_current_position_and_execution_history",
    }
    assert detail["charts"]["cumulative_quantity"][1]["value"] == 26800
    assert detail["charts"]["cumulative_quantity"][-1]["value"] == 22300
    assert (
        detail["charts"]["cumulative_quantity"][-1]["value"]
        == detail["symbol"]["current_quantity"]
    )
    assert detail["data_quality"]["initial_position_quantity"] == 29100
    assert (
        detail["data_quality"]["initial_position_source"]
        == "derived_from_current_position_and_execution_history"
    )
    assert detail["data_quality"]["symbol_filtered_execution_fill_count"] == 3
    assert detail["data_quality"]["canonical_trade_count"] == 2
    assert detail["data_quality"]["execution_detail_count"] == 2
    assert len(detail["executions"]) == 2
    first_execution = detail["executions"][0]
    assert first_execution["execution_id"] == first_execution["execution_key"]
    assert first_execution["id"] == first_execution["execution_key"]
    assert first_execution["broker_trade_id"] == "trade_first"
    assert first_execution["broker_order_id"] == "1477443585"
    assert first_execution["trade_time"] == _epoch("2026-04-29T10:14:07")
    assert first_execution["time"] == "2026-04-29T10:14:07+08:00"
    assert first_execution["side"] == "sell"
    assert first_execution["price"] == 22.41
    assert first_execution["quantity"] == 2300
    assert first_execution["request_id"] == "req_first"
    assert first_execution["internal_order_id"] == "ord_first"
    assert first_execution["execution_fill_id"] == "fill_first"
    assert first_execution["trade_fact_id"] == "fact_first"
    assert first_execution["association_quality"] == "high"
    assert first_execution["association_method"] == "execution_fill"


def test_reused_broker_trade_id_with_zero_score_does_not_attach_wrong_fill():
    trade_time = _epoch("2026-05-01T10:00:00")
    results, warnings = _associate_canonical_trades(
        symbol="002262",
        xt_trades=[
            {
                "traded_id": "reused_trade_id",
                "order_id": "correct_order",
                "stock_code": "002262.SZ",
                "side": "buy",
                "traded_volume": 100,
                "traded_price": 10,
                "traded_time": trade_time,
            }
        ],
        requests=[
            {
                "request_id": "req_wrong",
                "symbol": "002262",
                "action": "buy",
                "created_at": "2026-04-30T10:00:00+08:00",
            },
            {
                "request_id": "req_correct",
                "symbol": "002262",
                "action": "buy",
                "created_at": "2026-05-01T09:59:58+08:00",
            },
        ],
        orders=[
            {
                "internal_order_id": "ord_correct",
                "request_id": "req_correct",
                "broker_order_id": "correct_order",
                "symbol": "002262",
                "side": "buy",
                "submitted_at": "2026-05-01T09:59:59+08:00",
            }
        ],
        fills=[
            {
                "execution_fill_id": "fill_reused_from_old_trade",
                "request_id": "req_wrong",
                "broker_trade_id": "reused_trade_id",
                "symbol": "002262",
                "side": "buy",
                # Reused id, same quantity and price, but from the prior day.
                # Time proximity is a hard evidence gate.
                "quantity": 100,
                "price": 10,
                "trade_time": trade_time - 86_400,
            }
        ],
        trade_facts=[],
    )

    assert len(results) == 1
    assert results[0]["request_id"] == "req_correct"
    assert results[0]["execution_fill_id"] is None
    assert results[0]["association_method"] == "order_composite"
    assert results[0]["association_quality"] == "low"
    assert any(
        item["code"] == "broker_trade_id_evidence_mismatch"
        and item["evidence_type"] == "execution_fill"
        for item in warnings
    )


def test_execution_api_anonymizes_account_partitions():
    repository = FakePositionReviewRepository()
    repository.xt_trades[0]["account_id"] = "broker-account-secret-a"
    repository.xt_trades[1]["account_id"] = "broker-account-secret-b"
    detail = PositionReviewService(
        repository=repository,
        runtime_repository=FakeRuntimeRepository(),
        name_resolver=lambda symbol: "恩华药业",
    ).get_symbol_detail("002262")

    assert all("account_id" not in item for item in detail["executions"])
    assert all(
        str(item["account_partition"]).startswith("account:")
        for item in detail["executions"]
    )
    assert detail["data_quality"]["multiple_account_partitions"] is True
    assert detail["data_quality"]["account_partition_count"] == 2
    assert any(
        item["code"] == "multiple_execution_accounts"
        for item in detail["data_quality"]["warnings"]
    )
    serialized = json.dumps(detail, ensure_ascii=False)
    assert "broker-account-secret-a" not in serialized
    assert "broker-account-secret-b" not in serialized


def test_same_execution_identity_is_partitioned_and_associated_per_account():
    trade_time = _epoch("2026-05-01T10:00:00")
    raw_template = {
        "traded_id": "same_broker_trade",
        "order_id": "same_broker_order",
        "stock_code": "002262.SZ",
        "side": "buy",
        "traded_volume": 100,
        "traded_price": 10,
        "traded_time": trade_time,
    }
    requests = [
        {
            "request_id": f"req_{suffix}",
            "symbol": "002262",
            "action": "buy",
            "created_at": "2026-05-01T09:59:59+08:00",
        }
        for suffix in ("a", "b")
    ]
    fills = [
        {
            "execution_fill_id": f"fill_{suffix}",
            "request_id": f"req_{suffix}",
            "internal_order_id": f"ord_{suffix}",
            "broker_trade_id": "same_broker_trade",
            "symbol": "002262",
            "side": "buy",
            "quantity": 100,
            "price": 10,
            "trade_time": trade_time,
            "account_partition": build_account_partition(account_id),
        }
        for suffix, account_id in (
            ("a", "secret-account-a"),
            ("b", "secret-account-b"),
        )
    ]
    xt_trades = [
        {**raw_template, "account_id": account_id}
        for account_id in ("secret-account-a", "secret-account-b")
    ]

    executions, _ = _associate_canonical_trades(
        symbol="002262",
        xt_trades=xt_trades,
        requests=requests,
        orders=[],
        fills=fills,
        trade_facts=[],
    )

    assert {item["request_id"] for item in executions} == {
        "req_a",
        "req_b",
    }
    assert len({item["execution_key"] for item in executions}) == 2
    assert {item["association_quality"] for item in executions} == {"medium"}


def test_ambiguous_accountless_archive_evidence_is_never_counted_twice():
    repository = FakePositionReviewRepository()
    repository.requests = [deepcopy(repository.requests[0])]
    repository.orders = [deepcopy(repository.orders[0])]
    first_trade = deepcopy(repository.xt_trades[0])
    repository.xt_trades = [
        {**first_trade, "account_id": "secret-account-a"},
        {**first_trade, "account_id": "secret-account-b"},
    ]
    ambiguous_fill = deepcopy(repository.fills[0])
    ambiguous_fill["archive_account_resolution"] = "ambiguous_execution_candidate"
    ambiguous_fill["account_partition"] = "unknown"
    repository.fills = [ambiguous_fill]
    repository.trade_facts = []

    detail = PositionReviewService(
        repository=repository,
        runtime_repository=FakeRuntimeRepository(),
        name_resolver=lambda symbol: "恩华药业",
    ).get_symbol_detail("002262")

    assert len(detail["executions"]) == 2
    assert all(item["request_id"] is None for item in detail["executions"])
    assert all(item["execution_fill_id"] is None for item in detail["executions"])
    assert {item["association_quality"] for item in detail["executions"]} == {
        "ambiguous"
    }
    assert detail["reviews"][0]["actual"]["filled_quantity"] == 0
    assert any(
        item["code"] == "ambiguous_execution_account_evidence"
        for item in detail["data_quality"]["warnings"]
    )


def test_equal_score_fill_candidates_for_different_requests_are_ambiguous():
    trade_time = _epoch("2026-05-01T10:00:00")
    raw = {
        "traded_id": "shared_trade",
        "order_id": "shared_order",
        "stock_code": "002262.SZ",
        "side": "buy",
        "traded_volume": 100,
        "traded_price": 10,
        "traded_time": trade_time,
    }
    requests = [
        {
            "request_id": request_id,
            "symbol": "002262",
            "action": "buy",
            "created_at": "2026-05-01T09:59:59+08:00",
        }
        for request_id in ("req_a", "req_b")
    ]
    fills = [
        {
            "execution_fill_id": f"fill_{suffix}",
            "request_id": f"req_{suffix}",
            "internal_order_id": f"ord_{suffix}",
            "broker_trade_id": "shared_trade",
            "symbol": "002262",
            "side": "buy",
            "quantity": 100,
            "price": 10,
            "trade_time": trade_time,
        }
        for suffix in ("a", "b")
    ]

    results, warnings = _associate_canonical_trades(
        symbol="002262",
        xt_trades=[raw],
        requests=requests,
        orders=[],
        fills=fills,
        trade_facts=[],
    )

    assert results[0]["request_id"] is None
    assert results[0]["execution_fill_id"] is None
    assert results[0]["association_quality"] == "ambiguous"
    assert any(item["code"] == "broker_trade_id_evidence_mismatch" for item in warnings)


def test_reused_broker_trade_ids_at_different_times_have_stable_unique_ids():
    raw = {
        "traded_id": "duplicate_trade_id",
        "order_id": "duplicate_order_id",
        "stock_code": "002262.SZ",
        "side": "buy",
        "traded_volume": 100,
        "traded_price": 10,
        "traded_time": _epoch("2026-05-01T10:00:00"),
    }
    executions, _ = _associate_canonical_trades(
        symbol="002262",
        xt_trades=[
            raw,
            {
                **deepcopy(raw),
                "traded_time": _epoch("2026-05-01T10:01:00"),
            },
        ],
        requests=[],
        orders=[],
        fills=[],
        trade_facts=[],
    )

    assert len({item["execution_key"] for item in executions}) == 2
    timeline = _build_timeline(
        signals=[],
        canonical_trades=executions,
        reviews=[],
    )
    assert len({item["id"] for item in timeline}) == 2


def test_exact_duplicate_canonical_rows_are_stably_deduplicated():
    raw = {
        "traded_id": "duplicate_trade_id",
        "order_id": "duplicate_order_id",
        "stock_code": "002262.SZ",
        "side": "buy",
        "traded_volume": 100,
        "traded_price": 10,
        "traded_time": _epoch("2026-05-01T10:00:00"),
        "account_id": "secret-account-a",
    }

    executions, warnings = _associate_canonical_trades(
        symbol="002262",
        xt_trades=[raw, deepcopy(raw)],
        requests=[],
        orders=[],
        fills=[],
        trade_facts=[],
    )

    assert len(executions) == 1
    assert "__duplicate_" not in executions[0]["execution_key"]
    assert any(item["code"] == "duplicate_canonical_execution_row" for item in warnings)


def test_side_conflicting_om_evidence_warns_without_adding_execution():
    trade_time = _epoch("2026-05-01T10:00:00")
    executions, warnings = _associate_canonical_trades(
        symbol="002262",
        xt_trades=[
            {
                "traded_id": "side-conflict",
                "stock_code": "002262.SZ",
                "side": "buy",
                "traded_volume": 100,
                "traded_price": 10,
                "traded_time": trade_time,
            }
        ],
        requests=[],
        orders=[],
        fills=[
            {
                "execution_fill_id": "fill-side-conflict",
                "broker_trade_id": "side-conflict",
                "symbol": "002262",
                "side": "sell",
                "quantity": 100,
                "price": 10,
                "trade_time": trade_time,
                "canonical_conflict": "side_mismatch_with_xt",
            }
        ],
        trade_facts=[
            {
                "trade_fact_id": "fact-side-conflict",
                "broker_trade_id": "side-conflict",
                "symbol": "002262",
                "side": "sell",
                "quantity": 100,
                "price": 10,
                "trade_time": trade_time,
                "canonical_conflict": "side_mismatch_with_xt",
            }
        ],
    )

    assert len(executions) == 1
    assert executions[0]["side"] == "buy"
    assert executions[0]["request_id"] is None
    conflict_warnings = [
        item for item in warnings if item["code"] == "execution_side_conflict"
    ]
    assert len(conflict_warnings) == 1
    assert set(conflict_warnings[0]["evidence_types"]) == {
        "execution_fill",
        "trade_fact",
    }


def test_missing_broker_order_id_never_matches_empty_order_ids():
    trade_time = _epoch("2026-05-01T10:00:00")
    results, _ = _associate_canonical_trades(
        symbol="002262",
        xt_trades=[
            {
                "traded_id": "trade_without_order",
                "stock_code": "002262.SZ",
                "side": "buy",
                "traded_volume": 100,
                "traded_price": 10,
                "traded_time": trade_time,
            }
        ],
        requests=[
            {
                "request_id": "req_empty_order",
                "symbol": "002262",
                "action": "buy",
                "created_at": "2026-05-01T09:59:59+08:00",
            }
        ],
        orders=[
            {
                "internal_order_id": "ord_empty",
                "request_id": "req_empty_order",
                "broker_order_id": "",
                "symbol": "002262",
                "side": "buy",
                "submitted_at": "2026-05-01T09:59:59+08:00",
            }
        ],
        fills=[],
        trade_facts=[],
    )

    assert results[0]["request_id"] is None
    assert results[0]["association_method"] == "unassociated"
    assert results[0]["association_quality"] == "low"


def test_multiple_broker_order_candidates_can_resolve_to_the_same_request():
    trade_time = _epoch("2026-05-01T10:00:00")
    raw = {
        "traded_id": "trade-with-order-candidates",
        "stock_code": "002262.SZ",
        "side": "buy",
        "traded_volume": 100,
        "traded_price": 10,
        "traded_time": trade_time,
        "broker_order_id_candidates": ["broker-A", "broker-B"],
        "xt_snapshot_candidate_count": 2,
    }
    request = {
        "request_id": "req-shared",
        "symbol": "002262",
        "action": "buy",
        "created_at": "2026-05-01T09:59:58+08:00",
    }
    orders = [
        {
            "internal_order_id": f"order-{suffix}",
            "request_id": "req-shared",
            "broker_order_id": f"broker-{suffix}",
            "symbol": "002262",
            "side": "buy",
            "submitted_at": "2026-05-01T09:59:59+08:00",
        }
        for suffix in ("A", "B")
    ]

    executions, warnings = _associate_canonical_trades(
        symbol="002262",
        xt_trades=[raw],
        requests=[request],
        orders=orders,
        fills=[],
        trade_facts=[],
    )

    assert executions[0]["request_id"] == "req-shared"
    assert executions[0]["association_method"] == "order_composite"
    assert not any(item["code"] == "ambiguous_xt_order_candidates" for item in warnings)


def test_unresolved_broker_order_candidate_blocks_partial_request_match():
    trade_time = _epoch("2026-05-01T10:00:00")
    raw = {
        "traded_id": "trade-with-unresolved-order",
        "stock_code": "002262.SZ",
        "side": "buy",
        "traded_volume": 100,
        "traded_price": 10,
        "traded_time": trade_time,
        "broker_order_id_candidates": ["broker-A", "broker-missing"],
        "xt_snapshot_candidate_count": 2,
    }
    request = {
        "request_id": "req-A",
        "symbol": "002262",
        "action": "buy",
        "created_at": "2026-05-01T09:59:58+08:00",
    }
    order = {
        "internal_order_id": "order-A",
        "request_id": "req-A",
        "broker_order_id": "broker-A",
        "symbol": "002262",
        "side": "buy",
        "submitted_at": "2026-05-01T09:59:59+08:00",
    }

    executions, warnings = _associate_canonical_trades(
        symbol="002262",
        xt_trades=[raw],
        requests=[request],
        orders=[order],
        fills=[],
        trade_facts=[],
    )

    assert executions[0]["request_id"] is None
    assert executions[0]["association_method"] == "ambiguous_order_candidates"
    assert executions[0]["association_quality"] == "ambiguous"
    assert any(item["code"] == "ambiguous_xt_order_candidates" for item in warnings)


def test_exact_fill_disambiguates_multiple_broker_order_candidates():
    trade_time = _epoch("2026-05-01T10:00:00")
    raw = {
        "traded_id": "trade-disambiguated-by-fill",
        "stock_code": "002262.SZ",
        "side": "buy",
        "traded_volume": 100,
        "traded_price": 10,
        "traded_time": trade_time,
        "broker_order_id_candidates": ["broker-A", "broker-B"],
        "xt_snapshot_candidate_count": 2,
    }
    requests = [
        {
            "request_id": f"req-{suffix}",
            "symbol": "002262",
            "action": "buy",
            "created_at": "2026-05-01T09:59:58+08:00",
        }
        for suffix in ("A", "B")
    ]
    orders = [
        {
            "internal_order_id": f"order-{suffix}",
            "request_id": f"req-{suffix}",
            "broker_order_id": f"broker-{suffix}",
            "symbol": "002262",
            "side": "buy",
            "submitted_at": "2026-05-01T09:59:59+08:00",
        }
        for suffix in ("A", "B")
    ]
    fill = {
        "execution_fill_id": "fill-B",
        "request_id": "req-B",
        "internal_order_id": "order-B",
        "broker_trade_id": "trade-disambiguated-by-fill",
        "symbol": "002262",
        "side": "buy",
        "quantity": 100,
        "price": 10,
        "trade_time": trade_time,
    }

    executions, warnings = _associate_canonical_trades(
        symbol="002262",
        xt_trades=[raw],
        requests=requests,
        orders=orders,
        fills=[fill],
        trade_facts=[],
    )

    assert executions[0]["request_id"] == "req-B"
    assert executions[0]["association_method"] == "execution_fill"
    assert not any(item["code"] == "ambiguous_xt_order_candidates" for item in warnings)


def test_catalog_cache_single_flights_parallel_summary_and_symbol_requests():
    class CountingRepository(FakePositionReviewRepository):
        def __init__(self):
            super().__init__()
            self.catalog_calls = 0
            self.trade_detail_calls = 0
            self.catalog_lock = Lock()

        def list_symbols(self):
            with self.catalog_lock:
                self.catalog_calls += 1
            sleep(0.05)
            return super().list_symbols()

        def list_xt_trades(self, symbol=None):
            with self.catalog_lock:
                self.trade_detail_calls += 1
            return super().list_xt_trades(symbol)

    repository = CountingRepository()
    service = PositionReviewService(
        repository=repository,
        runtime_repository=FakeRuntimeRepository(),
        name_resolver=lambda symbol: "恩华药业",
        catalog_ttl_seconds=60,
    )
    barrier = Barrier(2)

    def load_summary():
        barrier.wait()
        return service.get_summary()

    def load_symbols():
        barrier.wait()
        return service.list_symbols()

    with ThreadPoolExecutor(max_workers=2) as executor:
        summary_future = executor.submit(load_summary)
        symbols_future = executor.submit(load_symbols)
        summary = summary_future.result()
        symbols = symbols_future.result()

    assert repository.catalog_calls == 1
    assert summary["totals"]["fills"] == 2
    assert summary["totals"]["sell_quantity"] == 6800
    assert symbols["total"] == 1
    assert sorted(
        [
            summary["data_quality"]["catalog_snapshot_cache"]["cache_hit"],
            symbols["data_quality"]["catalog_snapshot_cache"]["cache_hit"],
        ]
    ) == [False, True]
    trade_calls_after_catalog = repository.trade_detail_calls
    cached_detail = service.get_symbol_detail("002262")
    assert cached_detail["symbol"]["code"] == "002262"
    assert repository.trade_detail_calls == trade_calls_after_catalog

    service.get_summary(refresh=True)
    assert repository.catalog_calls == 2


def test_catalog_contains_only_symbols_with_actual_xt_trades():
    class Collection:
        def __init__(self, values):
            self.values = values

        def distinct(self, field):
            return list(self.values)

    repository = PositionReviewRepository(
        business_database={"xt_trades": Collection(["002262.SZ", "600000.SH"])},
        order_database={
            "om_order_requests": Collection(
                ["002262", "600000", "request_only_symbol"]
            ),
            "om_execution_history_archive": Collection([]),
        },
        position_database={},
    )

    assert repository.list_symbols() == ["002262", "600000"]


def test_catalog_uses_one_batch_snapshot_and_one_global_runtime_scan():
    source = FakePositionReviewRepository()

    def replace_symbol(value, symbol):
        if isinstance(value, dict):
            return {key: replace_symbol(item, symbol) for key, item in value.items()}
        if isinstance(value, list):
            return [replace_symbol(item, symbol) for item in value]
        if value == "002262":
            return symbol
        if value == "002262.SZ":
            return f"{symbol}.SZ"
        return value

    base_bundle = {
        "requests": source.requests,
        "orders": source.orders,
        "fills": source.fills[:2],
        "trade_facts": source.trade_facts,
        "entries": source.entries,
        "slices": source.slices,
        "allocations": [],
        "xt_trades": source.xt_trades,
        "positions": source.list_xt_positions(),
        "signals": source.list_stock_signals(),
        "pm_decisions": source.list_pm_decisions("002262"),
    }

    class BatchRepository:
        def __init__(self):
            self.batch_calls = 0

        def load_catalog_bundles(self):
            self.batch_calls += 1
            return {
                symbol: replace_symbol(deepcopy(base_bundle), symbol)
                for symbol in ("002262", "600000")
            }

        def __getattr__(self, name):
            raise AssertionError(f"unexpected per-symbol repository call: {name}")

    class BatchRuntimeRepository:
        def __init__(self):
            self.batch_calls = 0

        def list_guardian_events_by_symbol(self):
            self.batch_calls += 1
            return {
                "available": False,
                "items": [],
                "items_by_symbol": {},
                "error": "test runtime unavailable",
                "truncated": False,
                "max_events": 500000,
            }

        def list_guardian_events(self, symbol):
            raise AssertionError("per-symbol ClickHouse scan is forbidden")

    repository = BatchRepository()
    runtime_repository = BatchRuntimeRepository()
    service = PositionReviewService(
        repository=repository,
        runtime_repository=runtime_repository,
        name_resolver=lambda symbol: symbol,
    )

    summary = service.get_summary()

    assert summary["totals"]["symbols"] == 2
    assert summary["totals"]["fills"] == 4
    assert repository.batch_calls == 1
    assert runtime_repository.batch_calls == 1
    assert service.get_symbol_detail("600000")["summary"]["fill_count"] == 2
    assert repository.batch_calls == 1
    assert runtime_repository.batch_calls == 1


def test_missing_current_snapshot_and_negative_opening_balance_are_explicit():
    repository = FakePositionReviewRepository()
    repository.requests = repository.requests[:1]
    repository.orders = repository.orders[:1]
    repository.xt_trades = repository.xt_trades[:1]
    repository.fills = repository.fills[:1]
    repository.trade_facts = repository.trade_facts[:1]
    repository.requests[0]["action"] = "buy"
    repository.orders[0]["side"] = "buy"
    repository.xt_trades[0]["side"] = "buy"
    repository.fills[0]["side"] = "buy"
    repository.trade_facts[0]["side"] = "buy"
    repository.list_xt_positions = lambda symbol=None: []

    detail = PositionReviewService(
        repository=repository,
        runtime_repository=FakeRuntimeRepository(),
        name_resolver=lambda symbol: "恩华药业",
    ).get_symbol_detail("002262")

    assert detail["summary"]["initial_position_quantity"] == -2300
    assert detail["data_quality"]["current_position_snapshot_available"] is False
    warning_codes = {item["code"] for item in detail["data_quality"]["warnings"]}
    assert "current_position_snapshot_missing" in warning_codes
    assert "negative_derived_initial_position" in warning_codes


def test_runtime_repository_collects_all_pages_and_marks_safety_truncation():
    events = [
        {"event_id": "threshold", "node": "price_threshold_check"},
        {"event_id": "sellable", "node": "sellable_volume_check"},
    ]
    observed_filters = []

    class PagingStore:
        def list_events(self, *, cursor_event_id="", **kwargs):
            observed_filters.append(kwargs["filters"])
            if not cursor_event_id:
                return {
                    "items": [events[0]],
                    "next_cursor": {
                        "ts": "2026-04-29T10:00:00+08:00",
                        "event_id": "threshold",
                    },
                }
            return {"items": [events[1]], "next_cursor": None}

    repository = PositionReviewRuntimeRepository(store=PagingStore())
    complete = repository.list_guardian_events("002262", page_size=1, max_events=10)
    assert [item["node"] for item in complete["items"]] == [
        "price_threshold_check",
        "sellable_volume_check",
    ]
    assert complete["truncated"] is False
    assert observed_filters[0]["node"] == [
        "price_threshold_check",
        "sellable_volume_check",
    ]

    truncated = repository.list_guardian_events("002262", page_size=1, max_events=1)
    assert truncated["truncated"] is True
    assert truncated["max_events"] == 1
    assert [item["node"] for item in truncated["items"]] == ["price_threshold_check"]


def test_runtime_evidence_truncation_is_exposed_as_data_quality_warning():
    class TruncatedRuntimeRepository(FakeRuntimeRepository):
        def list_guardian_events(self, symbol):
            result = super().list_guardian_events(symbol)
            result.update({"truncated": True, "max_events": 2})
            return result

    detail = PositionReviewService(
        repository=FakePositionReviewRepository(),
        runtime_repository=TruncatedRuntimeRepository(),
        name_resolver=lambda symbol: "恩华药业",
    ).get_symbol_detail("002262")

    assert detail["data_quality"]["runtime_evidence_truncated"] is True
    assert any(
        item["code"] == "runtime_evidence_truncated"
        for item in detail["data_quality"]["warnings"]
    )


def test_guardian_buy_snapshot_quantity_is_independently_recomputed():
    request = {
        "request_id": "req_buy",
        "symbol": "002262",
        "action": "buy",
        "quantity": 4800,
        "price": 20.76,
        "created_at": "2026-05-18T02:14:00+00:00",
        "strategy_context": {
            "guardian_buy_grid": {
                "base_amount": 50000,
                "multiplier": 2,
                "source_price": 20.76,
                "grid_level": "BUY-1",
                "path": "holding_add",
            }
        },
    }

    reviews = review_requests(
        symbol="002262",
        requests=[request],
        orders_by_request={"req_buy": []},
        canonical_trades=[],
        inventory=[],
        threshold_ratios={},
    )

    assert reviews[0]["expected"]["quantity"] == 4800
    assert reviews[0]["verdict"] == "PASS"


def test_guardian_new_open_uses_initial_amount_without_grid_multiplier():
    request = {
        "request_id": "req_new_open",
        "symbol": "002262",
        "action": "buy",
        "quantity": 4800,
        "price": 20.76,
        "created_at": "2026-05-18T02:14:00+00:00",
        "strategy_context": {
            "guardian_buy_grid": {
                "initial_amount": 100000,
                "base_amount": 50000,
                "multiplier": 4,
                "source_price": 20.76,
                "path": "new_open",
            }
        },
    }

    review = review_requests(
        symbol="002262",
        requests=[request],
        orders_by_request={},
        canonical_trades=[],
        inventory=[],
        threshold_ratios={},
    )[0]

    assert review["expected"]["quantity"] == 4800
    assert review["expected"]["path"] == "new_open"
    assert review["expected"]["formula"] == (
        "floor(initial_amount / source_price / 100) * 100"
    )
    assert "multiplier" not in review["expected"]
    assert review["verdict"] == "PASS"


def test_unknown_threshold_mode_is_insufficient_when_percent_and_atr_diverge():
    request = {
        "request_id": "req_threshold_ambiguous",
        "symbol": "002262",
        "action": "sell",
        "quantity": 100,
        "price": 10.7,
        "trace_id": "trc_threshold_ambiguous",
        "created_at": "2026-05-18T02:14:00+00:00",
        "strategy_context": {
            "guardian_sell_sources": {
                "requested_quantity": 100,
                "submit_quantity": 100,
                "entries": [{"entry_id": "entry_1", "quantity": 100}],
            }
        },
    }
    inventory = [
        {
            "entry_id": "entry_1",
            "entry_slice_id": "slice_1",
            "guardian_price": 10,
            "initial_quantity": 100,
            "remaining_quantity": 100,
            "available_at": _epoch("2026-05-17T10:00:00"),
            "synthetic": False,
        }
    ]

    review = review_requests(
        symbol="002262",
        requests=[request],
        orders_by_request={},
        canonical_trades=[],
        inventory=inventory,
        threshold_ratios={
            "trc_threshold_ambiguous": {
                "mode": None,
                "ratio": 1.05,
                "delta": 1,
            }
        },
        sell_constraints={"trc_threshold_ambiguous": {"can_use_volume": 100}},
    )[0]

    assert review["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert review["expected"]["quantity"] is None
    assert review["expected"]["threshold_mode"] == "ambiguous"
    assert {
        item["raw_quantity"] for item in review["expected"]["threshold_candidates"]
    } == {0, 100}
    assert "historical_threshold_mode_ambiguous" in review["reason_codes"]


def test_guardian_sell_applies_historical_can_use_volume_cap():
    request = {
        "request_id": "req_sell_cap",
        "symbol": "002262",
        "action": "sell",
        "quantity": 300,
        "price": 11,
        "trace_id": "trc_cap",
        "created_at": "2026-05-18T02:14:00+00:00",
        "strategy_context": {
            "guardian_sell_sources": {
                "requested_quantity": 500,
                "submit_quantity": 300,
                "entries": [{"entry_id": "entry_1", "quantity": 300}],
            }
        },
    }
    inventory = [
        {
            "entry_id": "entry_1",
            "entry_slice_id": "slice_1",
            "guardian_price": 10,
            "initial_quantity": 500,
            "remaining_quantity": 500,
            "available_at": _epoch("2026-05-17T10:00:00"),
            "synthetic": False,
        }
    ]

    reviews = review_requests(
        symbol="002262",
        requests=[request],
        orders_by_request={},
        canonical_trades=[],
        inventory=inventory,
        threshold_ratios={"trc_cap": 1.01},
        sell_constraints={"trc_cap": {"can_use_volume": 300}},
    )

    assert reviews[0]["expected"]["raw_quantity"] == 500
    assert reviews[0]["expected"]["quantity"] == 300
    assert reviews[0]["expected"]["can_use_volume"] == 300
    assert reviews[0]["verdict"] == "PASS"


def test_same_second_xt_fill_is_replayed_after_its_request():
    request = {
        "request_id": "req_same_second",
        "symbol": "002262",
        "action": "sell",
        "quantity": 100,
        "price": 11,
        "trace_id": "trc_same_second",
        "created_at": "2026-07-16T03:12:05.529174+00:00",
        "strategy_context": {
            "guardian_sell_sources": {
                "requested_quantity": 100,
                "submit_quantity": 100,
                "entries": [{"entry_id": "entry_1", "quantity": 100}],
            }
        },
    }
    inventory = [
        {
            "entry_id": "entry_1",
            "entry_slice_id": "slice_1",
            "guardian_price": 10,
            "initial_quantity": 100,
            "remaining_quantity": 100,
            "available_at": _epoch("2026-07-15T13:50:02"),
            "synthetic": False,
        }
    ]
    fill_epoch = int(datetime.fromisoformat("2026-07-16T11:12:05+08:00").timestamp())

    reviews = review_requests(
        symbol="002262",
        requests=[request],
        orders_by_request={
            "req_same_second": [
                {
                    "request_id": "req_same_second",
                    "state": "FILLED",
                }
            ]
        },
        canonical_trades=[
            {
                "request_id": "req_same_second",
                "broker_trade_id": "trade_same_second",
                "symbol": "002262",
                "side": "sell",
                "quantity": 100,
                "price": 11,
                "trade_time": fill_epoch,
                "association_quality": "high",
            }
        ],
        inventory=inventory,
        threshold_ratios={"trc_same_second": 1.01},
        sell_constraints={
            "trc_same_second": {
                "can_use_volume": 100,
                "traced_raw_quantity": 100,
            }
        },
    )

    assert reviews[0]["expected"]["quantity"] == 100
    assert reviews[0]["verdict"] == "PASS"
    assert reviews[0]["execution_status"] == "filled"


def test_four_state_contract_covers_insufficient_and_not_applicable():
    requests = [
        {
            "request_id": "req_sell",
            "symbol": "002262",
            "action": "sell",
            "quantity": 100,
            "price": 10,
            "created_at": "2026-05-01T02:00:00+00:00",
            "strategy_context": {
                "guardian_sell_sources": {
                    "entries": [{"entry_id": "entry_1", "quantity": 100}]
                }
            },
        },
        {
            "request_id": "req_manual",
            "symbol": "002262",
            "action": "buy",
            "quantity": 100,
            "price": 10,
            "created_at": "2026-05-01T03:00:00+00:00",
            "strategy_context": {},
        },
    ]
    inventory = [
        {
            "entry_id": "entry_1",
            "entry_slice_id": "slice_1",
            "guardian_price": 9,
            "initial_quantity": 100,
            "remaining_quantity": 100,
            "available_at": _epoch("2026-04-30T10:00:00"),
            "synthetic": False,
        }
    ]

    reviews = review_requests(
        symbol="002262",
        requests=requests,
        orders_by_request={},
        canonical_trades=[],
        inventory=inventory,
        threshold_ratios={},
    )

    assert reviews[0]["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert reviews[1]["verdict"] == "NOT_APPLICABLE"


def test_position_review_routes_expose_summary_symbols_and_detail(monkeypatch):
    class FakeService:
        def __init__(self):
            self.calls = []

        def get_summary(self, *, refresh=False):
            self.calls.append(("summary", refresh))
            return {"totals": {"symbols": 1}}

        def list_symbols(self, **filters):
            self.calls.append(("symbols", filters["refresh"]))
            return {
                "rows": [{"symbol": "002262", "verdict": "FAIL"}],
                "total": 1,
                "page": filters["page"],
                "size": filters["size"],
            }

        def get_symbol_detail(self, symbol, *, refresh=False):
            if symbol == "missing":
                raise ValueError("symbol not found")
            return {"symbol": {"code": "002262", "name": "恩华药业"}}

    fake_service = FakeService()
    monkeypatch.setattr(
        "freshquant.rear.position_review.routes._get_position_review_service",
        lambda: fake_service,
    )
    app = Flask("position-review-routes")
    app.register_blueprint(position_review_bp)
    client = app.test_client()

    assert (
        client.get("/api/position-review/summary?refresh=true").get_json()["totals"][
            "symbols"
        ]
        == 1
    )
    symbols = client.get(
        "/api/position-review/symbols?page=2&size=10&verdict=FAIL&refresh=1"
    ).get_json()
    assert symbols["page"] == 2
    assert symbols["rows"][0]["symbol"] == "002262"
    assert client.get("/api/position-review/symbols/002262").status_code == 200
    assert client.get("/api/position-review/symbols/missing").status_code == 404
    assert fake_service.calls[:2] == [("summary", True), ("symbols", True)]
    assert client.get("/api/position-review/summary?refresh=maybe").status_code == 400

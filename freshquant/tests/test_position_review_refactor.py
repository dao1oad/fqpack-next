# -*- coding: utf-8 -*-

"""Tests for the position-review refactor read-model projections."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask

from freshquant.position_review.chart_projection import (
    build_conditions,
    build_holding_cycles,
    build_position_series_from_fills,
    replay_cost_basis,
    resolve_signal_type,
    signal_meta,
    signal_type_registry_payload,
)
from freshquant.position_review.portfolio_projection import (
    build_portfolio_contributions,
    build_portfolio_series,
    build_portfolio_summary,
)
from freshquant.position_review.service import PositionReviewService
from freshquant.rear.position_review.routes import position_review_bp

_TZ = ZoneInfo("Asia/Shanghai")


def _epoch(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=_TZ).timestamp())


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp, tz=_TZ).isoformat()


def _noop_name(symbol):
    return f"{symbol}标的"


def _canonical_trades_from_xt(repo):
    """Convert raw XT trades to the canonical fill shape used by the service."""

    trades = []
    for trade in repo.xt_trades:
        request_id = None
        internal_order_id = None
        for request in repo.requests:
            if str(request.get("request_id") or "").strip() == str(
                trade.get("request_id") or ""
            ):
                request_id = str(request["request_id"])
                break
        for order in repo.orders:
            if str(order.get("broker_order_id") or "") == str(
                trade.get("order_id") or ""
            ):
                internal_order_id = str(order["internal_order_id"])
                request_id = str(order["request_id"])
                break
        trades.append(
            {
                "execution_key": f"exec_{trade['traded_id']}",
                "id": f"exec_{trade['traded_id']}",
                "symbol": repo.symbol,
                "account_partition": "partition_a",
                "side": "sell" if trade["traded_id"] == "trade_sell" else "buy",
                "quantity": trade["traded_volume"],
                "price": trade["traded_price"],
                "trade_time": trade["traded_time"],
                "request_id": request_id,
                "internal_order_id": internal_order_id,
                "broker_trade_id": trade["traded_id"],
                "association_quality": "high",
            }
        )
    return trades


class FakeBuySellRepository:
    """Entry/slice/allocation ledger fixture with multi-fill buy and sell."""

    symbol = "002262"

    def __init__(self):
        self.requests = [
            {
                "request_id": "buy_req",
                "action": "buy",
                "source": "strategy",
                "trace_id": "trc_buy",
                "intent_id": "int_buy",
                "symbol": self.symbol,
                "price": 10.25,
                "quantity": 10000,
                "strategy_context": {
                    "guardian_buy_grid": {
                        "path": "new_open",
                        "initial_amount": 102700.0,
                        "source_price": 10.27,
                        "grid_level": "1",
                    }
                },
                "created_at": "2026-04-29T02:15:00+00:00",
            },
            {
                "request_id": "sell_req",
                "action": "sell",
                "source": "strategy",
                "trace_id": "trc_sell",
                "intent_id": "int_sell",
                "symbol": self.symbol,
                "price": 10.35,
                "quantity": 4000,
                "strategy_context": {
                    "guardian_sell_sources": {
                        "requested_quantity": 4000,
                        "submit_quantity": 4000,
                        "entries": [
                            {"entry_id": "entry_buy", "quantity": 4000},
                        ],
                    }
                },
                "created_at": "2026-04-29T02:30:00+00:00",
            },
        ]
        self.orders = [
            {
                "internal_order_id": "ord_buy",
                "request_id": "buy_req",
                "broker_order_id": "1477440001",
                "symbol": self.symbol,
                "side": "buy",
                "state": "FILLED",
                "submitted_at": "2026-04-29T10:15:02",
            },
            {
                "internal_order_id": "ord_sell",
                "request_id": "sell_req",
                "broker_order_id": "1477440002",
                "symbol": self.symbol,
                "side": "sell",
                "state": "FILLED",
                "submitted_at": "2026-04-29T10:30:00",
            },
        ]
        self.xt_trades = [
            {
                "traded_id": "trade_buy_1",
                "order_id": 1477440001,
                "stock_code": "002262.SZ",
                "order_type": 23,
                "traded_volume": 4000,
                "traded_price": 10.26,
                "traded_time": _epoch("2026-04-29T10:15:03"),
            },
            {
                "traded_id": "trade_buy_2",
                "order_id": 1477440001,
                "stock_code": "002262.SZ",
                "order_type": 23,
                "traded_volume": 3000,
                "traded_price": 10.27,
                "traded_time": _epoch("2026-04-29T10:17:20"),
            },
            {
                "traded_id": "trade_buy_3",
                "order_id": 1477440001,
                "stock_code": "002262.SZ",
                "order_type": 23,
                "traded_volume": 3000,
                "traded_price": 10.28,
                "traded_time": _epoch("2026-04-29T10:20:12"),
            },
            {
                "traded_id": "trade_sell",
                "order_id": 1477440002,
                "stock_code": "002262.SZ",
                "order_type": 31,
                "traded_volume": 4000,
                "traded_price": 10.35,
                "traded_time": _epoch("2026-04-29T10:30:05"),
            },
        ]
        self.fills = [
            {
                "execution_fill_id": f"fill_buy_{index}",
                "request_id": "buy_req",
                "internal_order_id": "ord_buy",
                "broker_trade_id": trade["traded_id"],
                "symbol": self.symbol,
                "side": "buy",
                "quantity": trade["traded_volume"],
                "price": trade["traded_price"],
                "trade_time": trade["traded_time"],
            }
            for index, trade in enumerate(self.xt_trades[:3])
        ]
        self.fills.append(
            {
                "execution_fill_id": "fill_sell",
                "request_id": "sell_req",
                "internal_order_id": "ord_sell",
                "broker_trade_id": "trade_sell",
                "symbol": self.symbol,
                "side": "sell",
                "quantity": 4000,
                "price": 10.35,
                "trade_time": _epoch("2026-04-29T10:30:05"),
            }
        )
        self.trade_facts = [
            {
                "trade_fact_id": f"fact_buy_{index}",
                "internal_order_id": "ord_buy",
                "broker_trade_id": trade["traded_id"],
                "symbol": self.symbol,
                "side": "buy",
                "quantity": trade["traded_volume"],
                "price": trade["traded_price"],
                "trade_time": trade["traded_time"],
            }
            for index, trade in enumerate(self.xt_trades[:3])
        ]
        self.trade_facts.append(
            {
                "trade_fact_id": "fact_sell",
                "internal_order_id": "ord_sell",
                "broker_trade_id": "trade_sell",
                "symbol": self.symbol,
                "side": "sell",
                "quantity": 4000,
                "price": 10.35,
                "trade_time": _epoch("2026-04-29T10:30:05"),
            }
        )
        self.entries = [
            {
                "entry_id": "entry_buy",
                "symbol": self.symbol,
                "entry_price": 10.27,
                "original_quantity": 10000,
                "remaining_quantity": 6000,
                "trade_time": _epoch("2026-04-29T10:15:00"),
            }
        ]
        self.slices = [
            {
                "entry_slice_id": "slice_buy",
                "entry_id": "entry_buy",
                "symbol": self.symbol,
                "guardian_price": 10.27,
                "original_quantity": 10000,
                "remaining_quantity": 6000,
            }
        ]
        self.allocations = [
            {
                "allocation_id": "alloc_sell",
                "entry_id": "entry_buy",
                "entry_slice_id": "slice_buy",
                "allocated_quantity": 4000,
                "price": 10.35,
            }
        ]
        self.signals = [
            {
                "code": self.symbol,
                "name": "恩华药业",
                "position": "BUY_LONG",
                "price": 10.25,
                "remark": "反转买点",
                "request_id": "buy_req",
                "fire_time": datetime.fromisoformat("2026-04-29T10:15:00+08:00"),
            }
        ]
        self.xt_positions = [
            {
                "stock_code": "002262.SZ",
                "volume": 6000,
                "avg_price": 10.27,
                "market_value": 62100.0,
                "last_price": 10.35,
            }
        ]

    def list_symbols(self):
        return [self.symbol]

    def load_catalog_bundles(self):
        return {
            symbol: {
                "requests": self.list_order_requests(symbol),
                "orders": self.list_orders(symbol),
                "fills": self.list_execution_fills(symbol),
                "trade_facts": self.list_trade_facts(symbol),
                "entries": self.list_position_entries(symbol),
                "slices": self.list_entry_slices(symbol),
                "allocations": self.list_exit_allocations(entry_ids=[]),
                "xt_trades": self.list_xt_trades(symbol),
                "positions": self.list_xt_positions(symbol),
                "signals": self.list_stock_signals(symbol),
                "pm_decisions": self.list_pm_decisions(symbol),
            }
            for symbol in self.list_symbols()
        }

    def list_xt_trades(self, symbol=None):
        if symbol and str(symbol).strip() != self.symbol:
            return []
        return deepcopy(self.xt_trades)

    def list_xt_positions(self, symbol=None):
        items = deepcopy(self.xt_positions)
        if symbol:
            normalized = str(symbol).strip()
            items = [
                item
                for item in items
                if str(item.get("stock_code") or "").split(".", 1)[0] == normalized
            ]
        return items

    def list_stock_signals(self, symbol=None):
        if symbol and str(symbol).strip() != self.symbol:
            return []
        return deepcopy(self.signals)

    def list_order_requests(self, symbol=None):
        if symbol and str(symbol).strip() != self.symbol:
            return []
        return deepcopy(self.requests)

    def list_orders(self, symbol=None, *, request_ids=None):
        if symbol and str(symbol).strip() != self.symbol:
            return []
        return deepcopy(self.orders)

    def list_execution_fills(self, symbol, *, request_ids=None):
        if symbol and str(symbol).strip() != self.symbol:
            return []
        return deepcopy(self.fills)

    def list_trade_facts(self, symbol, *, internal_order_ids=None):
        if symbol and str(symbol).strip() != self.symbol:
            return []
        return deepcopy(self.trade_facts)

    def list_position_entries(self, symbol):
        if symbol and str(symbol).strip() != self.symbol:
            return []
        return deepcopy(self.entries)

    def list_entry_slices(self, symbol):
        if symbol and str(symbol).strip() != self.symbol:
            return []
        return deepcopy(self.slices)

    def list_exit_allocations(self, *, entry_ids, trade_fact_ids=None):
        if entry_ids and not any(
            str(entry_id) in {str(item["entry_id"]) for item in self.allocations}
            for entry_id in entry_ids
        ):
            return []
        return deepcopy(self.allocations)

    def list_pm_decisions(self, symbol):
        if symbol and str(symbol).strip() != self.symbol:
            return []
        return []

    def list_xt_assets(self):
        return [
            {
                "account_id": "068000076370",
                "cash": 5000.9,
                "market_value": 62100.0,
                "total_asset": 67100.9,
                "updated_at": "2026-08-07T18:34:16+00:00",
            }
        ]

    def list_credit_asset_snapshots(self, *, limit=20_000):
        return []


class FakeLedgerSellRepository(FakeBuySellRepository):
    """Two entries; the sell consumes the low-cost slice first."""

    def __init__(self):
        super().__init__()
        self.requests = [
            {
                "request_id": "buy_low",
                "action": "buy",
                "source": "strategy",
                "trace_id": "trc_low",
                "symbol": self.symbol,
                "price": 21.32,
                "quantity": 2300,
                "strategy_context": {
                    "guardian_buy_grid": {
                        "path": "new_open",
                        "initial_amount": 49036.0,
                        "source_price": 21.32,
                        "grid_level": "1",
                    }
                },
                "created_at": "2026-04-23T05:37:00+00:00",
            },
            {
                "request_id": "buy_high",
                "action": "buy",
                "source": "strategy",
                "trace_id": "trc_high",
                "symbol": self.symbol,
                "price": 22.41,
                "quantity": 2200,
                "strategy_context": {
                    "guardian_buy_grid": {
                        "path": "holding_add",
                        "base_amount": 49302.0,
                        "multiplier": 1.0,
                        "source_price": 22.41,
                        "grid_level": "2",
                    }
                },
                "created_at": "2026-04-17T02:47:00+00:00",
            },
            {
                "request_id": "sell_low_first",
                "action": "sell",
                "source": "strategy",
                "trace_id": "trc_sell",
                "symbol": self.symbol,
                "price": 23.0,
                "quantity": 2300,
                "strategy_context": {
                    "guardian_sell_sources": {
                        "requested_quantity": 2300,
                        "submit_quantity": 2300,
                        "entries": [
                            {"entry_id": "entry_low", "quantity": 2300},
                        ],
                    }
                },
                "created_at": "2026-04-29T02:14:00+00:00",
            },
        ]
        self.xt_trades = [
            {
                "traded_id": "trade_low",
                "order_id": 1477441001,
                "stock_code": "002262.SZ",
                "traded_volume": 2300,
                "traded_price": 21.32,
                "traded_time": _epoch("2026-04-23T13:37:07"),
            },
            {
                "traded_id": "trade_high",
                "order_id": 1477441002,
                "stock_code": "002262.SZ",
                "traded_volume": 2200,
                "traded_price": 22.41,
                "traded_time": _epoch("2026-04-17T10:47:08"),
            },
            {
                "traded_id": "trade_sell",
                "order_id": 1477441003,
                "stock_code": "002262.SZ",
                "traded_volume": 2300,
                "traded_price": 23.0,
                "traded_time": _epoch("2026-04-29T10:14:07"),
            },
        ]
        self.fills = [
            {
                "execution_fill_id": f"fill_{trade['traded_id']}",
                "request_id": (
                    "buy_low"
                    if trade["traded_id"] == "trade_low"
                    else (
                        "buy_high"
                        if trade["traded_id"] == "trade_high"
                        else "sell_low_first"
                    )
                ),
                "internal_order_id": (
                    "ord_low"
                    if trade["traded_id"] == "trade_low"
                    else (
                        "ord_high" if trade["traded_id"] == "trade_high" else "ord_sell"
                    )
                ),
                "broker_trade_id": trade["traded_id"],
                "symbol": self.symbol,
                "side": "sell" if trade["traded_id"] == "trade_sell" else "buy",
                "quantity": trade["traded_volume"],
                "price": trade["traded_price"],
                "trade_time": trade["traded_time"],
            }
            for trade in self.xt_trades
        ]
        self.trade_facts = deepcopy(self.fills)
        for index, fact in enumerate(self.trade_facts):
            fact["trade_fact_id"] = f"fact_{index}"
        self.entries = [
            {
                "entry_id": "entry_low",
                "symbol": self.symbol,
                "entry_price": 21.32,
                "original_quantity": 2300,
                "remaining_quantity": 0,
                "trade_time": _epoch("2026-04-23T13:37:07"),
            },
            {
                "entry_id": "entry_high",
                "symbol": self.symbol,
                "entry_price": 22.41,
                "original_quantity": 2200,
                "remaining_quantity": 2200,
                "trade_time": _epoch("2026-04-17T10:47:08"),
            },
        ]
        self.slices = [
            {
                "entry_slice_id": "slice_low",
                "entry_id": "entry_low",
                "symbol": self.symbol,
                "guardian_price": 21.32,
                "original_quantity": 2300,
                "remaining_quantity": 0,
            },
            {
                "entry_slice_id": "slice_high",
                "entry_id": "entry_high",
                "symbol": self.symbol,
                "guardian_price": 22.41,
                "original_quantity": 2200,
                "remaining_quantity": 2200,
            },
        ]
        self.allocations = [
            {
                "allocation_id": "alloc_sell_low",
                "entry_id": "entry_low",
                "entry_slice_id": "slice_low",
                "allocated_quantity": 2300,
                "price": 23.0,
            }
        ]
        self.orders = [
            {
                "internal_order_id": "ord_low",
                "request_id": "buy_low",
                "broker_order_id": "1477441001",
                "symbol": self.symbol,
                "side": "buy",
                "state": "FILLED",
            },
            {
                "internal_order_id": "ord_high",
                "request_id": "buy_high",
                "broker_order_id": "1477441002",
                "symbol": self.symbol,
                "side": "buy",
                "state": "FILLED",
            },
            {
                "internal_order_id": "ord_sell",
                "request_id": "sell_low_first",
                "broker_order_id": "1477441003",
                "symbol": self.symbol,
                "side": "sell",
                "state": "FILLED",
            },
        ]
        self.signals = []
        self.allocations = []


class FakeFlattenRebuildRepository:
    """Cost-price flatten ledger with a reconstructed buy request + order."""

    symbol = "600917"

    def __init__(self):
        self.entry = {
            "entry_id": "entry_flatten_600917",
            "source_ref_type": "position_snapshot_flatten",
            "entry_type": "position_snapshot_flatten",
            "symbol": self.symbol,
            "stock_code": self.symbol,
            "entry_price": 5.527529,
            "buy_price_real": 5.527529,
            "original_quantity": 20000,
            "remaining_quantity": 20000,
            "trade_time": _epoch("2026-08-07T12:31:52"),
            "date": 20260807,
            "time": "12:31:52",
            "source": "order_ledger_rebuild",
            "arrange_mode": "position_snapshot_flatten",
            "status": "OPEN",
            "account_id": "068000076370",
        }
        self.request = {
            "request_id": "req_rebuilt_entry_flatten_600917",
            "action": "buy",
            "side": "buy",
            "symbol": self.symbol,
            "stock_code": self.symbol,
            "price": 5.527529,
            "quantity": 20000,
            "status": "FILLED",
            "state": "FILLED",
            "source": "order_ledger_rebuild",
            "rebuild_source": "position_snapshot_flatten",
            "rebuilt_open": True,
            "data_quality": "reconstructed",
            "entry_id": self.entry["entry_id"],
            "created_at": "2026-08-07T12:31:52+08:00",
            "trade_time": self.entry["trade_time"],
        }
        self.order = {
            "internal_order_id": "ord_rebuilt_entry_flatten_600917",
            "request_id": self.request["request_id"],
            "broker_order_id": None,
            "symbol": self.symbol,
            "side": "buy",
            "state": "FILLED",
            "status": "FILLED",
            "price": 5.527529,
            "quantity": 20000,
            "filled_quantity": 20000,
            "source": "order_ledger_rebuild",
            "rebuild_source": "position_snapshot_flatten",
            "rebuilt_open": True,
            "data_quality": "reconstructed",
            "entry_id": self.entry["entry_id"],
            "submitted_at": "2026-08-07T12:31:52+08:00",
            "trade_time": self.entry["trade_time"],
        }
        self.slice = {
            "entry_slice_id": "slice_flatten_600917",
            "entry_id": self.entry["entry_id"],
            "symbol": self.symbol,
            "guardian_price": 5.527529,
            "original_quantity": 20000,
            "remaining_quantity": 20000,
            "status": "OPEN",
        }
        self.position = {
            "stock_code": "600917.SH",
            "volume": 20000,
            "avg_price": 5.527529,
            "market_value": 96400.0,
            "last_price": 0.0,
        }

    def list_symbols(self):
        return [self.symbol]

    def load_catalog_bundles(self):
        return {
            symbol: {
                "requests": self.list_order_requests(symbol),
                "orders": self.list_orders(symbol),
                "fills": self.list_execution_fills(symbol),
                "trade_facts": self.list_trade_facts(symbol),
                "entries": self.list_position_entries(symbol),
                "slices": self.list_entry_slices(symbol),
                "allocations": self.list_exit_allocations(entry_ids=[]),
                "xt_trades": self.list_xt_trades(symbol),
                "positions": self.list_xt_positions(symbol),
                "signals": self.list_stock_signals(symbol),
                "pm_decisions": self.list_pm_decisions(symbol),
            }
            for symbol in self.list_symbols()
        }

    def list_xt_trades(self, symbol=None):
        return []

    def list_xt_positions(self, symbol=None):
        if symbol and str(symbol).strip() != self.symbol:
            return []
        return [deepcopy(self.position)]

    def list_stock_signals(self, symbol=None):
        return []

    def list_order_requests(self, symbol=None):
        if symbol and str(symbol).strip() != self.symbol:
            return []
        return [deepcopy(self.request)]

    def list_orders(self, symbol=None, *, request_ids=None):
        if symbol and str(symbol).strip() != self.symbol:
            return []
        return [deepcopy(self.order)]

    def list_execution_fills(self, symbol, *, request_ids=None):
        return []

    def list_trade_facts(self, symbol, *, internal_order_ids=None):
        return []

    def list_position_entries(self, symbol):
        if symbol and str(symbol).strip() != self.symbol:
            return []
        return [deepcopy(self.entry)]

    def list_entry_slices(self, symbol):
        if symbol and str(symbol).strip() != self.symbol:
            return []
        return [deepcopy(self.slice)]

    def list_exit_allocations(self, *, entry_ids, trade_fact_ids=None):
        return []

    def list_pm_decisions(self, symbol):
        return []

    def list_xt_assets(self):
        return []

    def list_credit_asset_snapshots(self, *, limit=20_000):
        return []


def test_signal_type_registry_is_stable_and_serializable():
    payload = signal_type_registry_payload()
    assert set(payload) == {
        "buy_v_reverse",
        "buy_zs_huila",
        "macd_bullish_divergence",
        "sell_takeprofit",
        "sell_stoploss",
        "manual",
        "unknown",
    }
    reversal = signal_meta("buy_v_reverse")
    assert reversal["family"] == "reversal"
    assert reversal["marker_symbol"] == "triangle"
    assert signal_meta("no_such_type")["type"] == "unknown"


def test_resolve_signal_type_new_open_buy_is_reversal():
    request = {
        "source": "strategy",
        "strategy_context": {
            "guardian_buy_grid": {
                "path": "new_open",
                "initial_amount": 10000.0,
                "source_price": 10.0,
            }
        },
    }
    assert (
        resolve_signal_type(request=request, signal=None, side="buy") == "buy_v_reverse"
    )


def test_resolve_signal_type_manual_and_unknown():
    manual = {"source": "manual"}
    assert resolve_signal_type(request=manual, signal=None, side="sell") == "manual"
    assert resolve_signal_type(request={}, signal=None, side=None) == "unknown"


def test_cost_basis_replay_uses_entry_unit_cost_and_tracks_realized():
    repo = FakeBuySellRepository()
    requests_by_id = {str(item.get("request_id") or ""): item for item in repo.requests}
    result = replay_cost_basis(
        symbol=repo.symbol,
        canonical_trades=_canonical_trades_from_xt(repo),
        entries=repo.entries,
        slices=repo.slices,
        allocations=repo.allocations,
        requests_by_id=requests_by_id,
        initial_position_quantity=0,
        initial_position_source="test",
    )
    assert result["cost_basis_source"] == "entry_slice_allocation"
    assert result["fees_included"] is False
    assert result["data_quality"]["cost_basis"] == "full"
    series = result["cost_basis_series"]
    buy_points = [point for point in series if point["point_type"] == "fill"]
    assert buy_points[0]["position_quantity"] == 4000
    assert buy_points[0]["average_cost"] == 10.27
    last_point = series[-1]
    assert last_point["position_quantity"] == 6000
    assert last_point["average_cost"] == 10.27
    assert last_point["realized_pnl"] == 320.0
    assert result["realized_pnl"] == 320.0


def test_cost_basis_replay_selling_low_cost_slice_raises_remaining_average():
    repo = FakeLedgerSellRepository()
    requests_by_id = {str(item.get("request_id") or ""): item for item in repo.requests}
    result = replay_cost_basis(
        symbol=repo.symbol,
        canonical_trades=_canonical_trades_from_xt(repo),
        entries=repo.entries,
        slices=repo.slices,
        allocations=repo.allocations,
        requests_by_id=requests_by_id,
        initial_position_quantity=0,
        initial_position_source="test",
    )
    series = result["cost_basis_series"]
    final_average = series[-1]["average_cost"]
    assert final_average == 22.41
    assert result["realized_pnl"] == 3864.0


def test_cost_basis_replay_degrades_when_entries_are_flatten_snapshots():
    repo = FakeBuySellRepository()
    flatten_entries = deepcopy(repo.entries)
    for entry in flatten_entries:
        entry["entry_type"] = "position_snapshot_flatten"
        entry["source"] = "order_ledger_rebuild"
        entry["arrange_mode"] = "position_snapshot_flatten"
    requests_by_id = {str(item.get("request_id") or ""): item for item in repo.requests}
    result = replay_cost_basis(
        symbol=repo.symbol,
        canonical_trades=_canonical_trades_from_xt(repo),
        entries=flatten_entries,
        slices=repo.slices,
        allocations=repo.allocations,
        requests_by_id=requests_by_id,
        initial_position_quantity=0,
        initial_position_source="test",
    )
    assert result["cost_basis_source"] == "broker_snapshot_estimate"
    assert result["data_quality"]["cost_basis"] == "degraded"
    assert any(
        warning.get("code")
        in {
            "cost_basis_estimated",
            "ledger_incomplete_for_buys",
            "cost_basis_broker_snapshot",
        }
        for warning in result["data_quality"]["warnings"]
    )


def test_position_series_and_holding_cycles_cover_reopen():
    series = [
        {"time": "2026-04-29T10:15:03+08:00", "value": 10000, "point_type": "fill"},
        {"time": "2026-04-29T10:30:05+08:00", "value": 6000, "point_type": "fill"},
        {"time": "2026-05-06T09:31:00+08:00", "value": 0, "point_type": "fill"},
        {"time": "2026-05-07T09:30:02+08:00", "value": 5000, "point_type": "fill"},
    ]
    cost_series = [
        {"time": "2026-04-29T10:15:03+08:00", "average_cost": 10.27},
        {"time": "2026-04-29T10:30:05+08:00", "average_cost": 10.27},
        {"time": "2026-05-06T09:31:00+08:00", "average_cost": None},
        {"time": "2026-05-07T09:30:02+08:00", "average_cost": 10.5},
    ]
    cycles = build_holding_cycles(
        position_series=series,
        cost_basis_series=cost_series,
        realized_pnl=100.0,
        symbol="002262",
    )
    assert [cycle["cycle_id"] for cycle in cycles] == [
        "002262:cycle:1",
        "002262:cycle:2",
    ]
    assert cycles[0]["status"] == "closed"
    assert cycles[1]["status"] == "open"
    assert cycles[1]["inherited"] is False


def test_build_conditions_sell_with_historical_threshold_is_complete():
    review = {
        "time": "2026-04-29T10:14:00+08:00",
        "verdict": "PASS",
        "expected": {
            "quantity": 2300,
            "threshold_price": 22.41,
            "threshold_mode": "percent",
            "can_use_volume": 2300,
        },
        "actual": {"filled_quantity": 2300},
    }
    request = {
        "request_id": "sell_req",
        "trace_id": "trc_sell",
        "price": 22.41,
        "quantity": 2300,
    }
    payload = build_conditions(
        review=review,
        request=request,
        runtime_event={"trace_id": "trc_sell"},
        side="sell",
    )
    assert payload["data_quality"]["condition_snapshot_status"] == "complete"
    assert payload["data_quality"]["threshold_missing_count"] == 0
    threshold_condition = next(
        item
        for item in payload["conditions"]
        if item["condition_key"] == "signal_price_above_threshold"
    )
    assert threshold_condition["threshold_value"] == 22.41
    assert threshold_condition["passed"] is True
    assert payload["config_snapshot_hash"] is None


def test_build_conditions_missing_historical_threshold_keeps_null():
    review = {
        "time": "2026-04-29T10:14:00+08:00",
        "expected": {"quantity": None, "threshold_price": None},
        "actual": {"filled_quantity": 0},
    }
    request = {
        "request_id": "sell_req",
        "price": 22.41,
        "quantity": 2300,
    }
    payload = build_conditions(
        review=review,
        request=request,
        runtime_event=None,
        side="sell",
    )
    assert payload["data_quality"]["condition_snapshot_status"] in {
        "partial",
        "missing",
    }
    assert payload["data_quality"]["threshold_missing_count"] >= 1
    threshold_condition = next(
        item
        for item in payload["conditions"]
        if item["condition_key"] == "signal_price_above_threshold"
    )
    assert threshold_condition["threshold_value"] is None
    assert threshold_condition["source"] == "missing"
    assert any(
        warning.get("code") == "historical_threshold_missing"
        for warning in payload["data_quality"]["warnings"]
    )


def test_build_conditions_buy_grid_snapshot_hash_is_stable():
    request = {
        "request_id": "buy_req",
        "price": 10.25,
        "quantity": 10000,
        "strategy_context": {
            "guardian_buy_grid": {
                "path": "new_open",
                "initial_amount": 102700.0,
                "source_price": 10.27,
                "grid_level": "1",
            }
        },
    }
    first = build_conditions(
        review={
            "time": "2026-04-29T10:15:00+08:00",
            "expected": {"quantity": 10000},
            "actual": {"filled_quantity": 10000},
        },
        request=request,
        runtime_event=None,
        side="buy",
    )
    second = build_conditions(
        review={
            "time": "2026-04-29T10:15:00+08:00",
            "expected": {"quantity": 10000},
            "actual": {"filled_quantity": 10000},
        },
        request=request,
        runtime_event=None,
        side="buy",
    )
    assert first["config_snapshot_hash"] == second["config_snapshot_hash"]
    assert first["trigger_snapshot"]["guardian_buy_grid"]["grid_level"] == "1"
    assert first["data_quality"]["condition_snapshot_status"] == "complete"


def test_get_symbol_chart_contract_has_markers_fills_and_registry():
    service = PositionReviewService(
        repository=FakeBuySellRepository(),
        runtime_repository=None,
        name_resolver=_noop_name,
    )
    payload = service.get_symbol_chart("002262")
    assert payload["symbol"]["code"] == "002262"
    assert payload["range"]["include_unfilled"] is False
    assert payload["signal_type_registry"]["buy_v_reverse"]["family"] == "reversal"
    assert payload["cost_basis"]["fees_included"] is False
    assert payload["cost_basis"]["source"] == "entry_slice_allocation"
    assert payload["cost_basis"]["realized_pnl"] == 320.0

    buy_events = [
        event
        for event in payload["order_events"]
        if event["side"] == "buy" and event["event_type"] == "filled_order"
    ]
    assert len(buy_events) == 1
    buy = buy_events[0]
    assert buy["execution"]["fill_count"] == 3
    assert buy["execution"]["actual_quantity"] == 10000
    assert buy["execution"]["avg_filled_price"] == 10.269
    assert buy["execution"]["first_fill_time"] is not None
    assert buy["execution"]["last_fill_time"] is not None
    assert len(buy["execution"]["fills"]) == 3
    assert buy["marker"]["side"] == "buy"
    assert buy["marker"]["symbol"] == "triangle"
    assert buy["marker"]["fill_count"] == 3
    assert buy["marker"]["verdict_encoding"]["verdict"] == "PASS"
    assert buy["signal"]["type"] == "buy_v_reverse"
    assert buy["signal"]["family"] == "reversal"
    assert buy["position_impact"]["fees_included"] is False
    assert buy["position_impact"]["cost_basis_after"] == 10.27
    assert buy["conditions"]["condition_snapshot_status"] == "complete"


def test_get_symbol_chart_include_unfilled_filters_empty_orders():
    service = PositionReviewService(
        repository=FakeBuySellRepository(),
        runtime_repository=None,
        name_resolver=_noop_name,
    )
    with_unfilled = service.get_symbol_chart("002262", include_unfilled=True)
    without_unfilled = service.get_symbol_chart("002262", include_unfilled=False)
    assert len(with_unfilled["order_events"]) >= len(without_unfilled["order_events"])


def test_get_symbol_chart_unknown_symbol_raises():
    service = PositionReviewService(
        repository=FakeBuySellRepository(),
        runtime_repository=None,
        name_resolver=_noop_name,
    )
    try:
        service.get_symbol_chart("999999")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_build_portfolio_summary_kpis_and_basis():
    detail = {
        "symbol": {"code": "002262", "name": "恩华药业", "is_holding": True},
        "summary": {
            "buy_amount": 102690.0,
            "sell_amount": 41400.0,
            "review_counts": {"PASS": 2, "FAIL": 0},
        },
        "reviews": [
            {
                "request_id": "buy_req",
                "side": "buy",
                "time": "2026-04-29T10:15:00+08:00",
                "verdict": "PASS",
                "request": {"quantity": 10000, "price": 10.25},
            },
            {
                "request_id": "sell_req",
                "side": "sell",
                "time": "2026-04-29T10:30:00+08:00",
                "verdict": "PASS",
                "request": {"quantity": 4000, "price": 10.35},
            },
        ],
    }
    cost_replay = {
        "realized_pnl": 320.0,
        "cost_basis_source": "entry_slice_allocation",
        "data_quality": {"cost_basis": "full"},
        "cost_basis_series": [
            {
                "time": "2026-04-29T10:30:05+08:00",
                "position_quantity": 6000,
                "average_cost": 10.27,
                "realized_pnl": 320.0,
            }
        ],
    }
    position = {
        "stock_code": "002262.SZ",
        "volume": 6000,
        "avg_price": 10.27,
        "market_value": 62100.0,
        "last_price": 10.35,
    }
    summary = build_portfolio_summary(
        catalog_rows=["002262"],
        detail_by_symbol={"002262": detail},
        cost_by_symbol={"002262": cost_replay},
        position_by_symbol={"002262": position},
        xt_assets=[
            {
                "cash": 5000.9,
                "market_value": 62100.0,
                "total_asset": 67100.9,
                "updated_at": "2026-08-07T18:34:16+00:00",
            }
        ],
        generated_at="2026-08-08T00:00:00+00:00",
    )
    assert summary["kpis"]["market_value"] == 62100.0
    assert summary["kpis"]["remaining_cost"] == 61620.0
    assert summary["kpis"]["floating_pnl"] == 480.0
    assert summary["kpis"]["realized_pnl"] == 320.0
    assert summary["data_quality"]["equity_basis"] == "broker_total_asset"
    assert summary["verdict_counts"]["PASS"] == 2
    assert len(summary["monthly_turnover"]) == 1
    assert summary["monthly_turnover"][0]["buy"] == 102500.0


def test_build_portfolio_series_credit_rebuild_net_value_default_day():
    series = build_portfolio_series(
        xt_assets=[],
        credit_snapshots=[
            {
                "queried_at": "2026-07-21T12:17:46+00:00",
                "total_asset": 5196064.04,
                "market_value": 5191064.0,
                "total_debt": 1637725.17,
                "available_amount": 5000.04,
            },
            {
                "queried_at": "2026-07-21T12:17:47+00:00",
                "total_asset": 5196064.04,
                "market_value": 5191064.0,
                "total_debt": 1637725.17,
                "available_amount": 5000.04,
            },
            {
                "queried_at": "2026-07-21T13:00:00+00:00",
                "total_asset": 5200000.0,
                "market_value": 5195000.0,
                "total_debt": 1637725.17,
                "available_amount": 5000.04,
            },
        ],
        trade_events=[
            {
                "time": "2026-07-21T13:00:00+00:00",
                "symbol": "002262",
                "name": "恩华药业",
                "side": "buy",
                "quantity": 4000,
                "price": 10.26,
                "amount": 41040.0,
                "request_id": "buy_req",
            },
            {
                "time": "2026-07-22T02:00:00+00:00",
                "symbol": "512000",
                "name": "券商ETF",
                "side": "sell",
                "quantity": 1000,
                "price": 0.57,
                "amount": 570.0,
                "request_id": "sell_req",
            },
        ],
        generated_at="2026-08-08T00:00:00+00:00",
    )
    assert series["equity_basis"] == "credit_snapshot_reconstructed"
    assert "净资产" in series["label"]
    assert series["period"] == "day"
    assert series["data_quality"]["interpolated"] is False
    assert series["data_quality"]["net_value_formula"] == (
        "net_value = total_asset - total_debt"
    )
    # 三条分钟快照同属北京 2026-07-21，聚合为一个日点（保留末笔）。
    assert len(series["series"]) == 1
    point = series["series"][0]
    assert point["period_key"] == "2026-07-21"
    assert point["total_asset"] == 5200000.0
    assert point["net_value"] == round(5200000.0 - 1637725.17, 2)
    assert point["estimated_equity"] == point["net_value"]
    assert point["trade_count"] == 1
    assert point["trades"][0]["symbol"] == "002262"


def test_build_portfolio_series_period_week_and_month_buckets():
    snapshots = [
        {"queried_at": "2026-07-20T03:00:00+00:00", "total_asset": 1000.0},
        {"queried_at": "2026-07-21T03:00:00+00:00", "total_asset": 1100.0},
        {"queried_at": "2026-07-22T03:00:00+00:00", "total_asset": 1200.0},
        {"queried_at": "2026-08-01T03:00:00+00:00", "total_asset": 1300.0},
    ]
    for item in snapshots:
        item.setdefault("total_debt", 0.0)
        item.setdefault("market_value", 0.0)
        item.setdefault("available_amount", 0.0)
    month = build_portfolio_series(
        xt_assets=[],
        credit_snapshots=snapshots,
        period="month",
        generated_at="2026-08-08T00:00:00+00:00",
    )
    assert [point["period_key"] for point in month["series"]] == [
        "2026-07",
        "2026-08",
    ]
    assert month["series"][0]["total_asset"] == 1200.0
    week = build_portfolio_series(
        xt_assets=[],
        credit_snapshots=snapshots,
        period="week",
        generated_at="2026-08-08T00:00:00+00:00",
    )
    keys = [point["period_key"] for point in week["series"]]
    assert keys == ["2026-07-20", "2026-07-27"]
    assert week["series"][0]["total_asset"] == 1200.0
    day = build_portfolio_series(
        xt_assets=[],
        credit_snapshots=snapshots,
        period="day",
        generated_at="2026-08-08T00:00:00+00:00",
    )
    assert len(day["series"]) == 4


def test_build_portfolio_series_rejects_invalid_period():
    try:
        build_portfolio_series(
            xt_assets=[],
            credit_snapshots=[],
            period="hour",
            generated_at="2026-08-08T00:00:00+00:00",
        )
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_build_portfolio_contributions_sorts_by_total_pnl():
    base = {
        "symbol": {"code": "", "name": ""},
        "summary": {"review_counts": {"PASS": 1, "FAIL": 0}},
    }
    detail_by_symbol = {
        "002262": {**deepcopy(base), "symbol": {"code": "002262", "name": "A"}},
        "512000": {**deepcopy(base), "symbol": {"code": "512000", "name": "B"}},
    }
    cost_by_symbol = {
        "002262": {
            "realized_pnl": -500.0,
            "cost_basis_source": "estimated_moving_average",
            "cost_basis_series": [],
            "data_quality": {},
        },
        "512000": {
            "realized_pnl": 300.0,
            "cost_basis_source": "estimated_moving_average",
            "cost_basis_series": [],
            "data_quality": {},
        },
    }
    position_by_symbol = {
        "002262": {"volume": 6000, "avg_price": 10.27, "market_value": 62100.0},
        "512000": {"volume": 0, "avg_price": 0.0, "market_value": 0.0},
    }
    payload = build_portfolio_contributions(
        detail_by_symbol=detail_by_symbol,
        cost_by_symbol=cost_by_symbol,
        position_by_symbol=position_by_symbol,
        top_n=10,
    )
    assert payload["top"][0]["symbol"] == "512000"
    assert payload["top"][0]["total_pnl"] == 300.0
    assert payload["top"][1]["symbol"] == "002262"


def test_position_review_refactor_routes(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(position_review_bp)
    client = app.test_client()

    class FakeService:
        def get_portfolio_summary(self, *, refresh=False):
            return {"kpis": {"total_asset": 1.0}, "data_quality": {}}

        def get_portfolio_series(self, *, refresh=False, period="day"):
            return {
                "equity_basis": "estimated",
                "period": period,
                "series": [],
            }

        def get_portfolio_contributions(self, *, refresh=False, top_n=10):
            return {"top": [], "total": 0}

        def get_symbol_chart(
            self,
            symbol,
            *,
            period=None,
            account_partition=None,
            include_unfilled=False,
            refresh=False,
        ):
            return {"symbol": {"code": symbol}, "order_events": []}

        def get_event_conditions(self, event_id, *, refresh=False):
            if event_id == "missing":
                raise ValueError("event not found")
            return {"event_id": event_id, "conditions": []}

    monkeypatch.setattr(
        "freshquant.rear.position_review.routes._get_position_review_service",
        lambda: FakeService(),
    )
    assert client.get("/api/position-review/portfolio/summary").status_code == 200
    assert client.get("/api/position-review/portfolio/series").status_code == 200
    series_period = client.get("/api/position-review/portfolio/series?period=week")
    assert series_period.status_code == 200
    assert series_period.get_json()["period"] == "week"
    assert (
        client.get("/api/position-review/portfolio/contributions?top_n=5").status_code
        == 200
    )
    chart = client.get("/api/position-review/symbols/002262/chart")
    assert chart.status_code == 200
    assert chart.get_json()["symbol"]["code"] == "002262"
    conditions = client.get("/api/position-review/events/evt_1/conditions")
    assert conditions.status_code == 200
    assert conditions.get_json()["event_id"] == "evt_1"
    missing = client.get("/api/position-review/events/missing/conditions")
    assert missing.status_code == 404
    invalid = client.get("/api/position-review/portfolio/contributions?top_n=0")
    assert invalid.status_code == 400


def test_catalog_appends_current_holdings_without_execution_history():
    repo = FakeBuySellRepository()
    # 增加两只没有成交记录的当前持仓（ETF 风格）
    repo.xt_positions = [
        {
            "stock_code": "002262.SZ",
            "volume": 6000,
            "avg_price": 10.27,
            "market_value": 62100.0,
            "last_price": 10.35,
        },
        {
            "stock_code": "512000.SH",
            "volume": 1468900,
            "avg_price": 0.568875,
            "market_value": 769703.6,
            "last_price": 0.5238,
        },
        {
            "stock_code": "513180.SH",
            "volume": 756700,
            "avg_price": 0.6131,
            "market_value": 463857.1,
            "last_price": 0.613,
        },
    ]
    service = PositionReviewService(
        repository=repo,
        runtime_repository=None,
        name_resolver=_noop_name,
    )
    rows, detail_by_symbol = service._build_symbol_rows()
    symbols = {row["symbol"] for row in rows}
    assert "002262" in symbols
    assert "512000" in symbols
    assert "513180" in symbols
    holding_only = [row for row in rows if row.get("no_execution_history")]
    assert sorted(row["symbol"] for row in holding_only) == ["512000", "513180"]
    assert all(row["is_holding"] for row in holding_only)
    assert all(row["verdict"] is None for row in holding_only)
    assert detail_by_symbol["512000"]["data_quality"]["no_execution_history"] is True


def test_portfolio_contributions_include_holding_only_symbols_with_broker_estimate():
    repo = FakeBuySellRepository()
    repo.xt_positions = [
        {
            "stock_code": "002262.SZ",
            "volume": 6000,
            "avg_price": 10.27,
            "market_value": 62100.0,
            "last_price": 10.35,
        },
        {
            "stock_code": "512000.SH",
            "volume": 1468900,
            "avg_price": 0.568875,
            "market_value": 769703.6,
            "last_price": 0.5238,
        },
    ]
    service = PositionReviewService(
        repository=repo,
        runtime_repository=None,
        name_resolver=_noop_name,
    )
    contributions = service.get_portfolio_contributions(refresh=True, top_n=10)
    symbols = {row["symbol"] for row in contributions["top"]}
    assert "002262" in symbols
    assert "512000" in symbols
    holding_row = next(row for row in contributions["top"] if row["symbol"] == "512000")
    assert holding_row["is_holding"] is True
    assert holding_row["cost_basis_source"] == "broker_snapshot_estimate"
    assert holding_row["quantity"] == 1468900
    assert holding_row["market_value"] == 769703.6


def test_get_symbol_detail_and_chart_work_for_holding_only_symbol():
    repo = FakeBuySellRepository()
    # 增加一只没有成交记录的当前持仓（对应 600917 场景）。
    repo.xt_positions = [
        {
            "stock_code": "600917.SH",
            "volume": 20000,
            "avg_price": 5.527529,
            "market_value": 96400.0,
            "last_price": 0.0,
        },
    ]
    service = PositionReviewService(
        repository=repo,
        runtime_repository=None,
        name_resolver=_noop_name,
    )
    detail = service.get_symbol_detail("600917")
    assert detail["symbol"]["code"] == "600917"
    assert detail["symbol"]["is_holding"] is True
    assert detail["data_quality"]["no_execution_history"] is True
    assert detail["executions"] == []

    chart = service.get_symbol_chart("600917")
    assert chart["symbol"]["code"] == "600917"
    assert chart["order_events"] == []
    assert chart["range"]["period"] is None
    assert chart["cost_basis"]["source"] == "broker_snapshot_estimate"
    assert chart["cost_basis"]["fees_included"] is False
    assert len(chart["cost_basis_series"]) == 1
    point = chart["cost_basis_series"][0]
    assert point["average_cost"] == 5.527529
    assert point["position_quantity"] == 20000
    assert point["point_type"] == "broker_snapshot_estimate"


def test_get_symbol_detail_unknown_symbol_still_raises():
    repo = FakeBuySellRepository()
    service = PositionReviewService(
        repository=repo,
        runtime_repository=None,
        name_resolver=_noop_name,
    )
    try:
        service.get_symbol_detail("999999")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_flatten_rebuild_symbol_chart_shows_rebuilt_open_order_and_cost_point():
    """账本重建对账后：图表默认可见重建买入事件，成本曲线有重建成本点。"""

    service = PositionReviewService(
        repository=FakeFlattenRebuildRepository(),
        runtime_repository=None,
        name_resolver=_noop_name,
    )
    chart = service.get_symbol_chart("600917")
    assert chart["symbol"]["code"] == "600917"
    assert chart["cost_basis"]["source"] == "broker_snapshot_estimate"
    assert chart["cost_basis"]["fees_included"] is False

    rebuilt_events = [
        event
        for event in chart["order_events"]
        if event["event_type"] == "rebuilt_open_order"
    ]
    assert len(rebuilt_events) == 1
    rebuilt = rebuilt_events[0]
    assert rebuilt["rebuilt"] is True
    assert rebuilt["rebuild_source"] == "position_snapshot_flatten"
    assert rebuilt["side"] == "buy"
    assert rebuilt["order"]["status"] == "FILLED"

    rebuilt_points = [
        point
        for point in chart["cost_basis_series"]
        if point["point_type"] == "rebuilt_open"
    ]
    assert len(rebuilt_points) == 1
    point = rebuilt_points[0]
    assert point["average_cost"] == 5.527529
    assert point["position_quantity"] == 20000
    assert point["cost_basis_source"] == "broker_snapshot_estimate"
    assert point["fees_included"] is False


def test_flatten_rebuild_request_review_is_not_applicable():
    """重建买入请求无策略上下文，复盘结论为 NOT_APPLICABLE，不污染 PASS/FAIL。"""

    service = PositionReviewService(
        repository=FakeFlattenRebuildRepository(),
        runtime_repository=None,
        name_resolver=_noop_name,
    )
    detail = service.get_symbol_detail("600917")
    reviews = detail.get("reviews") or []
    assert len(reviews) == 1
    review = reviews[0]
    assert review["request_id"] == "req_rebuilt_entry_flatten_600917"
    assert review["verdict"] == "NOT_APPLICABLE"
    assert "non_guardian_request" in review["reason_codes"]

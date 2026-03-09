# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any

from freshquant.carnation.param import queryParam
from freshquant.db import DBQuantAxis
from freshquant.market_data.xtdata.pools import (
    load_monitor_codes,
    normalize_xtdata_mode,
)
from freshquant.trading.dt import query_current_trade_date, query_prev_trade_date
from freshquant.util.code import normalize_to_base_code


def _normalize_date_str(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text:
        return None
    return text[:10]


def _to_xt_code(code_prefixed: str) -> str:
    s = (code_prefixed or "").lower().strip()
    if len(s) >= 8 and s[:2] in {"sh", "sz", "bj"} and s[2:8].isdigit():
        return f"{s[2:8]}.{s[:2].upper()}"
    return s


def _is_index_like_code(code_prefixed: str) -> bool:
    base_code = normalize_to_base_code(code_prefixed)
    return base_code.startswith(("15", "16", "51", "52", "53", "56", "58", "159"))


def _default_code_loader() -> list[str]:
    mode = normalize_xtdata_mode(queryParam("monitor.xtdata.mode", None))
    max_symbols = int(queryParam("monitor.xtdata.max_symbols", 50) or 50)
    return list(load_monitor_codes(mode=mode, max_symbols=max_symbols) or [])


class AdjRefreshRepository:
    def get_base_anchor(
        self, kind: str, code: str, base_anchor_date: str
    ) -> dict | None:
        coll = "stock_adj" if kind == "stock" else "etf_adj"
        return DBQuantAxis[coll].find_one(
            {
                "code": normalize_to_base_code(code),
                "date": {"$lte": base_anchor_date},
            },
            sort=[("date", -1)],
            projection={"_id": 0, "date": 1, "adj": 1},
        )

    def upsert_intraday_override(
        self, kind: str, document: dict[str, Any]
    ) -> dict[str, Any]:
        coll = "stock_adj_intraday" if kind == "stock" else "etf_adj_intraday"
        DBQuantAxis[coll].update_one(
            {
                "code": document["code"],
                "trade_date": document["trade_date"],
            },
            {"$set": document},
            upsert=True,
        )
        return dict(document)


class XtDataAdjRefreshClient:
    def __init__(self, xtdata_module=None, port: int | None = None):
        if xtdata_module is None:
            from xtquant import xtdata as xtdata_module  # type: ignore

        self.xtdata = xtdata_module
        self.port = int(port or os.environ.get("XTQUANT_PORT", "58610"))
        self._connected = False

    def _ensure_connected(self) -> None:
        if self._connected:
            return
        self.xtdata.connect(port=self.port)
        self._connected = True

    def _load_close(
        self, code: str, trade_date: str, *, dividend_type: str
    ) -> float | None:
        self._ensure_connected()
        xt_code = _to_xt_code(code)
        day_str = trade_date.replace("-", "")
        try:
            self.xtdata.download_history_data(xt_code, "1d", day_str, day_str)
        except Exception:
            pass

        data = self.xtdata.get_market_data(
            field_list=["close"],
            stock_list=[xt_code],
            period="1d",
            start_time=day_str,
            end_time=day_str,
            dividend_type=dividend_type,
            fill_data=False,
        )
        close_df = (data or {}).get("close")
        if close_df is None or getattr(close_df, "empty", True):
            return None

        row_key = None
        for candidate in (
            xt_code,
            xt_code.upper(),
            xt_code.lower(),
            code,
            code.upper(),
            code.lower(),
            normalize_to_base_code(code),
        ):
            if candidate in close_df.index:
                row_key = candidate
                break
        if row_key is None and len(close_df.index) == 1:
            row_key = close_df.index[0]
        if row_key is None:
            return None

        series = close_df.loc[row_key]
        if getattr(series, "empty", True):
            return None
        try:
            return float(series.iloc[-1])
        except Exception:
            return None

    def get_daily_close_pair(
        self, code: str, trade_date: str
    ) -> dict[str, float] | None:
        raw_close = self._load_close(code, trade_date, dividend_type="none")
        front_close = self._load_close(code, trade_date, dividend_type="front")
        if raw_close is None or front_close is None:
            return None
        return {"raw_close": raw_close, "front_close": front_close}


class AdjRefreshService:
    def __init__(
        self,
        repository=None,
        market_client=None,
        code_loader=None,
        trade_date_provider=None,
        prev_trade_date_provider=None,
        now_provider=None,
    ):
        self.repository = repository or AdjRefreshRepository()
        self.market_client = market_client or XtDataAdjRefreshClient()
        self.code_loader = code_loader or _default_code_loader
        self.trade_date_provider = trade_date_provider or query_current_trade_date
        self.prev_trade_date_provider = (
            prev_trade_date_provider or query_prev_trade_date
        )
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def sync_once(self) -> dict[str, Any]:
        trade_date = _normalize_date_str(self.trade_date_provider())
        base_anchor_date = _normalize_date_str(self.prev_trade_date_provider())
        if not trade_date or not base_anchor_date:
            return {
                "count": 0,
                "stock_count": 0,
                "etf_count": 0,
                "trade_date": trade_date,
                "base_anchor_date": base_anchor_date,
                "updated_at": self.now_provider().isoformat(),
            }

        updated_at = self.now_provider().isoformat()
        result = {
            "count": 0,
            "stock_count": 0,
            "etf_count": 0,
            "trade_date": trade_date,
            "base_anchor_date": base_anchor_date,
            "updated_at": updated_at,
        }

        for code in list(self.code_loader() or []):
            kind = "etf" if _is_index_like_code(code) else "stock"
            anchor_doc = self.repository.get_base_anchor(kind, code, base_anchor_date)
            if not anchor_doc or anchor_doc.get("adj") in (None, 0):
                continue
            effective_anchor_date = str(anchor_doc.get("date") or base_anchor_date)

            close_pair = self.market_client.get_daily_close_pair(
                code, effective_anchor_date
            )
            if not close_pair:
                continue

            raw_close = float(close_pair.get("raw_close") or 0.0)
            front_close = float(close_pair.get("front_close") or 0.0)
            base_adj = float(anchor_doc.get("adj") or 0.0)
            if raw_close <= 0 or front_close <= 0 or base_adj <= 0:
                continue

            target_adj = front_close / raw_close
            anchor_scale = target_adj / base_adj
            document = {
                "code": normalize_to_base_code(code),
                "trade_date": trade_date,
                "base_anchor_date": effective_anchor_date,
                "anchor_scale": float(anchor_scale),
                "source": "xtdata_front_raw",
                "updated_at": updated_at,
            }
            self.repository.upsert_intraday_override(kind, document)
            result["count"] += 1
            result[f"{kind}_count"] += 1

        return result


def refresh_adj_overrides_once(
    *,
    repository=None,
    market_client=None,
    code_loader=None,
    trade_date_provider=None,
    prev_trade_date_provider=None,
    now_provider=None,
) -> dict[str, Any]:
    service = AdjRefreshService(
        repository=repository,
        market_client=market_client,
        code_loader=code_loader,
        trade_date_provider=trade_date_provider,
        prev_trade_date_provider=prev_trade_date_provider,
        now_provider=now_provider,
    )
    return service.sync_once()

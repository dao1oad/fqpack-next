from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from typing import Any

from freshquant.db import DBQuantAxis

QFQ_DATA_VERSION = "qfq-daily-v1"


class AdjustmentCoverageError(ValueError):
    def __init__(
        self,
        *,
        asset_type: str,
        symbol: str,
        missing_dates: list[str],
        invalid_dates: list[str],
    ) -> None:
        self.asset_type = asset_type
        self.symbol = symbol
        self.data_version = QFQ_DATA_VERSION
        self.missing_dates = list(missing_dates)
        self.invalid_dates = list(invalid_dates)
        details = []
        if missing_dates:
            details.append(self._date_summary("missing_dates", missing_dates))
        if invalid_dates:
            details.append(self._date_summary("invalid_dates", invalid_dates))
        super().__init__(
            f"{QFQ_DATA_VERSION} adjustment coverage invalid for "
            f"{asset_type}/{symbol}: {'; '.join(details)}"
        )

    def _date_summary(self, label: str, values: list[str]) -> str:
        preview = ",".join(values[:5])
        suffix = f",...({len(values)} total)" if len(values) > 5 else ""
        return f"{label}={preview}{suffix}"


class MongoDailyMarketDataProvider:
    data_version = QFQ_DATA_VERSION

    def __init__(self, database=None) -> None:
        self.database = database if database is not None else DBQuantAxis

    def list_instruments(
        self, asset_type: str, _trade_date: str
    ) -> list[dict[str, str]]:
        if asset_type == "stock":
            collection = self.database["stock_list"]
            day_collection = self.database["stock_day"]
        elif asset_type == "etf":
            collection = self.database["etf_list"]
            day_collection = self.database["index_day"]
        else:
            raise ValueError(f"unsupported asset_type: {asset_type}")
        current_codes = {
            str(code).strip()
            for code in day_collection.distinct("code", {"date": _trade_date})
            if str(code).strip()
        }
        rows = []
        seen = set()
        for item in collection.find({}, {"_id": 0, "code": 1, "name": 1}):
            symbol = str(item.get("code") or "").strip()
            name = str(item.get("name") or symbol).strip()
            if (
                symbol not in current_codes
                or not self._eligible(asset_type, symbol, name)
                or symbol in seen
            ):
                continue
            seen.add(symbol)
            rows.append({"symbol": symbol, "name": name})
        rows.sort(key=lambda item: item["symbol"])
        return rows

    def get_latest_trade_date(self, asset_type: str, symbol: str) -> str:
        if asset_type == "stock":
            collection = self.database["stock_day"]
        elif asset_type == "etf":
            collection = self.database["index_day"]
        else:
            raise ValueError(f"unsupported asset_type: {asset_type}")
        row = collection.find_one(
            {"code": str(symbol or "").strip()},
            {"_id": 0, "date": 1},
            sort=[("date", -1)],
        )
        return self._date_text((row or {}).get("date"))

    def get_daily_bars(
        self,
        asset_type: str,
        symbol: str,
        trade_date: str,
        bar_count: int,
    ) -> list[dict[str, Any]]:
        if asset_type == "stock":
            bar_collection = self.database["stock_day"]
            adj_collection = self.database["stock_adj"]
        elif asset_type == "etf":
            bar_collection = self.database["index_day"]
            adj_collection = self.database["etf_adj"]
        else:
            raise ValueError(f"unsupported asset_type: {asset_type}")
        cursor = (
            bar_collection.find(
                {"code": symbol, "date": {"$lte": trade_date}},
                {
                    "_id": 0,
                    "date": 1,
                    "open": 1,
                    "high": 1,
                    "low": 1,
                    "close": 1,
                    "vol": 1,
                    "volume": 1,
                },
            )
            .sort("date", -1)
            .limit(int(bar_count))
        )
        rows = list(cursor)
        rows.reverse()
        if not rows:
            return []
        first_date = self._date_text(rows[0].get("date"))
        bar_dates = [self._date_text(item.get("date")) for item in rows]
        bar_date_set = set(bar_dates)
        adjustments: dict[str, float] = {}
        invalid_dates = set()
        for item in adj_collection.find(
            {
                "code": symbol,
                "date": {"$gte": first_date, "$lte": trade_date},
            },
            {"_id": 0, "date": 1, "adj": 1, "qfq_adj": 1},
        ):
            date_text = self._date_text(item.get("date"))
            raw_factor = item.get("adj")
            if raw_factor is None:
                raw_factor = item.get("qfq_adj")
            try:
                factor = float(raw_factor)
            except (TypeError, ValueError):
                if date_text in bar_date_set:
                    invalid_dates.add(date_text)
                continue
            if not date_text or not isfinite(factor) or factor <= 0:
                if date_text in bar_date_set:
                    invalid_dates.add(date_text)
                continue
            adjustments[date_text] = factor
        missing_dates = sorted(set(bar_dates) - set(adjustments) - invalid_dates)
        if missing_dates or invalid_dates:
            raise AdjustmentCoverageError(
                asset_type=asset_type,
                symbol=symbol,
                missing_dates=missing_dates,
                invalid_dates=sorted(invalid_dates),
            )
        bars = []
        for item in rows:
            date_text = self._date_text(item.get("date"))
            factor = adjustments[date_text]
            bars.append(
                {
                    "date": date_text,
                    "open": float(item["open"]) * factor,
                    "high": float(item["high"]) * factor,
                    "low": float(item["low"]) * factor,
                    "close": float(item["close"]) * factor,
                    "volume": float(item.get("volume", item.get("vol", 0.0)) or 0.0),
                    "adjustment_factor": factor,
                    "data_version": QFQ_DATA_VERSION,
                }
            )
        return bars

    def _eligible(self, asset_type: str, symbol: str, name: str) -> bool:
        if len(symbol) != 6 or not symbol.isdigit():
            return False
        if asset_type == "stock":
            if "ST" in name.upper():
                return False
            if symbol.startswith(("4", "8", "92")):
                return False
        return True

    def _date_text(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value or "")[:10]

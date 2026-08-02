from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from math import isfinite
from typing import Any, NoReturn

import pandas as pd

from freshquant.db import DBQuantAxis

QFQ_DATA_VERSION = "qfq-daily-v1"


class MongoDailyMarketDataProvider:
    data_version = QFQ_DATA_VERSION

    _QFQ_METADATA_FIELDS = (
        "scope",
        "active_slot",
        "collection",
        "snapshot_id",
        "factor_asof",
        "published_at",
        "effective_version",
        "override_version",
    )

    def __init__(self, database=None, *, expected_snapshot_metadata=None) -> None:
        self.database = database if database is not None else DBQuantAxis
        self._expected_snapshot_metadata = expected_snapshot_metadata
        self._last_qfq_metadata: dict[str, dict[str, Any]] = {}

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

    def probe_qfq_instrument(
        self,
        asset_type: str,
        symbol: str,
        trade_date: str,
        *,
        bar_count: int = 1,
        expected_snapshot_metadata=None,
    ) -> dict[str, Any]:
        """Prove at most ``bar_count`` BFQ bars against one frozen snapshot."""
        bar_count = int(bar_count)
        if bar_count < 1:
            raise ValueError("bar_count must be positive")
        bars = self.get_daily_bars(
            asset_type,
            symbol,
            trade_date,
            bar_count,
            expected_snapshot_metadata=expected_snapshot_metadata,
        )
        trade_date = self._date_text(trade_date)
        if not bars or bars[-1].get("date") != trade_date:
            self._raise_qfq_not_ready(
                "strict QFQ reader did not return the target-day bar",
                scope=asset_type,
                code=str(symbol or "").strip(),
            )
        metadata = self.last_read_metadata(asset_type)
        if metadata is None:
            self._raise_qfq_not_ready(
                "strict QFQ reader returned no snapshot metadata",
                scope=asset_type,
                code=str(symbol or "").strip(),
            )
        return metadata

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
        *,
        expected_snapshot_metadata=None,
    ) -> list[dict[str, Any]]:
        if asset_type == "stock":
            bar_collection = self.database["stock_day"]
        elif asset_type == "etf":
            bar_collection = self.database["index_day"]
        else:
            raise ValueError(f"unsupported asset_type: {asset_type}")
        symbol = str(symbol or "").strip()
        trade_date = self._date_text(trade_date)
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

        from freshquant.data.qfq_reader import apply_qfq_to_bars

        raw_bars = pd.DataFrame(
            [
                {
                    "date": self._date_text(item.get("date")),
                    "open": item.get("open"),
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "close": item.get("close"),
                    "volume": item.get("volume", item.get("vol", 0.0)),
                }
                for item in rows
            ]
        )
        adjusted_bars, metadata = apply_qfq_to_bars(
            raw_bars,
            scope=asset_type,
            code=symbol,
            db=self.database,
            date_col="date",
            ohlc_cols=("open", "high", "low", "close"),
        )
        metadata_facts = self._metadata_facts(metadata)
        expected = self._expected_metadata(
            asset_type,
            expected_snapshot_metadata,
        )
        self._validate_qfq_metadata(
            asset_type=asset_type,
            symbol=symbol,
            trade_date=trade_date,
            actual=metadata_facts,
            expected=expected,
        )
        bars = []
        for raw_item, item in zip(
            raw_bars.to_dict("records"),
            adjusted_bars.to_dict("records"),
            strict=True,
        ):
            date_text = self._date_text(item.get("date"))
            try:
                factor = float(item["close"]) / float(raw_item["close"])
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                factor = float("nan")
            if not isfinite(factor) or factor <= 0:
                self._raise_qfq_not_ready(
                    "strict QFQ reader returned an invalid adjustment factor",
                    scope=asset_type,
                    code=symbol,
                )
            bars.append(
                {
                    "date": date_text,
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                    "volume": float(item.get("volume", 0.0) or 0.0),
                    "adjustment_factor": factor,
                    "data_version": QFQ_DATA_VERSION,
                    "qfq_active_slot": metadata_facts["active_slot"],
                    "qfq_snapshot_id": metadata_facts["snapshot_id"],
                    "qfq_factor_asof": metadata_facts["factor_asof"],
                    "qfq_published_at": metadata_facts["published_at"],
                    "qfq_effective_version": metadata_facts["effective_version"],
                    "qfq_collection": metadata_facts["collection"],
                }
            )
        self._last_qfq_metadata[asset_type] = dict(metadata_facts)
        return bars

    def last_read_metadata(self, scope: str) -> dict[str, Any] | None:
        metadata = self._last_qfq_metadata.get(str(scope or "").strip().lower())
        return dict(metadata) if metadata is not None else None

    def _expected_metadata(self, scope: str, override) -> dict[str, Any] | None:
        value = override if override is not None else self._expected_snapshot_metadata
        if value is None:
            return None
        if isinstance(value, Mapping) and any(
            candidate in value for candidate in ("stock", "etf")
        ):
            if value.get(scope) is None:
                raise ValueError(f"expected QFQ snapshot pair is missing {scope}")
            value = value[scope]
        facts = self._metadata_facts(value)
        declared_scope = str(facts.get("scope") or scope).strip().lower()
        if declared_scope != scope:
            raise ValueError(
                f"expected QFQ snapshot scope mismatch: {declared_scope or '<empty>'}"
            )
        facts["scope"] = scope
        for field in ("snapshot_id", "factor_asof"):
            if not str(facts.get(field) or "").strip():
                raise ValueError(f"expected QFQ snapshot metadata requires {field}")
        return facts

    def _metadata_facts(self, metadata) -> dict[str, Any]:
        if is_dataclass(metadata) and not isinstance(metadata, type):
            raw = asdict(metadata)
        elif isinstance(metadata, Mapping):
            raw = dict(metadata)
        else:
            raw = vars(metadata)
        facts = {}
        for field in self._QFQ_METADATA_FIELDS:
            if field not in raw:
                continue
            value = raw.get(field)
            if field == "override_version":
                facts[field] = str(value).strip() if value not in (None, "") else None
            else:
                facts[field] = str(value or "").strip()
        return facts

    def _validate_qfq_metadata(
        self,
        *,
        asset_type: str,
        symbol: str,
        trade_date: str,
        actual: dict[str, Any],
        expected: dict[str, Any] | None,
    ) -> None:
        for field in (
            "scope",
            "active_slot",
            "collection",
            "snapshot_id",
            "factor_asof",
            "published_at",
            "effective_version",
        ):
            if not actual.get(field):
                self._raise_qfq_not_ready(
                    f"strict QFQ reader returned empty {field}",
                    scope=asset_type,
                    code=symbol,
                )
        if actual["scope"] != asset_type:
            self._raise_qfq_not_ready(
                f"strict QFQ reader scope mismatch: actual={actual['scope']}",
                scope=asset_type,
                code=symbol,
            )
        if trade_date <= actual["factor_asof"] and actual.get("override_version"):
            self._raise_qfq_not_ready(
                "strict QFQ reader returned an override for a snapshot-covered date",
                scope=asset_type,
                code=symbol,
            )
        if expected is None:
            return
        compared_fields = ["scope", "snapshot_id", "factor_asof"]
        compared_fields.extend(
            field
            for field in (
                "active_slot",
                "collection",
                "published_at",
                "effective_version",
                "override_version",
            )
            if field in expected
        )
        mismatches = [
            field
            for field in compared_fields
            if actual.get(field) != expected.get(field)
        ]
        if mismatches:
            details = ", ".join(
                f"{field}=expected:{expected.get(field)!r}/actual:{actual.get(field)!r}"
                for field in mismatches
            )
            self._raise_qfq_not_ready(
                f"frozen QFQ snapshot metadata mismatch: {details}",
                scope=asset_type,
                code=symbol,
            )

    def _raise_qfq_not_ready(self, message: str, *, scope: str, code: str) -> NoReturn:
        from freshquant.data.qfq_reader import QFQDataNotReadyError

        raise QFQDataNotReadyError(message, scope=scope, code=code)

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

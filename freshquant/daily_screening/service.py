from __future__ import annotations

import asyncio
import json
import threading
from datetime import date, datetime
from typing import Any

import pendulum

from freshquant.daily_screening.session_store import DailyScreeningSessionStore
from freshquant.db import DBfreshquant


def _save_pre_pool(**kwargs) -> None:
    from freshquant.signal.a_stock_common import save_a_stock_pre_pools

    expire_at_days = int(kwargs.pop("expire_at_days", 89) or 89)
    save_a_stock_pre_pools(
        expire_at=pendulum.now().add(days=expire_at_days),
        **kwargs,
    )


def _save_stock_pool(**kwargs) -> None:
    from freshquant.signal.a_stock_common import save_a_stock_pools

    expire_days = int(kwargs.pop("expire_days", 30) or 30)
    save_a_stock_pools(
        expire_at=pendulum.now().add(days=expire_days),
        **kwargs,
    )


def _save_database_outputs(results: list[Any], config: dict) -> None:
    if not results:
        return
    save_signal = bool(config.get("save_signal"))
    save_pools = bool(config.get("save_pools"))
    if not save_signal and not save_pools:
        return
    from freshquant.screening.writers import DatabaseOutput

    DatabaseOutput.save_all(
        results,
        save_signal=save_signal,
        save_pools=save_pools,
        save_pre_pools=False,
        pool_expire_days=int(config.get("pool_expire_days") or 10),
    )


class DailyScreeningService:
    def __init__(
        self,
        *,
        session_store: DailyScreeningSessionStore | None = None,
        db=None,
    ) -> None:
        self.session_store = session_store or DailyScreeningSessionStore()
        self.db = db or DBfreshquant

    def get_schema(self) -> dict:
        categories = sorted(
            {str(doc.get("category") or "").strip() for doc in self._find_pre_pools({})}
            - {""}
        )
        remarks = sorted(
            {str(doc.get("remark") or "").strip() for doc in self._find_pre_pools({})}
            - {""}
        )
        return {
            "models": [self._clxs_schema(), self._chanlun_schema()],
            "options": {
                "pre_pool_categories": categories,
                "pre_pool_remarks": remarks,
            },
        }

    def start_run(self, payload: dict | None, *, run_async: bool = True) -> dict:
        config = self._normalize_start_payload(payload or {})
        run_id = self.session_store.create_run(model=config["model"], params=config)
        if run_async:
            thread = threading.Thread(
                target=self._execute_run,
                args=(run_id, config),
                daemon=True,
                name=f"daily-screening-{run_id}",
            )
            thread.start()
        else:
            self._execute_run(run_id, config)
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict:
        return self.session_store.get_run(run_id)

    def get_schema_options(self) -> dict:
        return self.get_schema()["options"]

    def list_pre_pools(
        self,
        *,
        remark: str | None = None,
        category: str | None = None,
        run_id: str | None = None,
        limit: int = 200,
    ) -> dict:
        query = {}
        if remark:
            query["remark"] = str(remark).strip()
        if category:
            query["category"] = str(category).strip()
        rows = self._find_pre_pools(query)
        if run_id:
            rows = [
                row
                for row in rows
                if str((row.get("extra") or {}).get("screening_run_id") or "") == run_id
            ]
        rows.sort(
            key=lambda item: self._sort_key(item.get("datetime")),
            reverse=True,
        )
        return {"rows": [self._format_pre_pool_row(row) for row in rows[:limit]]}

    def add_pre_pool_to_stock_pool(self, payload: dict | None) -> dict:
        payload = payload or {}
        code = self._normalize_code(payload.get("code"))
        if not code:
            raise ValueError("code required")
        query = {"code": code}
        if payload.get("category"):
            query["category"] = str(payload["category"]).strip()
        if payload.get("remark"):
            query["remark"] = str(payload["remark"]).strip()
        row = self._find_one_pre_pool(query)
        if row is None:
            raise ValueError("pre pool row not found")
        target_category = (
            str(payload.get("stock_pool_category") or "").strip()
            or str(row.get("category") or "").strip()
            or "自选股"
        )
        _save_stock_pool(
            code=code,
            category=target_category,
            dt=row.get("datetime") or pendulum.now(),
            stop_loss_price=row.get("stop_loss_price"),
            expire_days=int(payload.get("days") or 30),
            screening_source=row.get("remark"),
            screening_run_id=(row.get("extra") or {}).get("screening_run_id"),
        )
        return {"code": code, "category": target_category}

    def delete_pre_pool(self, payload: dict | None) -> dict:
        payload = payload or {}
        code = self._normalize_code(payload.get("code"))
        if not code:
            raise ValueError("code required")
        query = {"code": code}
        if payload.get("category"):
            query["category"] = str(payload["category"]).strip()
        if payload.get("remark"):
            query["remark"] = str(payload["remark"]).strip()
        collection = self.db["stock_pre_pools"]
        if hasattr(collection, "delete_many"):
            result = collection.delete_many(query)
            deleted_count = int(getattr(result, "deleted_count", 0))
        else:
            before = self._find_pre_pools({})
            remaining = [
                row
                for row in before
                if not all(row.get(key) == value for key, value in query.items())
            ]
            deleted_count = len(before) - len(remaining)
            if hasattr(collection, "docs"):
                collection.docs = remaining
        return {"deleted_count": deleted_count}

    def iter_sse(self, run_id: str, *, after: int = 0, once: bool = False):
        cursor = max(int(after or 0), 0)
        while True:
            events = self.session_store.wait_for_events(
                run_id, after=cursor, timeout=1.0
            )
            if events:
                for event in events:
                    cursor = int(event["seq"])
                    yield self._format_sse(event["event"], event)
                if once:
                    break
            elif once:
                break
            else:
                yield self._format_sse(
                    "heartbeat",
                    {"seq": cursor, "ts": datetime.now().astimezone().isoformat()},
                )
            snapshot = self.get_run(run_id)
            if snapshot["status"] in {"completed", "failed"} and cursor >= int(
                snapshot["event_count"]
            ):
                break

    def _execute_run(self, run_id: str, config: dict) -> None:
        self.session_store.publish_event(
            run_id,
            "started",
            {"strategy": config["model"], "params": self._jsonable(config)},
        )
        try:
            results = asyncio.run(self._run_model(run_id, config))
            _save_database_outputs(results, config)
            persisted_count = self._persist_results(run_id, config, results)
            self.session_store.publish_event(
                run_id,
                "summary",
                {
                    "strategy": config["model"],
                    "accepted_count": len(results),
                    "persisted_count": persisted_count,
                },
            )
            self.session_store.publish_event(
                run_id, "completed", {"status": "completed"}
            )
        except Exception as exc:
            message = str(exc)
            self.session_store.publish_event(run_id, "error", {"message": message})
            self.session_store.publish_event(
                run_id,
                "completed",
                {"status": "failed", "error": message},
            )

    async def _run_model(self, run_id: str, config: dict) -> list[Any]:
        if config["model"] == "clxs":
            strategy = self._make_clxs_strategy(run_id, config)
            return await strategy.screen(days=config["days"], code=config["code"])
        strategy = self._make_chanlun_strategy(run_id, config)
        kwargs = {
            "days": config["days"],
            "period": None if config["period_mode"] == "all" else config["periods"][0],
        }
        if config["input_mode"] == "single_code":
            kwargs["symbol"] = self._infer_symbol(config["code"])
            kwargs["code"] = config["code"]
        else:
            query = self._build_pre_pool_query(config)
            if query:
                kwargs["pre_pool_query"] = query
        return await strategy.screen(**kwargs)

    def _make_clxs_strategy(self, run_id: str, config: dict):
        from freshquant.screening.strategies.clxs import ClxsStrategy

        return ClxsStrategy(
            wave_opt=config["wave_opt"],
            stretch_opt=config["stretch_opt"],
            trend_opt=config["trend_opt"],
            model_opt=config["model_opt"],
            save_pre_pools=False,
            output_html=False,
            **self._make_strategy_hooks(run_id),
        )

    def _make_chanlun_strategy(self, run_id: str, config: dict):
        from freshquant.screening.strategies.chanlun_service import (
            ChanlunServiceStrategy,
        )

        return ChanlunServiceStrategy(
            periods=config["periods"],
            pool_expire_days=config["pool_expire_days"],
            save_signal=False,
            save_pools=False,
            save_pre_pools=False,
            max_concurrent=config["max_concurrent"],
            days=config["days"],
            output_html=False,
            **self._make_strategy_hooks(run_id),
        )

    def _make_strategy_hooks(self, run_id: str) -> dict:
        return {
            "on_universe": lambda payload: self.session_store.publish_event(
                run_id, "universe", self._jsonable(payload)
            ),
            "on_stock_progress": lambda payload: self.session_store.publish_event(
                run_id, "progress", self._jsonable(payload)
            ),
            "on_hit_raw": lambda payload: self.session_store.publish_event(
                run_id, "hit_raw", self._jsonable(payload)
            ),
            "on_result_accepted": lambda payload: self.session_store.publish_event(
                run_id, "accepted", self._jsonable(payload)
            ),
            "on_error": lambda payload: self.session_store.publish_event(
                run_id, "error", self._jsonable(payload)
            ),
        }

    def _persist_results(self, run_id: str, config: dict, results: list[Any]) -> int:
        if not config.get("save_pre_pools"):
            return 0
        persisted_count = 0
        for result in results:
            category = self._resolve_output_category(config, result)
            payload = {
                "code": result.code,
                "category": category,
                "dt": result.fire_time,
                "stop_loss_price": result.stop_loss_price,
                "expire_at_days": 89,
                "remark": config["remark"],
                "screening_run_id": run_id,
                "screening_model": config["model"],
                "screening_input_mode": config["input_mode"],
                "screening_source_scope": self._source_scope(config),
                "screening_signal_type": result.signal_type,
                "screening_signal_name": getattr(result, "remark", "")
                or result.signal_type,
                "screening_period": result.period,
                "screening_params": self._public_params(config),
            }
            _save_pre_pool(**payload)
            persisted_count += 1
            self.session_store.publish_event(
                run_id,
                "persisted",
                self._jsonable(
                    {
                        "code": result.code,
                        "category": category,
                        "remark": config["remark"],
                        "screening_run_id": run_id,
                    }
                ),
            )
        return persisted_count

    def _resolve_output_category(self, config: dict, result: Any) -> str:
        explicit = str(config.get("output_category") or "").strip()
        if explicit:
            return explicit
        if config["model"] == "clxs":
            return f"CLXS_{config['model_opt']}"
        if str(getattr(result, "category", "") or "").strip():
            return str(result.category).strip()
        return "chanlun_service"

    def _build_pre_pool_query(self, config: dict) -> dict | None:
        mode = config["input_mode"]
        if mode == "all_pre_pools":
            return None
        if mode == "category_filtered_pre_pools":
            return {"category": config["pre_pool_category"]}
        if mode == "remark_filtered_pre_pools":
            return {"remark": config["pre_pool_remark"]}
        return None

    def _public_params(self, config: dict) -> dict:
        if config["model"] == "clxs":
            return {
                "days": config["days"],
                "code": config["code"],
                "wave_opt": config["wave_opt"],
                "stretch_opt": config["stretch_opt"],
                "trend_opt": config["trend_opt"],
                "model_opt": config["model_opt"],
            }
        return {
            "days": config["days"],
            "code": config["code"],
            "input_mode": config["input_mode"],
            "period_mode": config["period_mode"],
            "pre_pool_category": config["pre_pool_category"],
            "pre_pool_remark": config["pre_pool_remark"],
            "max_concurrent": config["max_concurrent"],
            "save_signal": config["save_signal"],
            "save_pools": config["save_pools"],
            "pool_expire_days": config["pool_expire_days"],
        }

    def _source_scope(self, config: dict) -> str:
        mode = config["input_mode"]
        if mode == "category_filtered_pre_pools":
            return f"pre_pool_category:{config['pre_pool_category']}"
        if mode == "remark_filtered_pre_pools":
            return f"pre_pool_remark:{config['pre_pool_remark']}"
        return mode

    def _normalize_start_payload(self, payload: dict) -> dict:
        model = str(payload.get("model") or "").strip().lower()
        if model not in {"clxs", "chanlun"}:
            raise ValueError("model must be clxs or chanlun")
        if model == "clxs":
            code = self._normalize_code(payload.get("code"))
            model_opt = int(payload.get("model_opt") or 10001)
            return {
                "model": "clxs",
                "days": max(int(payload.get("days") or 1), 1),
                "code": code,
                "wave_opt": int(payload.get("wave_opt") or 1560),
                "stretch_opt": int(payload.get("stretch_opt") or 0),
                "trend_opt": int(payload.get("trend_opt") or 1),
                "model_opt": model_opt,
                "save_pre_pools": self._as_bool(payload.get("save_pre_pools"), True),
                "save_signal": False,
                "save_pools": False,
                "pool_expire_days": 10,
                "output_category": str(payload.get("output_category") or "").strip()
                or f"CLXS_{model_opt}",
                "remark": str(payload.get("remark") or "").strip()
                or "daily-screening:clxs",
                "input_mode": "single_code" if code else "market",
            }

        code = self._normalize_code(payload.get("code"))
        input_mode = str(payload.get("input_mode") or "").strip() or (
            "single_code" if code else "all_pre_pools"
        )
        if input_mode == "single_code" and not code:
            raise ValueError("code required for single_code")
        pre_pool_category = str(payload.get("pre_pool_category") or "").strip()
        pre_pool_remark = str(payload.get("pre_pool_remark") or "").strip()
        if input_mode == "category_filtered_pre_pools" and not pre_pool_category:
            raise ValueError("pre_pool_category required")
        if input_mode == "remark_filtered_pre_pools" and not pre_pool_remark:
            raise ValueError("pre_pool_remark required")
        period_mode = str(payload.get("period_mode") or "all").strip() or "all"
        periods = ["30m", "60m", "1d"] if period_mode == "all" else [period_mode]
        return {
            "model": "chanlun",
            "days": max(int(payload.get("days") or 1), 1),
            "code": code,
            "input_mode": input_mode,
            "period_mode": period_mode,
            "periods": periods,
            "pre_pool_category": pre_pool_category or None,
            "pre_pool_remark": pre_pool_remark or None,
            "max_concurrent": max(int(payload.get("max_concurrent") or 50), 1),
            "save_signal": self._as_bool(payload.get("save_signal"), False),
            "save_pools": self._as_bool(payload.get("save_pools"), False),
            "save_pre_pools": self._as_bool(payload.get("save_pre_pools"), True),
            "pool_expire_days": max(int(payload.get("pool_expire_days") or 10), 1),
            "output_category": str(payload.get("output_category") or "").strip()
            or (
                pre_pool_category
                if input_mode == "category_filtered_pre_pools"
                else "chanlun_service"
            ),
            "remark": str(payload.get("remark") or "").strip()
            or "daily-screening:chanlun",
        }

    def _find_pre_pools(self, query: dict) -> list[dict]:
        collection = self.db["stock_pre_pools"]
        rows = collection.find(query or {})
        return [dict(row) for row in list(rows)]

    def _find_one_pre_pool(self, query: dict) -> dict | None:
        collection = self.db["stock_pre_pools"]
        if hasattr(collection, "find_one"):
            row = collection.find_one(query)
            return dict(row) if row is not None else None
        rows = self._find_pre_pools(query)
        return rows[0] if rows else None

    def _format_pre_pool_row(self, row: dict) -> dict:
        extra = row.get("extra") or {}
        return {
            "code": row.get("code"),
            "symbol": self._infer_symbol(row.get("code")),
            "name": row.get("name") or "",
            "category": row.get("category") or "",
            "remark": row.get("remark") or "",
            "datetime": self._jsonable(row.get("datetime")),
            "expire_at": self._jsonable(row.get("expire_at")),
            "stop_loss_price": row.get("stop_loss_price"),
            "extra": self._jsonable(extra),
        }

    def _sort_key(self, value: Any):
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        return datetime.min

    def _format_sse(self, event: str, payload: dict) -> str:
        return (
            f"id: {payload.get('seq', '')}\n"
            f"event: {event}\n"
            f"data: {json.dumps(self._jsonable(payload), ensure_ascii=False)}\n\n"
        )

    def _jsonable(self, value: Any):
        if isinstance(value, dict):
            return {key: self._jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._jsonable(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return value

    def _normalize_code(self, value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        upper = text.upper()
        if "." in upper:
            upper = upper.split(".", 1)[0]
        if upper.startswith(("SH", "SZ")) and len(upper) >= 8:
            upper = upper[2:]
        digits = "".join(ch for ch in upper if ch.isdigit())
        if not digits:
            return None
        return digits[-6:].zfill(6)

    def _infer_symbol(self, code: Any) -> str:
        base = self._normalize_code(code)
        if not base:
            return ""
        prefix = "sh" if base.startswith(("5", "6", "9")) else "sz"
        return f"{prefix}{base}"

    def _as_bool(self, value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _clxs_schema(self) -> dict:
        return {
            "id": "clxs",
            "label": "CLXS",
            "fields": [
                {"name": "days", "type": "number", "default": 1},
                {"name": "code", "type": "text", "default": ""},
                {"name": "wave_opt", "type": "number", "default": 1560},
                {"name": "stretch_opt", "type": "number", "default": 0},
                {"name": "trend_opt", "type": "number", "default": 1},
                {
                    "name": "model_opt",
                    "type": "select",
                    "default": 10001,
                    "options": [
                        {"value": 8, "label": "MACD 背驰"},
                        {"value": 9, "label": "中枢回拉"},
                        {"value": 12, "label": "V 反"},
                        {"value": 10001, "label": "默认 CLXS"},
                    ],
                },
                {"name": "save_pre_pools", "type": "boolean", "default": True},
                {"name": "output_category", "type": "text", "default": "CLXS_10001"},
                {
                    "name": "remark",
                    "type": "text",
                    "default": "daily-screening:clxs",
                    "readonly": True,
                },
            ],
        }

    def _chanlun_schema(self) -> dict:
        return {
            "id": "chanlun",
            "label": "缠论服务",
            "fields": [
                {"name": "days", "type": "number", "default": 1},
                {
                    "name": "input_mode",
                    "type": "select",
                    "default": "all_pre_pools",
                    "options": [
                        {"value": "single_code", "label": "单票扫描"},
                        {"value": "all_pre_pools", "label": "全预选池"},
                        {
                            "value": "category_filtered_pre_pools",
                            "label": "按分类扫描预选池",
                        },
                        {
                            "value": "remark_filtered_pre_pools",
                            "label": "按来源扫描预选池",
                        },
                    ],
                },
                {"name": "code", "type": "text", "default": ""},
                {
                    "name": "period_mode",
                    "type": "select",
                    "default": "all",
                    "options": [
                        {"value": "all", "label": "30m / 60m / 1d"},
                        {"value": "30m", "label": "30m"},
                        {"value": "60m", "label": "60m"},
                        {"value": "1d", "label": "1d"},
                    ],
                },
                {"name": "pre_pool_category", "type": "text", "default": ""},
                {"name": "pre_pool_remark", "type": "text", "default": ""},
                {"name": "max_concurrent", "type": "number", "default": 50},
                {"name": "save_signal", "type": "boolean", "default": False},
                {"name": "save_pools", "type": "boolean", "default": False},
                {"name": "save_pre_pools", "type": "boolean", "default": True},
                {"name": "pool_expire_days", "type": "number", "default": 10},
                {
                    "name": "output_category",
                    "type": "text",
                    "default": "chanlun_service",
                },
                {
                    "name": "remark",
                    "type": "text",
                    "default": "daily-screening:chanlun",
                    "readonly": True,
                },
            ],
        }

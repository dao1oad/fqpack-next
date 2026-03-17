from __future__ import annotations

import asyncio
import json
import threading
from datetime import date, datetime
from typing import Any

import pendulum

from freshquant.daily_screening.pipeline_service import DailyScreeningPipelineService
from freshquant.daily_screening.session_store import DailyScreeningSessionStore
from freshquant.db import DBfreshquant
from freshquant.screening.signal_types import CHANLUN_SIGNAL_TYPES

CLXS_MODEL_OPTIONS: list[dict[str, int | str]] = [
    {"value": 8, "label": "MACD 背驰"},
    {"value": 9, "label": "中枢回拉"},
    {"value": 12, "label": "V 反"},
    {"value": 10001, "label": "默认 CLXS"},
]
DEFAULT_CLXS_MODEL_OPTS: list[int] = [int(item["value"]) for item in CLXS_MODEL_OPTIONS]
DEFAULT_CHANLUN_SIGNAL_TYPES: list[str] = [
    "buy_zs_huila",
    "buy_v_reverse",
    "macd_bullish_divergence",
    "sell_zs_huila",
    "sell_v_reverse",
    "macd_bearish_divergence",
]


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
        pipeline_service: DailyScreeningPipelineService | None = None,
    ) -> None:
        self.session_store = session_store or DailyScreeningSessionStore()
        self.db = db or DBfreshquant
        self.pipeline_service = pipeline_service or DailyScreeningPipelineService()

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
            "models": [
                self._all_schema(),
                self._clxs_schema(),
                self._chanlun_schema(),
            ],
            "options": {
                "pre_pool_categories": categories,
                "pre_pool_remarks": remarks,
            },
        }

    def start_run(self, payload: dict | None, *, run_async: bool = True) -> dict:
        config = self._normalize_start_payload(payload or {})
        run = self.pipeline_service.start_run(config, trigger_type="manual_api")
        run_id = self.session_store.create_run(
            run_id=run["id"],
            model=config["model"],
            params=config,
        )
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
        self.pipeline_service.execute_run(
            run_id,
            config,
            execute_stage=lambda stage_name, stage_config: self._execute_stage(
                run_id, stage_name, stage_config
            ),
            on_event=lambda event, payload: self.session_store.publish_event(
                run_id,
                event,
                self._jsonable(payload),
            ),
        )

    def _execute_stage(
        self,
        run_id: str,
        stage_name: str,
        config: dict,
    ) -> tuple[list[Any], int]:
        stage_config = {**config, "_pipeline_stage": stage_name}
        if (
            stage_name == "chanlun"
            and stage_config.get("_pipeline_parent_model") == "all"
            and stage_config.get("input_mode") != "single_code"
            and not stage_config.get("pre_pool_run_id")
        ):
            stage_config["pre_pool_run_id"] = run_id
        results = asyncio.run(self._run_model(run_id, stage_config))
        _save_database_outputs(results, stage_config)
        persisted_count = self._persist_results(run_id, stage_config, results)
        return results, persisted_count

    async def _run_model(self, run_id: str, config: dict) -> list[Any]:
        if config["model"] == "clxs":
            return await self._run_clxs_models(run_id, config)
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

    async def _run_all_pipeline(
        self, run_id: str, config: dict
    ) -> tuple[list[Any], int]:
        combined_results = []
        persisted_total = 0

        clxs_config = dict(config["clxs"])
        self.session_store.publish_event(
            run_id,
            "phase_started",
            {
                "branch": "clxs",
                "label": "CLXS 全模型",
                "model_opts": clxs_config["model_opts"],
            },
        )
        clxs_results = await self._run_clxs_models(run_id, clxs_config)
        combined_results.extend(clxs_results)
        _save_database_outputs(clxs_results, clxs_config)
        persisted_total += self._persist_results(run_id, clxs_config, clxs_results)
        self.session_store.publish_event(
            run_id,
            "phase_completed",
            {
                "branch": "clxs",
                "label": "CLXS 全模型",
                "accepted_count": len(clxs_results),
            },
        )

        chanlun_config = dict(config["chanlun"])
        if chanlun_config["input_mode"] != "single_code":
            chanlun_config["pre_pool_run_id"] = run_id
        self.session_store.publish_event(
            run_id,
            "phase_started",
            {
                "branch": "chanlun",
                "label": "chanlun 全信号",
                "signal_types": chanlun_config["signal_types"],
            },
        )
        chanlun_results = await self._run_model(run_id, chanlun_config)
        combined_results.extend(chanlun_results)
        _save_database_outputs(chanlun_results, chanlun_config)
        persisted_total += self._persist_results(
            run_id, chanlun_config, chanlun_results
        )
        self.session_store.publish_event(
            run_id,
            "phase_completed",
            {
                "branch": "chanlun",
                "label": "chanlun 全信号",
                "accepted_count": len(chanlun_results),
            },
        )

        return combined_results, persisted_total

    async def _run_clxs_models(self, run_id: str, config: dict) -> list[Any]:
        model_opts = list(config.get("model_opts") or [config["model_opt"]])
        results = []
        for model_opt in model_opts:
            step_config = {
                **config,
                "model_opt": model_opt,
            }
            strategy = self._make_clxs_strategy(run_id, step_config)
            step_results = await strategy.screen(
                days=step_config["days"],
                code=step_config["code"],
            )
            results.extend(step_results)
        return results

    def _make_clxs_strategy(self, run_id: str, config: dict):
        from freshquant.screening.strategies.clxs import ClxsStrategy

        return ClxsStrategy(
            wave_opt=config["wave_opt"],
            stretch_opt=config["stretch_opt"],
            trend_opt=config["trend_opt"],
            model_opt=config["model_opt"],
            save_pre_pools=False,
            output_html=False,
            **self._make_strategy_hooks(run_id, config),
        )

    def _make_chanlun_strategy(self, run_id: str, config: dict):
        from freshquant.screening.strategies.chanlun_service import (
            ChanlunServiceStrategy,
        )

        return ChanlunServiceStrategy(
            periods=config["periods"],
            signal_types=config.get("signal_types"),
            preserve_signal_variants=bool(
                config.get("preserve_signal_variants", False)
            ),
            pool_expire_days=config["pool_expire_days"],
            save_signal=False,
            save_pools=False,
            save_pre_pools=False,
            max_concurrent=config["max_concurrent"],
            days=config["days"],
            output_html=False,
            **self._make_strategy_hooks(run_id, config),
        )

    def _make_strategy_hooks(self, run_id: str, config: dict) -> dict:
        stage = str(config.get("_pipeline_stage") or config["model"]).strip()
        return {
            "on_universe": lambda payload: self.session_store.publish_event(
                run_id,
                "stage_progress",
                self._jsonable(
                    {
                        **self._with_context(config, payload),
                        "stage": stage,
                        "kind": "universe",
                    }
                ),
            ),
            "on_stock_progress": lambda payload: self.session_store.publish_event(
                run_id,
                "stage_progress",
                self._jsonable(
                    {
                        **self._with_context(config, payload),
                        "stage": stage,
                        "kind": "stock_progress",
                    }
                ),
            ),
            "on_hit_raw": lambda payload: self.session_store.publish_event(
                run_id,
                "stage_progress",
                self._jsonable(
                    {
                        **self._with_context(config, payload),
                        "stage": stage,
                        "kind": "hit_raw",
                    }
                ),
            ),
            "on_result_accepted": lambda payload: self.session_store.publish_event(
                run_id,
                "stage_progress",
                self._jsonable(
                    {
                        **self._with_context(config, payload),
                        "stage": stage,
                        "kind": "accepted",
                        "accepted_delta": 1,
                    }
                ),
            ),
            "on_error": lambda payload: self.session_store.publish_event(
                run_id,
                "stage_progress",
                self._jsonable(
                    {
                        **self._with_context(config, payload),
                        "stage": stage,
                        "kind": "error",
                    }
                ),
            ),
        }

    def _persist_results(self, run_id: str, config: dict, results: list[Any]) -> int:
        if not config.get("save_pre_pools"):
            return 0
        persisted_count = 0
        stage = str(config.get("_pipeline_stage") or config["model"]).strip()
        for result in results:
            category = self._resolve_output_category(config, result)
            model_meta = self._result_model_meta(config, result)
            payload = {
                "code": result.code,
                "category": category,
                "dt": result.fire_time,
                "stop_loss_price": result.stop_loss_price,
                "expire_at_days": 89,
                "remark": config["remark"],
                "screening_run_id": run_id,
                "screening_model": config["model"],
                "screening_branch": model_meta["branch"],
                "screening_model_key": model_meta["model_key"],
                "screening_model_label": model_meta["model_label"],
                "screening_input_mode": config["input_mode"],
                "screening_source_scope": self._source_scope(config),
                "screening_signal_type": result.signal_type,
                "screening_signal_name": getattr(result, "remark", "")
                or result.signal_type,
                "screening_period": result.period,
                "screening_params": self._public_params_for_result(config, result),
            }
            _save_pre_pool(**payload)
            persisted_count += 1
            self.session_store.publish_event(
                run_id,
                "stage_progress",
                self._jsonable(
                    {
                        "stage": stage,
                        "kind": "persisted",
                        "persisted_delta": 1,
                        "code": result.code,
                        "branch": model_meta["branch"],
                        "model_key": model_meta["model_key"],
                        "model_label": model_meta["model_label"],
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
            signal_type = str(getattr(result, "signal_type", "") or "").strip()
            if signal_type.startswith("CLXS_"):
                return signal_type
            return f"CLXS_{config['model_opt']}"
        if str(getattr(result, "category", "") or "").strip():
            return str(result.category).strip()
        return "chanlun_service"

    def _build_pre_pool_query(self, config: dict) -> dict | None:
        mode = config["input_mode"]
        if mode == "all_pre_pools":
            query = {}
        elif mode == "category_filtered_pre_pools":
            query = {"category": config["pre_pool_category"]}
        elif mode == "remark_filtered_pre_pools":
            query = {"remark": config["pre_pool_remark"]}
        else:
            return None
        if config.get("pre_pool_run_id"):
            query["extra.screening_run_id"] = config["pre_pool_run_id"]
        return query or None

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
            "pre_pool_run_id": config.get("pre_pool_run_id"),
            "signal_types": config.get("signal_types"),
            "max_concurrent": config["max_concurrent"],
            "save_signal": config["save_signal"],
            "save_pools": config["save_pools"],
            "pool_expire_days": config["pool_expire_days"],
        }

    def _public_params_for_result(self, config: dict, result: Any) -> dict:
        if config["model"] != "clxs":
            return self._public_params(config)
        model_opt = self._resolve_clxs_model_opt(result, fallback=config["model_opt"])
        return {
            "days": config["days"],
            "code": config["code"],
            "wave_opt": config["wave_opt"],
            "stretch_opt": config["stretch_opt"],
            "trend_opt": config["trend_opt"],
            "model_opt": model_opt,
        }

    def _resolve_clxs_model_opt(self, item: Any, *, fallback: int) -> int:
        signal_type = str(getattr(item, "signal_type", "") or "").strip()
        if signal_type.startswith("CLXS_"):
            try:
                return int(signal_type.split("_", 1)[1])
            except ValueError:
                return fallback
        return fallback

    def _source_scope(self, config: dict) -> str:
        mode = config["input_mode"]
        if mode == "category_filtered_pre_pools":
            return f"pre_pool_category:{config['pre_pool_category']}"
        if mode == "remark_filtered_pre_pools":
            return f"pre_pool_remark:{config['pre_pool_remark']}"
        return mode

    def _normalize_start_payload(self, payload: dict) -> dict:
        model = str(payload.get("model") or "").strip().lower()
        if model not in {"all", "clxs", "chanlun"}:
            raise ValueError("model must be all, clxs or chanlun")
        if model == "all":
            code = self._normalize_code(payload.get("code"))
            clxs_model_opts = self._normalize_int_list(
                payload.get("clxs_model_opts"),
                default=DEFAULT_CLXS_MODEL_OPTS,
            )
            chanlun_signal_types = self._normalize_text_list(
                payload.get("chanlun_signal_types"),
                default=DEFAULT_CHANLUN_SIGNAL_TYPES,
            )
            chanlun_period_mode = (
                str(payload.get("chanlun_period_mode") or "all").strip() or "all"
            )
            chanlun_periods = (
                ["30m", "60m", "1d"]
                if chanlun_period_mode == "all"
                else [chanlun_period_mode]
            )
            return {
                "model": "all",
                "days": max(int(payload.get("days") or 1), 1),
                "code": code,
                "save_pre_pools": True,
                "clxs": {
                    "model": "clxs",
                    "days": max(int(payload.get("days") or 1), 1),
                    "code": code,
                    "wave_opt": int(payload.get("wave_opt") or 1560),
                    "stretch_opt": int(payload.get("stretch_opt") or 0),
                    "trend_opt": int(payload.get("trend_opt") or 1),
                    "model_opt": clxs_model_opts[0],
                    "model_opts": clxs_model_opts,
                    "save_pre_pools": True,
                    "save_signal": False,
                    "save_pools": False,
                    "pool_expire_days": 10,
                    "output_category": "",
                    "remark": "daily-screening:clxs",
                    "input_mode": "single_code" if code else "market",
                },
                "chanlun": {
                    "model": "chanlun",
                    "days": max(int(payload.get("days") or 1), 1),
                    "code": code,
                    "input_mode": (
                        "single_code" if code else "remark_filtered_pre_pools"
                    ),
                    "period_mode": chanlun_period_mode,
                    "periods": chanlun_periods,
                    "pre_pool_category": None,
                    "pre_pool_remark": None if code else "daily-screening:clxs",
                    "pre_pool_run_id": None,
                    "signal_types": chanlun_signal_types,
                    "preserve_signal_variants": True,
                    "max_concurrent": max(
                        int(payload.get("chanlun_max_concurrent") or 50), 1
                    ),
                    "save_signal": False,
                    "save_pools": False,
                    "save_pre_pools": True,
                    "pool_expire_days": 10,
                    "output_category": "",
                    "remark": "daily-screening:chanlun",
                },
            }
        if model == "clxs":
            code = self._normalize_code(payload.get("code"))
            model_opts = self._normalize_int_list(
                payload.get("model_opts"),
                default=[int(payload.get("model_opt") or 10001)],
            )
            model_opt = model_opts[0]
            return {
                "model": "clxs",
                "days": max(int(payload.get("days") or 1), 1),
                "code": code,
                "wave_opt": int(payload.get("wave_opt") or 1560),
                "stretch_opt": int(payload.get("stretch_opt") or 0),
                "trend_opt": int(payload.get("trend_opt") or 1),
                "model_opt": model_opt,
                "model_opts": model_opts,
                "save_pre_pools": self._as_bool(payload.get("save_pre_pools"), True),
                "save_signal": False,
                "save_pools": False,
                "pool_expire_days": 10,
                "output_category": str(payload.get("output_category") or "").strip(),
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
            "pre_pool_run_id": str(payload.get("pre_pool_run_id") or "").strip()
            or None,
            "signal_types": self._normalize_text_list(
                payload.get("signal_types"),
                default=DEFAULT_CHANLUN_SIGNAL_TYPES,
            ),
            "preserve_signal_variants": True,
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
            "branch": extra.get("screening_branch") or "",
            "model_key": extra.get("screening_model_key") or "",
            "model_label": extra.get("screening_model_label") or "",
            "signal_type": extra.get("screening_signal_type") or "",
            "signal_name": extra.get("screening_signal_name") or "",
            "period": extra.get("screening_period") or "",
            "extra": self._jsonable(extra),
        }

    def _with_context(self, config: dict, payload: dict) -> dict:
        payload = dict(payload or {})
        model_meta = self._result_model_meta(config, payload)
        payload.setdefault("branch", model_meta["branch"])
        payload.setdefault("model_key", model_meta["model_key"])
        payload.setdefault("model_label", model_meta["model_label"])
        payload.setdefault("source_remark", config.get("remark") or "")
        return payload

    def _result_model_meta(self, config: dict, item: Any) -> dict:
        if isinstance(item, dict):
            signal_type = str(item.get("signal_type") or "").strip()
            label = str(item.get("remark") or "").strip()
        else:
            signal_type = str(getattr(item, "signal_type", "") or "").strip()
            label = str(getattr(item, "remark", "") or "").strip()
        branch = "clxs" if config["model"] == "clxs" else "chanlun"
        model_key = signal_type or (
            f"CLXS_{config['model_opt']}" if branch == "clxs" else branch
        )
        return {
            "branch": branch,
            "model_key": model_key,
            "model_label": label or model_key,
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

    def _normalize_text_list(self, value: Any, *, default: list[str]) -> list[str]:
        if value is None:
            return list(default)
        if isinstance(value, str):
            items = [part.strip() for part in value.split(",")]
        elif isinstance(value, (list, tuple, set)):
            items = [str(item).strip() for item in value]
        else:
            items = [str(value).strip()]
        normalized = [item for item in items if item]
        return normalized or list(default)

    def _normalize_int_list(self, value: Any, *, default: list[int]) -> list[int]:
        raw_items = self._normalize_text_list(
            value, default=[str(item) for item in default]
        )
        normalized = []
        for item in raw_items:
            try:
                normalized.append(int(item))
            except ValueError:
                continue
        return normalized or list(default)

    def _all_schema(self) -> dict:
        return {
            "id": "all",
            "label": "全链路",
            "fields": [
                {"name": "days", "type": "number", "default": 1},
                {"name": "code", "type": "text", "default": ""},
                {"name": "wave_opt", "type": "number", "default": 1560},
                {"name": "stretch_opt", "type": "number", "default": 0},
                {"name": "trend_opt", "type": "number", "default": 1},
                {
                    "name": "clxs_model_opts",
                    "type": "select",
                    "multiple": True,
                    "default": list(DEFAULT_CLXS_MODEL_OPTS),
                    "options": list(CLXS_MODEL_OPTIONS),
                },
                {
                    "name": "chanlun_signal_types",
                    "type": "select",
                    "multiple": True,
                    "default": list(DEFAULT_CHANLUN_SIGNAL_TYPES),
                    "options": [
                        {
                            "value": signal_type,
                            "label": CHANLUN_SIGNAL_TYPES[signal_type]["name"],
                        }
                        for signal_type in DEFAULT_CHANLUN_SIGNAL_TYPES
                    ],
                },
                {
                    "name": "chanlun_period_mode",
                    "type": "select",
                    "default": "all",
                    "options": [
                        {"value": "all", "label": "30m / 60m / 1d"},
                        {"value": "30m", "label": "30m"},
                        {"value": "60m", "label": "60m"},
                        {"value": "1d", "label": "1d"},
                    ],
                },
                {"name": "chanlun_max_concurrent", "type": "number", "default": 50},
                {
                    "name": "save_pre_pools",
                    "type": "boolean",
                    "default": True,
                    "readonly": True,
                },
                {
                    "name": "clxs_remark",
                    "type": "text",
                    "default": "daily-screening:clxs",
                    "readonly": True,
                },
                {
                    "name": "chanlun_remark",
                    "type": "text",
                    "default": "daily-screening:chanlun",
                    "readonly": True,
                },
            ],
        }

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
                    "name": "model_opts",
                    "type": "select",
                    "multiple": True,
                    "default": [10001],
                    "options": list(CLXS_MODEL_OPTIONS),
                },
                {"name": "save_pre_pools", "type": "boolean", "default": True},
                {"name": "output_category", "type": "text", "default": ""},
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
                {
                    "name": "signal_types",
                    "type": "select",
                    "multiple": True,
                    "default": list(DEFAULT_CHANLUN_SIGNAL_TYPES),
                    "options": [
                        {
                            "value": signal_type,
                            "label": CHANLUN_SIGNAL_TYPES[signal_type]["name"],
                        }
                        for signal_type in DEFAULT_CHANLUN_SIGNAL_TYPES
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
                    "default": "",
                },
                {
                    "name": "remark",
                    "type": "text",
                    "default": "daily-screening:chanlun",
                    "readonly": True,
                },
            ],
        }

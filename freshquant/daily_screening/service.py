from __future__ import annotations

import asyncio
import json
import threading
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pendulum

from freshquant.daily_screening.pipeline_service import DailyScreeningPipelineService
from freshquant.daily_screening.session_store import DailyScreeningSessionStore
from freshquant.db import DBfreshquant
from freshquant.screening.signal_types import CHANLUN_SIGNAL_TYPES

FULL_CLXS_MODEL_OPTS: list[int] = list(range(10001, 10013))
CLXS_MODEL_OPTIONS: list[dict[str, int | str]] = [
    {"value": model_opt, "label": f"S{model_opt % 10000:04d}"}
    for model_opt in FULL_CLXS_MODEL_OPTS
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


def _resolve_clxs_model_label(model_opt: Any) -> str | None:
    try:
        calc_type = int(model_opt) % 10000
    except (TypeError, ValueError):
        return None
    if calc_type <= 0:
        return None
    return f"S{calc_type:04d}"


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

    def get_scopes(self) -> dict:
        items = []
        for index, run in enumerate(self._list_repository_runs()):
            run_id = str(run.get("run_id") or run.get("id") or "").strip()
            if not run_id:
                continue
            items.append(
                {
                    "run_id": run_id,
                    "scope": self._run_scope(run_id),
                    "label": run_id,
                    "is_latest": index == 0,
                }
            )
        return {"items": items}

    def get_latest_scope(self) -> dict:
        items = self.get_scopes()["items"]
        if not items:
            return {
                "run_id": "",
                "scope": "",
                "label": "",
                "is_latest": False,
            }
        return dict(items[0])

    def get_scope_summary(self, run_id: str) -> dict:
        repository = self._screening_repository()
        if repository is None:
            return {
                "run_id": run_id,
                "scope": self._run_scope(run_id),
                "membership_count": 0,
                "stock_count": 0,
                "stage_counts": {},
                "stock_codes": [],
            }
        return repository.query_scope_summary(
            run_id=run_id,
            scope=self._run_scope(run_id),
        )

    def query_scope(self, run_id: str, payload: dict | None = None) -> dict:
        repository = self._screening_repository()
        scope = self._run_scope(run_id)
        if repository is None:
            return {
                "run_id": run_id,
                "scope": scope,
                "total": 0,
                "rows": [],
                "summary": self.get_scope_summary(run_id),
            }
        rows = repository.query_scope_stocks(run_id=run_id, scope=scope)
        filters = payload or {}
        filtered_rows = [
            row for row in rows if self._matches_scope_filters(row, filters)
        ]
        return {
            "run_id": run_id,
            "scope": scope,
            "total": len(filtered_rows),
            "rows": filtered_rows,
            "summary": self.get_scope_summary(run_id),
        }

    def get_stock_detail(self, run_id: str, code: Any) -> dict:
        normalized_code = self._normalize_code(code)
        if not normalized_code:
            raise ValueError("code required")
        repository = self._screening_repository()
        scope = self._run_scope(run_id)
        if repository is None:
            raise ValueError("stock detail not found")
        snapshots = repository.query_scope_stocks(
            run_id=run_id,
            scope=scope,
            code=normalized_code,
        )
        memberships = repository.get_stock_detail_memberships(
            run_id=run_id,
            scope=scope,
            code=normalized_code,
        )
        if not snapshots and not memberships:
            raise ValueError("stock detail not found")
        clxs_memberships = [item for item in memberships if item.get("stage") == "clxs"]
        chanlun_memberships = [
            item for item in memberships if item.get("stage") == "chanlun"
        ]
        agg90_memberships = [
            item for item in memberships if item.get("stage") == "shouban30_agg90"
        ]
        market_flag_memberships = [
            item for item in memberships if item.get("stage") == "market_flags"
        ]
        return {
            "run_id": run_id,
            "scope": scope,
            "snapshot": snapshots[0] if snapshots else None,
            "memberships": memberships,
            "clxs_memberships": clxs_memberships,
            "chanlun_memberships": chanlun_memberships,
            "agg90_memberships": agg90_memberships,
            "market_flag_memberships": market_flag_memberships,
            "hot_reasons": self._load_hot_reasons(normalized_code),
        }

    def add_to_pre_pool(self, payload: dict | None) -> dict:
        payload = payload or {}
        run_id = str(payload.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("run_id required")
        code = self._normalize_code(payload.get("code"))
        if not code:
            raise ValueError("code required")
        detail = self.get_stock_detail(run_id, code)
        snapshot = detail.get("snapshot") or {}
        memberships = list(detail.get("memberships") or [])
        primary = self._select_primary_membership(memberships)
        category = str(payload.get("category") or "").strip() or self._scope_category(
            snapshot, primary
        )
        remark = str(payload.get("remark") or "").strip() or self._scope_remark(primary)
        if not category:
            raise ValueError("category required")
        extra = self._scope_extra(run_id, primary)
        dt = (
            primary.get("fire_time")
            or snapshot.get("latest_fire_time")
            or pendulum.now()
        )
        save_payload = {
            "code": code,
            "category": category,
            "dt": dt,
            "name": snapshot.get("name") or primary.get("name") or "",
            "stop_loss_price": primary.get("stop_loss_price"),
            "remark": remark,
            "expire_at_days": 89,
            **extra,
        }
        _save_pre_pool(**save_payload)
        return {
            "code": code,
            "category": category,
            "remark": remark,
        }

    def add_batch_to_pre_pool(self, payload: dict | None) -> dict:
        payload = payload or {}
        run_id = str(payload.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("run_id required")
        scope_rows = self.query_scope(run_id, payload).get("rows") or []
        codes = []
        for row in scope_rows:
            code = self._normalize_code(row.get("code"))
            if not code:
                continue
            self.add_to_pre_pool(
                {
                    "run_id": run_id,
                    "code": code,
                    "remark": payload.get("remark"),
                    "category": payload.get("category"),
                }
            )
            codes.append(code)
        return {
            "created_count": len(codes),
            "codes": codes,
        }

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
            event_after = self._event_cursor_for_sse_after(cursor)
            events = self.session_store.wait_for_events(
                run_id, after=event_after, timeout=1.0
            )
            if events:
                for event in events:
                    internal_seq = int(event["seq"])
                    for output_index, (sse_event, payload) in enumerate(
                        self._iter_sse_outputs(run_id, event)
                    ):
                        sse_cursor = self._sse_cursor(internal_seq, output_index)
                        if sse_cursor <= cursor:
                            continue
                        cursor = sse_cursor
                        yield self._format_sse(sse_event, payload, sse_id=sse_cursor)
                if once:
                    break
            elif once:
                break
            else:
                yield self._format_sse(
                    "heartbeat",
                    {"seq": cursor, "ts": datetime.now().astimezone().isoformat()},
                    sse_id=cursor,
                )
            snapshot = self.get_run(run_id)
            if snapshot["status"] in {"completed", "failed"}:
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
        if stage_name == "chanlun" and stage_config.get("_pipeline_parent_model") == "all":
            if stage_config.get("input_mode") != "single_code":
                stage_config["_input_codes"] = self._current_clxs_run_codes(run_id)
                stage_config["input_mode"] = "current_clxs_run"
                stage_config["pre_pool_run_id"] = None
        if stage_name == "shouban30_agg90":
            results = self._run_shouban30_agg90_stage(run_id, stage_config)
        elif stage_name == "market_flags":
            results = self._run_market_flags_stage(run_id, stage_config)
        else:
            results = asyncio.run(self._run_model(run_id, stage_config))
        if stage_name in {"shouban30_agg90", "market_flags"}:
            for result in results:
                self._publish_manual_result_accepted(run_id, stage_config, result)
        _save_database_outputs(results, stage_config)
        persisted_count = self._persist_results(run_id, stage_config, results)
        self._persist_run_scope_read_model(run_id, stage_name, stage_config, results)
        return results, persisted_count

    async def _run_model(self, run_id: str, config: dict) -> list[Any]:
        if config["model"] == "clxs":
            return await self._run_clxs_models(run_id, config)
        if config.get("_input_codes") is not None:
            return await self._run_chanlun_current_clxs_universe(
                run_id,
                config,
                config.get("_input_codes") or [],
            )
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

    async def _run_chanlun_current_clxs_universe(
        self,
        run_id: str,
        config: dict,
        codes: list[str],
    ) -> list[Any]:
        normalized_codes = []
        seen_codes = set()
        for code in codes or []:
            normalized = self._normalize_code(code)
            if not normalized or normalized in seen_codes:
                continue
            seen_codes.add(normalized)
            normalized_codes.append(normalized)
        if not normalized_codes:
            return []

        stage = str(config.get("_pipeline_stage") or config["model"]).strip()
        self.session_store.publish_event(
            run_id,
            "stage_progress",
            self._jsonable(
                {
                    "stage": stage,
                    "kind": "universe",
                    "strategy": "chanlun_service",
                    "total": len(normalized_codes),
                    "mode": "current_clxs_run",
                    "code": None,
                }
            ),
        )

        strategy = self._make_chanlun_strategy(
            run_id,
            {
                **config,
                "_suppress_strategy_universe": True,
                "_suppress_strategy_stock_progress": True,
            },
        )
        results = []
        period = None if config["period_mode"] == "all" else config["periods"][0]
        total = len(normalized_codes)

        for processed, code in enumerate(normalized_codes, start=1):
            symbol = self._infer_symbol(code)
            try:
                stock_results = await strategy.screen(
                    symbol=symbol,
                    code=code,
                    period=period,
                    days=config["days"],
                )
            except Exception as exc:
                self.session_store.publish_event(
                    run_id,
                    "stage_progress",
                    self._jsonable(
                        {
                            "stage": stage,
                            "kind": "error",
                            "code": code,
                            "symbol": symbol,
                            "error": str(exc),
                        }
                    ),
                )
                stock_results = []
                status = "error"
            else:
                status = "ok" if stock_results else "empty"
            results.extend(stock_results)
            self.session_store.publish_event(
                run_id,
                "stage_progress",
                self._jsonable(
                    {
                        "stage": stage,
                        "kind": "stock_progress",
                        "strategy": "chanlun_service",
                        "processed": processed,
                        "total": total,
                        "code": code,
                        "symbol": symbol,
                        "result_count": len(stock_results),
                        "status": status,
                    }
                ),
            )
        return results

    def _run_shouban30_agg90_stage(self, run_id: str, config: dict) -> list[Any]:
        stage = str(config.get("_pipeline_stage") or config["model"]).strip()
        rows = self._load_shouban30_agg90_rows(config)
        total = len(rows)
        self.session_store.publish_event(
            run_id,
            "stage_progress",
            self._jsonable(
                {
                    "stage": stage,
                    "kind": "universe",
                    "strategy": "shouban30_agg90",
                    "total": total,
                    "trade_date": config.get("trade_date"),
                    "providers": list(config.get("providers") or []),
                }
            ),
        )
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            code = self._normalize_code(row.get("code6"))
            if not code:
                continue
            entry = grouped.setdefault(
                code,
                {
                    "code": code,
                    "name": str(row.get("name") or row.get("code6") or code),
                    "providers": set(),
                    "plate_refs": set(),
                    "latest_trade_date": None,
                },
            )
            provider = str(row.get("provider") or "").strip()
            plate_key = str(row.get("plate_key") or "").strip()
            if provider:
                entry["providers"].add(provider)
            if provider and plate_key:
                entry["plate_refs"].add(f"{provider}:{plate_key}")
            latest_trade_date = str(row.get("latest_trade_date") or row.get("as_of_date") or "").strip()
            if latest_trade_date and (
                entry["latest_trade_date"] is None or latest_trade_date > entry["latest_trade_date"]
            ):
                entry["latest_trade_date"] = latest_trade_date

        results: list[Any] = []
        total_codes = len(grouped)
        for processed, item in enumerate(grouped.values(), start=1):
            providers = sorted(item["providers"])
            label = " / ".join(providers) if providers else "90日聚合"
            result = SimpleNamespace(
                code=item["code"],
                name=item["name"],
                symbol=self._infer_symbol(item["code"]),
                period="90d",
                fire_time=self._trade_date_to_datetime(
                    item["latest_trade_date"] or config.get("trade_date")
                ),
                price=None,
                stop_loss_price=None,
                signal_type="agg90",
                position="BUY_LONG",
                remark=label,
                category="shouban30_agg90",
                providers=providers,
                plate_refs=sorted(item["plate_refs"]),
            )
            results.append(result)
            self.session_store.publish_event(
                run_id,
                "stage_progress",
                self._jsonable(
                    {
                        "stage": stage,
                        "kind": "stock_progress",
                        "strategy": "shouban30_agg90",
                        "processed": processed,
                        "total": total_codes,
                        "code": result.code,
                        "symbol": result.symbol,
                        "result_count": 1,
                        "status": "ok",
                    }
                ),
            )
        return results

    def _run_market_flags_stage(self, run_id: str, config: dict) -> list[Any]:
        from freshquant.data.gantt_readmodel import (
            _load_shouban30_credit_subject_lookup,
            _load_shouban30_quality_subject_lookup,
            _resolve_shouban30_extra_filter_result,
        )
        from freshquant.instrument.stock import fq_inst_fetch_stock_list

        stage = str(config.get("_pipeline_stage") or config["model"]).strip()
        stock_rows = list(fq_inst_fetch_stock_list() or [])
        self.session_store.publish_event(
            run_id,
            "stage_progress",
            self._jsonable(
                {
                    "stage": stage,
                    "kind": "universe",
                    "strategy": "market_flags",
                    "total": len(stock_rows),
                    "trade_date": config.get("trade_date"),
                }
            ),
        )
        credit_subject_lookup, credit_subject_snapshot_ready = (
            _load_shouban30_credit_subject_lookup()
        )
        (
            quality_subject_lookup,
            quality_subject_snapshot_ready,
            quality_subject_source_version,
        ) = _load_shouban30_quality_subject_lookup()
        filter_cache: dict[str, dict[str, Any]] = {}
        results: list[Any] = []
        total = len(stock_rows)
        for processed, row in enumerate(stock_rows, start=1):
            code = self._normalize_code(row.get("code"))
            if not code:
                continue
            filter_result = _resolve_shouban30_extra_filter_result(
                code,
                as_of_date=str(config.get("trade_date") or ""),
                filter_result_cache=filter_cache,
                credit_subject_lookup=credit_subject_lookup,
                credit_subject_snapshot_ready=credit_subject_snapshot_ready,
                quality_subject_lookup=quality_subject_lookup,
                quality_subject_snapshot_ready=quality_subject_snapshot_ready,
                quality_subject_source_version=quality_subject_source_version,
            )
            stock_results: list[Any] = []
            if config.get("include_credit_subject") and filter_result.get("is_credit_subject"):
                stock_results.append(
                    self._build_market_flag_result(
                        code=code,
                        name=row.get("name"),
                        trade_date=config.get("trade_date"),
                        signal_type="credit_subject",
                        remark="融资标的",
                        category="credit_subject",
                    )
                )
            if config.get("include_quality_subject") and filter_result.get("is_quality_subject"):
                stock_results.append(
                    self._build_market_flag_result(
                        code=code,
                        name=row.get("name"),
                        trade_date=config.get("trade_date"),
                        signal_type="quality_subject",
                        remark="优质标的",
                        category="quality_subject",
                    )
                )
            if config.get("include_near_long_term_ma") and filter_result.get(
                "near_long_term_ma_passed"
            ):
                basis = str(filter_result.get("near_long_term_ma_basis") or "").strip()
                stock_results.append(
                    self._build_market_flag_result(
                        code=code,
                        name=row.get("name"),
                        trade_date=config.get("trade_date"),
                        signal_type="near_long_term_ma",
                        remark=f"均线附近 {basis}" if basis else "均线附近",
                        category="near_long_term_ma",
                    )
            )
            results.extend(stock_results)
            self.session_store.publish_event(
                run_id,
                "stage_progress",
                self._jsonable(
                    {
                        "stage": stage,
                        "kind": "stock_progress",
                        "strategy": "market_flags",
                        "processed": processed,
                        "total": total,
                        "code": code,
                        "symbol": self._infer_symbol(code),
                        "result_count": len(stock_results),
                        "status": "ok" if stock_results else "empty",
                    }
                ),
            )
        return results

    def _load_shouban30_agg90_rows(self, config: dict) -> list[dict[str, Any]]:
        from freshquant.data.gantt_readmodel import COL_SHOUBAN30_STOCKS
        from freshquant.db import DBGantt

        providers = [
            str(item).strip()
            for item in (config.get("providers") or [])
            if str(item).strip()
        ]
        trade_date = str(config.get("trade_date") or "").strip()
        if not providers or not trade_date:
            return []
        collection = DBGantt[COL_SHOUBAN30_STOCKS]
        rows = list(
            collection.find(
                {
                    "provider": {"$in": providers},
                    "stock_window_days": int(config.get("window_days") or 90),
                    "as_of_date": {"$lte": trade_date},
                }
            )
        )
        if not rows:
            return []
        latest_as_of_date = max(
            str(row.get("as_of_date") or "").strip() for row in rows if row.get("as_of_date")
        )
        return [
            dict(row)
            for row in rows
            if str(row.get("as_of_date") or "").strip() == latest_as_of_date
        ]

    def _build_market_flag_result(
        self,
        *,
        code: str,
        name: Any,
        trade_date: Any,
        signal_type: str,
        remark: str,
        category: str,
    ) -> Any:
        return SimpleNamespace(
            code=code,
            name=str(name or code),
            symbol=self._infer_symbol(code),
            period="1d",
            fire_time=self._trade_date_to_datetime(trade_date),
            price=None,
            stop_loss_price=None,
            signal_type=signal_type,
            position="BUY_LONG",
            remark=remark,
            category=category,
        )

    def _publish_manual_result_accepted(self, run_id: str, config: dict, result: Any) -> None:
        stage = str(config.get("_pipeline_stage") or config["model"]).strip()
        payload = {
            **self._with_context(
                config,
                {
                    "code": getattr(result, "code", None),
                    "name": getattr(result, "name", None),
                    "symbol": getattr(result, "symbol", None),
                    "period": getattr(result, "period", None),
                    "fire_time": getattr(result, "fire_time", None),
                    "price": getattr(result, "price", None),
                    "stop_loss_price": getattr(result, "stop_loss_price", None),
                    "signal_type": getattr(result, "signal_type", None),
                    "position": getattr(result, "position", None),
                    "remark": getattr(result, "remark", None),
                    "category": getattr(result, "category", None),
                },
            ),
            "stage": stage,
            "kind": "accepted",
            "accepted_delta": 1,
        }
        self.session_store.publish_event(
            run_id,
            "stage_progress",
            self._jsonable(payload),
        )

    def _persist_run_scope_read_model(
        self,
        run_id: str,
        stage_name: str,
        config: dict,
        results: list[Any],
    ) -> None:
        repository = getattr(self.pipeline_service, "repository", None)
        if repository is None:
            return
        replace_stage_memberships = getattr(repository, "replace_stage_memberships", None)
        upsert_stock_snapshots = getattr(repository, "upsert_stock_snapshots", None)
        get_stock_detail_memberships = getattr(repository, "get_stock_detail_memberships", None)
        if not callable(replace_stage_memberships) or not callable(
            upsert_stock_snapshots
        ) or not callable(get_stock_detail_memberships):
            return
        scope = self._run_scope(run_id)
        memberships = [
            self._build_run_scope_membership(
                run_id=run_id,
                scope=scope,
                stage_name=stage_name,
                config=config,
                result=result,
            )
            for result in (results or [])
        ]
        replace_stage_memberships(
            run_id=run_id,
            stage=stage_name,
            scope=scope,
            memberships=memberships,
        )
        all_memberships = get_stock_detail_memberships(run_id=run_id, scope=scope)
        snapshots = self._build_run_scope_snapshots(
            run_id=run_id,
            scope=scope,
            memberships=all_memberships,
        )
        upsert_stock_snapshots(run_id=run_id, scope=scope, snapshots=snapshots)

    def _run_scope(self, run_id: str) -> str:
        return f"run:{run_id}"

    def _screening_repository(self):
        repository = getattr(self.pipeline_service, "repository", None)
        query_scope_summary = getattr(repository, "query_scope_summary", None)
        query_scope_stocks = getattr(repository, "query_scope_stocks", None)
        get_stock_detail_memberships = getattr(
            repository,
            "get_stock_detail_memberships",
            None,
        )
        if not callable(query_scope_summary) or not callable(query_scope_stocks):
            return None
        if not callable(get_stock_detail_memberships):
            return None
        return repository

    def _list_repository_runs(self) -> list[dict[str, Any]]:
        repository = self._screening_repository()
        if repository is None:
            return []
        runs_collection = getattr(repository, "runs", None)
        if isinstance(runs_collection, dict):
            rows = [dict(item) for item in runs_collection.values()]
        elif hasattr(runs_collection, "find"):
            rows = [dict(item) for item in list(runs_collection.find({}))]
        else:
            rows = []
        rows.sort(key=self._run_sort_key, reverse=True)
        return rows

    def _run_sort_key(self, row: dict[str, Any]):
        return (
            str(row.get("started_at") or row.get("created_at") or ""),
            str(row.get("run_id") or row.get("id") or ""),
        )

    def _matches_scope_filters(self, row: dict[str, Any], payload: dict) -> bool:
        selected_by = dict(row.get("selected_by") or {})
        selected_sets = self._normalize_text_list(payload.get("selected_sets"), default=[])
        for item in selected_sets:
            if not bool(selected_by.get(item)):
                return False

        clxs_models = set(
            self._normalize_text_list(payload.get("clxs_models"), default=[])
        )
        if clxs_models:
            snapshot_models = {
                str(item).strip() for item in list(row.get("clxs_models") or [])
                if str(item).strip()
            }
            if not snapshot_models.intersection(clxs_models):
                return False

        chanlun_signal_types = set(
            self._normalize_text_list(payload.get("chanlun_signal_types"), default=[])
        )
        chanlun_periods = set(
            self._normalize_text_list(payload.get("chanlun_periods"), default=[])
        )
        if chanlun_signal_types or chanlun_periods:
            variants = list(row.get("chanlun_variants") or [])

            def _variant_matches(item: dict[str, Any]) -> bool:
                signal_type = str(item.get("signal_type") or "").strip()
                period = str(item.get("period") or "").strip()
                if chanlun_signal_types and signal_type not in chanlun_signal_types:
                    return False
                if chanlun_periods and period not in chanlun_periods:
                    return False
                return True

            if not any(_variant_matches(item) for item in variants):
                return False

        shouban30_providers = set(
            self._normalize_text_list(payload.get("shouban30_providers"), default=[])
        )
        if shouban30_providers:
            providers = {
                str(item).strip()
                for item in list(row.get("shouban30_providers") or [])
                if str(item).strip()
            }
            if not providers.intersection(shouban30_providers):
                return False

        return True

    def _build_run_scope_membership(
        self,
        *,
        run_id: str,
        scope: str,
        stage_name: str,
        config: dict,
        result: Any,
    ) -> dict[str, Any]:
        model_meta = self._result_model_meta(config, result)
        return {
            "run_id": run_id,
            "scope": scope,
            "stage": stage_name,
            "code": self._normalize_code(getattr(result, "code", None)),
            "name": str(getattr(result, "name", "") or "").strip(),
            "symbol": str(getattr(result, "symbol", "") or "").strip(),
            "branch": model_meta["branch"],
            "model_key": model_meta["model_key"],
            "model_label": model_meta["model_label"],
            "signal_type": str(getattr(result, "signal_type", "") or "").strip(),
            "period": str(getattr(result, "period", "") or "").strip() or None,
            "fire_time": getattr(result, "fire_time", None),
            "stop_loss_price": getattr(result, "stop_loss_price", None),
            "category": str(getattr(result, "category", "") or "").strip() or None,
            "source_remark": str(config.get("remark") or "").strip() or None,
            "providers": sorted(
                {
                    str(item).strip()
                    for item in list(getattr(result, "providers", []) or [])
                    if str(item).strip()
                }
            ),
        }

    def _build_run_scope_snapshots(
        self,
        *,
        run_id: str,
        scope: str,
        memberships: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for item in memberships or []:
            code = self._normalize_code(item.get("code"))
            if not code:
                continue
            snapshot = grouped.setdefault(
                code,
                {
                    "run_id": run_id,
                    "scope": scope,
                    "code": code,
                    "name": str(item.get("name") or "").strip() or code,
                    "symbol": str(item.get("symbol") or "").strip()
                    or self._infer_symbol(code),
                    "selected_by": {
                        "clxs": False,
                        "chanlun": False,
                        "shouban30_agg90": False,
                        "credit_subject": False,
                        "quality_subject": False,
                        "near_long_term_ma": False,
                    },
                    "clxs_models": set(),
                    "chanlun_variants": set(),
                    "shouban30_providers": set(),
                },
            )
            if not snapshot["name"] and item.get("name"):
                snapshot["name"] = str(item.get("name") or "").strip() or code
            stage = str(item.get("stage") or "").strip()
            signal_type = str(item.get("signal_type") or "").strip()
            period = str(item.get("period") or "").strip()
            if stage == "clxs":
                snapshot["selected_by"]["clxs"] = True
                if item.get("model_key"):
                    snapshot["clxs_models"].add(str(item["model_key"]))
            elif stage == "chanlun":
                snapshot["selected_by"]["chanlun"] = True
                snapshot["chanlun_variants"].add((signal_type, period))
            elif stage == "shouban30_agg90":
                snapshot["selected_by"]["shouban30_agg90"] = True
                for provider in list(item.get("providers") or []):
                    provider_text = str(provider).strip()
                    if provider_text:
                        snapshot["shouban30_providers"].add(provider_text)
            elif stage == "market_flags":
                if signal_type == "credit_subject":
                    snapshot["selected_by"]["credit_subject"] = True
                elif signal_type == "quality_subject":
                    snapshot["selected_by"]["quality_subject"] = True
                elif signal_type == "near_long_term_ma":
                    snapshot["selected_by"]["near_long_term_ma"] = True
        snapshots: list[dict[str, Any]] = []
        for snapshot in grouped.values():
            snapshots.append(
                {
                    "run_id": run_id,
                    "scope": scope,
                    "code": snapshot["code"],
                    "name": snapshot["name"],
                    "symbol": snapshot["symbol"],
                    "selected_by": dict(snapshot["selected_by"]),
                    "clxs_models": sorted(snapshot["clxs_models"]),
                    "chanlun_variants": [
                        {"signal_type": signal_type, "period": period}
                        for signal_type, period in sorted(snapshot["chanlun_variants"])
                    ],
                    "shouban30_providers": sorted(snapshot["shouban30_providers"]),
                }
            )
        snapshots.sort(key=lambda item: item["code"])
        return snapshots

    async def _run_all_pipeline(
        self, run_id: str, config: dict
    ) -> tuple[list[Any], int]:
        combined_results = []
        persisted_total = 0

        clxs_config = dict(config["clxs"])
        clxs_results = await self._run_clxs_models(run_id, clxs_config)
        combined_results.extend(clxs_results)
        _save_database_outputs(clxs_results, clxs_config)
        persisted_total += self._persist_results(run_id, clxs_config, clxs_results)

        chanlun_config = dict(config["chanlun"])
        if chanlun_config["input_mode"] != "single_code":
            chanlun_config["pre_pool_run_id"] = run_id
        chanlun_results = await self._run_model(run_id, chanlun_config)
        combined_results.extend(chanlun_results)
        _save_database_outputs(chanlun_results, chanlun_config)
        persisted_total += self._persist_results(
            run_id, chanlun_config, chanlun_results
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
        suppress_universe = bool(config.get("_suppress_strategy_universe"))
        suppress_stock_progress = bool(config.get("_suppress_strategy_stock_progress"))
        return {
            "on_universe": (
                None
                if suppress_universe
                else lambda payload: self.session_store.publish_event(
                    run_id,
                    "stage_progress",
                    self._jsonable(
                        {
                            **self._with_context(config, payload),
                            "stage": stage,
                            "kind": "universe",
                        }
                    ),
                )
            ),
            "on_stock_progress": (
                None
                if suppress_stock_progress
                else lambda payload: self.session_store.publish_event(
                    run_id,
                    "stage_progress",
                    self._jsonable(
                        {
                            **self._with_context(config, payload),
                            "stage": stage,
                            "kind": "stock_progress",
                        }
                    ),
                )
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

    def _current_clxs_run_codes(self, run_id: str) -> list[str]:
        snapshot = self.session_store.get_run(run_id)
        codes = []
        seen_codes = set()
        for item in snapshot.get("results") or []:
            if str(item.get("branch") or "").strip() != "clxs":
                continue
            code = self._normalize_code(item.get("code"))
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            codes.append(code)
        return codes

    def _normalize_start_payload(self, payload: dict) -> dict:
        model = str(payload.get("model") or "").strip().lower()
        if model not in {"all", "clxs", "chanlun"}:
            raise ValueError("model must be all, clxs or chanlun")
        if model == "all":
            code = self._normalize_code(payload.get("code"))
            trade_date = str(payload.get("trade_date") or date.today().isoformat())
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
                "trade_date": trade_date,
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
                "shouban30_agg90": {
                    "model": "shouban30_agg90",
                    "trade_date": trade_date,
                    "window_days": 90,
                    "providers": ["xgb", "jygs"],
                },
                "market_flags": {
                    "model": "market_flags",
                    "trade_date": trade_date,
                    "include_credit_subject": True,
                    "include_quality_subject": True,
                    "include_near_long_term_ma": True,
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

    def _load_hot_reasons(self, code6: str) -> list[dict]:
        query_func = globals().get("query_stock_hot_reason_rows")
        if not callable(query_func):
            from freshquant.data.gantt_readmodel import query_stock_hot_reason_rows as query_func

        try:
            rows = query_func(code6=code6, provider="all", limit=0)
        except Exception:
            return []
        return [self._jsonable(dict(item)) for item in list(rows or [])]

    def _select_primary_membership(self, memberships: list[dict]) -> dict:
        if not memberships:
            return {}
        return sorted(memberships, key=self._membership_priority_key)[0]

    def _membership_priority_key(self, membership: dict):
        stage = str(membership.get("stage") or "").strip()
        priority = {
            "clxs": 0,
            "chanlun": 1,
            "shouban30_agg90": 2,
            "market_flags": 3,
        }.get(stage, 9)
        return (
            priority,
            str(membership.get("model_key") or membership.get("signal_type") or ""),
        )

    def _scope_category(self, snapshot: dict, membership: dict) -> str:
        return str(
            membership.get("model_key")
            or membership.get("signal_type")
            or snapshot.get("category")
            or membership.get("stage")
            or ""
        ).strip()

    def _scope_remark(self, membership: dict) -> str:
        branch = str(
            membership.get("branch") or membership.get("stage") or "screening"
        ).strip()
        return f"daily-screening:{branch}"

    def _scope_extra(self, run_id: str, membership: dict) -> dict:
        return {
            "screening_run_id": run_id,
            "screening_model": str(
                membership.get("branch") or membership.get("stage") or ""
            ).strip(),
            "screening_branch": str(membership.get("branch") or "").strip(),
            "screening_model_key": str(
                membership.get("model_key") or membership.get("signal_type") or ""
            ).strip(),
            "screening_model_label": str(
                membership.get("model_label")
                or membership.get("signal_name")
                or membership.get("signal_type")
                or ""
            ).strip(),
            "screening_input_mode": "run_scope",
            "screening_source_scope": self._run_scope(run_id),
            "screening_signal_type": str(membership.get("signal_type") or "").strip(),
            "screening_signal_name": str(membership.get("signal_name") or "").strip(),
            "screening_period": str(membership.get("period") or "").strip(),
            "screening_params": {"run_id": run_id},
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
        branch = str(config.get("model") or "").strip() or "chanlun"
        model_key = signal_type or (
            f"CLXS_{config['model_opt']}" if branch == "clxs" else branch
        )
        if branch == "clxs":
            model_opt = config.get("model_opt")
            if signal_type.startswith("CLXS_"):
                try:
                    model_opt = int(signal_type.removeprefix("CLXS_"))
                except ValueError:
                    model_opt = config.get("model_opt")
            model_label = _resolve_clxs_model_label(model_opt)
            return {
                "branch": branch,
                "model_key": model_key,
                "model_label": model_label or label or model_key,
            }
        if branch == "shouban30_agg90":
            return {
                "branch": branch,
                "model_key": model_key or "agg90",
                "model_label": label or "90日聚合",
            }
        if branch == "market_flags":
            return {
                "branch": branch,
                "model_key": model_key or "market_flags",
                "model_label": label or model_key or "市场属性",
            }
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

    def _trade_date_to_datetime(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        text = str(value or "").strip()
        if not text:
            return datetime.min
        try:
            return datetime.combine(date.fromisoformat(text), datetime.min.time())
        except ValueError:
            return datetime.min

    def _format_sse(self, event: str, payload: dict, *, sse_id: int | None = None) -> str:
        return (
            f"id: {sse_id if sse_id is not None else payload.get('seq', '')}\n"
            f"event: {event}\n"
            f"data: {json.dumps(self._jsonable(payload), ensure_ascii=False)}\n\n"
        )

    def _event_cursor_for_sse_after(self, after: int) -> int:
        if after <= 0:
            return 0
        return max((int(after) // 10) - 1, 0)

    def _sse_cursor(self, internal_seq: int, output_index: int) -> int:
        return max(int(internal_seq), 0) * 10 + max(int(output_index), 0)

    def _iter_sse_outputs(self, run_id: str, event: dict):
        yield event["event"], event
        for mapped_event, mapped_payload in self._legacy_sse_outputs(run_id, event):
            yield mapped_event, mapped_payload

    def _legacy_sse_outputs(self, run_id: str, event: dict):
        name = str(event.get("event") or "").strip()
        data = dict(event.get("data") or {})
        record = {
            "seq": event.get("seq"),
            "ts": event.get("ts"),
        }
        if name == "run_started":
            yield "started", {
                **record,
                "event": "started",
                "data": {
                    "strategy": data.get("model") or data.get("strategy"),
                    "params": self._jsonable(data.get("params") or {}),
                },
            }
            return
        if name == "stage_started":
            yield "phase_started", {
                **record,
                "event": "phase_started",
                "data": self._legacy_phase_payload(data),
            }
            return
        if name == "stage_progress":
            legacy_name = self._legacy_progress_event_name(data)
            if legacy_name is None:
                return
            yield legacy_name, {
                **record,
                "event": legacy_name,
                "data": self._legacy_progress_payload(data, legacy_name),
            }
            return
        if name == "stage_completed":
            yield "phase_completed", {
                **record,
                "event": "phase_completed",
                "data": self._legacy_phase_payload(data),
            }
            return
        if name == "run_completed":
            snapshot = self.get_run(run_id)
            summary = dict(data.get("summary") or {})
            yield "summary", {
                **record,
                "event": "summary",
                "data": {
                    "strategy": snapshot["model"],
                    "accepted_count": int(summary.get("accepted_count") or 0),
                    "persisted_count": int(summary.get("persisted_count") or 0),
                },
            }
            yield "completed", {
                **record,
                "event": "completed",
                "data": {"status": data.get("status") or "completed"},
            }
            return
        if name == "run_failed":
            message = str(data.get("message") or data.get("error") or "")
            yield "error", {
                **record,
                "event": "error",
                "data": {"message": message},
            }
            yield "completed", {
                **record,
                "event": "completed",
                "data": {"status": data.get("status") or "failed", "error": message},
            }

    def _legacy_phase_payload(self, data: dict) -> dict:
        payload = dict(data)
        payload.setdefault("branch", payload.get("stage") or "")
        return payload

    def _legacy_progress_event_name(self, data: dict) -> str | None:
        kind = str(data.get("kind") or "").strip()
        mapping = {
            "universe": "universe",
            "stock_progress": "progress",
            "hit_raw": "hit_raw",
            "accepted": "accepted",
            "persisted": "persisted",
            "error": "error",
        }
        return mapping.get(kind)

    def _legacy_progress_payload(self, data: dict, legacy_name: str) -> dict:
        payload = dict(data)
        payload.setdefault("branch", payload.get("stage") or "")
        if legacy_name == "error":
            payload["message"] = payload.get("message") or payload.get("error") or ""
        return payload

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

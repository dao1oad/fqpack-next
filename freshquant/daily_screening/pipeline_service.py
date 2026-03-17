from __future__ import annotations

import copy
import uuid
from datetime import datetime
from typing import Any, Callable

from freshquant.daily_screening.repository import DailyScreeningRepository


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


class DailyScreeningPipelineService:
    def __init__(self, *, repository=None) -> None:
        self.repository = repository or DailyScreeningRepository()

    def start_run(self, params: dict | None, *, trigger_type: str) -> dict:
        run_id = uuid.uuid4().hex[:12]
        created_at = _now_iso()
        run = {
            "id": run_id,
            "run_id": run_id,
            "params": copy.deepcopy(params or {}),
            "trigger_type": str(trigger_type or "").strip() or "manual_api",
            "status": "queued",
            "created_at": created_at,
            "started_at": None,
            "completed_at": None,
            "error": None,
            "summary": {},
            "stage_summaries": {},
        }
        saved = self.repository.save_run(run)
        return self.get_run(saved.get("run_id", run_id))

    def get_run(self, run_id: str) -> dict:
        saved = self.repository.get_run(run_id) or {}
        return self._normalize_run(saved, run_id=run_id)

    def execute_run(
        self,
        run_id: str,
        config: dict,
        *,
        execute_stage: Callable[[str, dict], tuple[list[Any], int]],
        on_event: Callable[[str, dict], None],
    ) -> dict:
        run = self.get_run(run_id)
        stage_summaries = copy.deepcopy(run.get("stage_summaries") or {})
        started_at = _now_iso()
        self.repository.save_run(
            run_id=run_id,
            status="running",
            started_at=started_at,
            completed_at=None,
            error=None,
            stage_summaries=stage_summaries,
        )
        on_event(
            "run_started",
            {
                "run_id": run_id,
                "status": "running",
                "model": config.get("model"),
                "params": copy.deepcopy(config),
            },
        )

        active_stage: str | None = None
        active_stage_config: dict | None = None
        accepted_total = 0
        persisted_total = 0

        try:
            for stage_name, stage_config in self._iter_stages(config):
                active_stage = stage_name
                active_stage_config = stage_config
                summary = {
                    "stage": stage_name,
                    "label": self._stage_label(stage_name, stage_config),
                    "status": "running",
                    "started_at": _now_iso(),
                    "completed_at": None,
                    "accepted_count": 0,
                    "persisted_count": 0,
                }
                stage_summaries[stage_name] = summary
                self.repository.save_run(run_id=run_id, stage_summaries=stage_summaries)
                on_event("stage_started", copy.deepcopy(summary))

                results, persisted_count = execute_stage(stage_name, stage_config)
                accepted_count = len(results or [])
                accepted_total += accepted_count
                persisted_total += int(persisted_count or 0)

                completed_summary = {
                    **summary,
                    "status": "completed",
                    "completed_at": _now_iso(),
                    "accepted_count": accepted_count,
                    "persisted_count": int(persisted_count or 0),
                }
                stage_summaries[stage_name] = completed_summary
                self.repository.save_run(
                    run_id=run_id,
                    stage_summaries=stage_summaries,
                )
                on_event("stage_completed", copy.deepcopy(completed_summary))
                active_stage = None
                active_stage_config = None

            summary = {
                "accepted_count": accepted_total,
                "persisted_count": persisted_total,
                "stage_count": len(stage_summaries),
            }
            completed_at = _now_iso()
            self.repository.save_run(
                run_id=run_id,
                status="completed",
                completed_at=completed_at,
                error=None,
                summary=summary,
                stage_summaries=stage_summaries,
            )
            on_event(
                "run_completed",
                {
                    "run_id": run_id,
                    "status": "completed",
                    "summary": copy.deepcopy(summary),
                    "stage_summaries": copy.deepcopy(stage_summaries),
                },
            )
        except Exception as exc:
            message = str(exc)
            if active_stage is not None:
                failed_summary = copy.deepcopy(stage_summaries.get(active_stage) or {})
                failed_summary.setdefault("stage", active_stage)
                failed_summary.setdefault(
                    "label",
                    self._stage_label(active_stage, active_stage_config or config),
                )
                failed_summary["status"] = "failed"
                failed_summary["completed_at"] = _now_iso()
                failed_summary["error"] = message
                stage_summaries[active_stage] = failed_summary
            completed_at = _now_iso()
            self.repository.save_run(
                run_id=run_id,
                status="failed",
                completed_at=completed_at,
                error=message,
                stage_summaries=stage_summaries,
            )
            on_event(
                "run_failed",
                {
                    "run_id": run_id,
                    "status": "failed",
                    "error": message,
                    "stage_summaries": copy.deepcopy(stage_summaries),
                },
            )

        return self.get_run(run_id)

    def _iter_stages(self, config: dict):
        model = str(config.get("model") or "").strip()
        if model == "all":
            yield "clxs", {**dict(config["clxs"]), "_pipeline_parent_model": "all"}
            yield "chanlun", {
                **dict(config["chanlun"]),
                "_pipeline_parent_model": "all",
            }
            return
        yield model, dict(config)

    def _stage_label(self, stage_name: str, config: dict) -> str:
        if stage_name == "clxs":
            model_opts = list(config.get("model_opts") or [])
            if len(model_opts) > 1:
                return "CLXS 全模型"
            model_opt = config.get("model_opt")
            if model_opt is not None:
                return f"CLXS_{model_opt}"
        if stage_name == "chanlun":
            signal_types = list(config.get("signal_types") or [])
            if len(signal_types) > 1:
                return "chanlun 全信号"
        return stage_name

    def _normalize_run(self, payload: dict, *, run_id: str) -> dict:
        normalized = dict(payload or {})
        effective_run_id = str(
            normalized.get("run_id") or normalized.get("id") or run_id
        )
        normalized["id"] = effective_run_id
        normalized["run_id"] = effective_run_id
        normalized["params"] = copy.deepcopy(normalized.get("params") or {})
        normalized["summary"] = copy.deepcopy(normalized.get("summary") or {})
        normalized["stage_summaries"] = copy.deepcopy(
            normalized.get("stage_summaries") or {}
        )
        return normalized

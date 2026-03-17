from __future__ import annotations

import copy
import threading
import uuid
from datetime import datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


class DailyScreeningSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_run(self, *, model: str, params: dict, run_id: str | None = None) -> str:
        run_id = str(run_id or uuid.uuid4().hex[:12])
        condition = threading.Condition()
        session: dict[str, Any] = {
            "id": run_id,
            "model": model,
            "params": copy.deepcopy(params),
            "status": "queued",
            "created_at": _now_iso(),
            "started_at": None,
            "completed_at": None,
            "error": None,
            "summary": {},
            "stage_summaries": {},
            "progress": {
                "processed": 0,
                "total": 0,
                "accepted": 0,
                "persisted": 0,
            },
            "results": [],
            "event_count": 0,
            "events": [],
            "_condition": condition,
        }
        with self._lock:
            self._sessions[run_id] = session
        return run_id

    def publish_event(self, run_id: str, event: str, data: dict | None = None) -> dict:
        session = self._require_session(run_id)
        condition = session["_condition"]
        payload = copy.deepcopy(data or {})
        with condition:
            seq = int(session["event_count"]) + 1
            record = {
                "seq": seq,
                "event": event,
                "ts": _now_iso(),
                "data": payload,
            }
            session["events"].append(record)
            session["event_count"] = seq
            self._apply_event(session, record)
            condition.notify_all()
        return copy.deepcopy(record)

    def get_run(self, run_id: str) -> dict:
        session = self._require_session(run_id)
        return self._snapshot(session)

    def get_events(self, run_id: str, after: int = 0) -> list[dict]:
        session = self._require_session(run_id)
        return copy.deepcopy(
            [
                event
                for event in session["events"]
                if int(event["seq"]) > int(after or 0)
            ]
        )

    def wait_for_events(
        self, run_id: str, *, after: int = 0, timeout: float = 1.0
    ) -> list[dict]:
        session = self._require_session(run_id)
        condition = session["_condition"]
        with condition:
            if int(session["event_count"]) <= int(after or 0) and session[
                "status"
            ] not in {"completed", "failed"}:
                condition.wait(timeout=timeout)
            return copy.deepcopy(
                [
                    event
                    for event in session["events"]
                    if int(event["seq"]) > int(after or 0)
                ]
            )

    def _require_session(self, run_id: str) -> dict:
        with self._lock:
            session = self._sessions.get(run_id)
        if session is None:
            raise KeyError(run_id)
        return session

    def _snapshot(self, session: dict) -> dict:
        return {
            "id": session["id"],
            "model": session["model"],
            "params": copy.deepcopy(session["params"]),
            "status": session["status"],
            "created_at": session["created_at"],
            "started_at": session["started_at"],
            "completed_at": session["completed_at"],
            "error": session["error"],
            "summary": copy.deepcopy(session["summary"]),
            "stage_summaries": copy.deepcopy(session["stage_summaries"]),
            "progress": copy.deepcopy(session["progress"]),
            "results": copy.deepcopy(session["results"]),
            "event_count": int(session["event_count"]),
        }

    def _apply_event(self, session: dict, record: dict) -> None:
        event = record["event"]
        data = record["data"]
        if event == "run_started":
            session["status"] = "running"
            session["started_at"] = record["ts"]
        elif event == "stage_started":
            stage = str(data.get("stage") or "").strip()
            if stage:
                current = copy.deepcopy(session["stage_summaries"].get(stage) or {})
                current.update(
                    {
                        "stage": stage,
                        "label": data.get("label") or current.get("label") or stage,
                        "status": "running",
                        "started_at": data.get("started_at") or record["ts"],
                    }
                )
                session["stage_summaries"][stage] = current
        elif event == "stage_progress":
            stage = str(data.get("stage") or "").strip()
            if stage:
                current = copy.deepcopy(session["stage_summaries"].get(stage) or {})
                current.setdefault("stage", stage)
                current.setdefault("label", data.get("label") or stage)
                current.setdefault("status", "running")
                session["stage_summaries"][stage] = current
            kind = str(data.get("kind") or "").strip()
            if kind == "universe":
                total = int(data.get("total") or 0)
                if total > 0:
                    session["progress"]["total"] = total
            elif kind == "stock_progress":
                session["progress"]["processed"] = max(
                    int(session["progress"]["processed"]),
                    int(data.get("processed") or 0),
                )
                total = int(data.get("total") or 0)
                if total > 0:
                    session["progress"]["total"] = total
            elif kind == "accepted":
                delta = max(int(data.get("accepted_delta") or 1), 0)
                session["progress"]["accepted"] += delta
                session["results"].append(copy.deepcopy(data))
            elif kind == "persisted":
                delta = max(int(data.get("persisted_delta") or 1), 0)
                session["progress"]["persisted"] += delta
            elif kind == "error":
                session["error"] = data.get("message") or data.get("error")
        elif event == "stage_completed":
            stage = str(data.get("stage") or "").strip()
            if stage:
                current = copy.deepcopy(session["stage_summaries"].get(stage) or {})
                current.update(copy.deepcopy(data))
                current.setdefault("stage", stage)
                current["status"] = data.get("status") or "completed"
                current["completed_at"] = data.get("completed_at") or record["ts"]
                session["stage_summaries"][stage] = current
        elif event == "run_completed":
            session["status"] = data.get("status") or "completed"
            session["completed_at"] = record["ts"]
            session["summary"] = copy.deepcopy(data.get("summary") or {})
            if data.get("stage_summaries"):
                session["stage_summaries"] = copy.deepcopy(data["stage_summaries"])
        elif event == "run_failed":
            session["status"] = data.get("status") or "failed"
            session["completed_at"] = record["ts"]
            session["error"] = data.get("message") or data.get("error")
            if data.get("stage_summaries"):
                session["stage_summaries"] = copy.deepcopy(data["stage_summaries"])
        elif event == "started":
            session["status"] = "running"
            session["started_at"] = record["ts"]
        elif event == "universe":
            total = int(data.get("total") or 0)
            if total > 0:
                session["progress"]["total"] = total
        elif event == "progress":
            session["progress"]["processed"] = max(
                int(session["progress"]["processed"]),
                int(data.get("processed") or 0),
            )
            total = int(data.get("total") or 0)
            if total > 0:
                session["progress"]["total"] = total
        elif event == "accepted":
            session["progress"]["accepted"] += 1
            session["results"].append(copy.deepcopy(data))
        elif event == "persisted":
            session["progress"]["persisted"] += 1
        elif event == "summary":
            session["summary"] = copy.deepcopy(data)
        elif event == "error":
            session["error"] = data.get("message") or data.get("error")
        elif event == "completed":
            session["status"] = data.get("status") or "completed"
            session["completed_at"] = record["ts"]
            if data.get("error"):
                session["error"] = data["error"]

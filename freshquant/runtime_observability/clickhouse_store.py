from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests  # type: ignore[import-untyped]

from freshquant.runtime_observability.assembler import (
    _find_inline_symbol_name,
    _lookup_symbol_name,
)
from freshquant.runtime_observability.logger import get_runtime_log_root
from freshquant.runtime_observability.node_catalog import COMPONENTS
from freshquant.runtime_observability.sessioning import build_session_identity
from freshquant.util.code import normalize_to_base_code

_ISSUE_STATUSES = {"warning", "failed", "error", "skipped"}
_HEALTH_EVENT_TYPES = {"heartbeat", "metric_snapshot"}
_CLICKHOUSE_TIMEZONE = ZoneInfo("Asia/Shanghai")
_SYMBOL_FIELDS = (
    "symbol",
    "code",
    "stock_code",
    "security_code",
    "ticker",
    "instrument",
    "instrument_id",
)


class RuntimeObservabilityStoreError(RuntimeError):
    pass


def build_clickhouse_event_row(
    event: dict[str, Any],
    *,
    raw_file: str,
    raw_line: int,
    ingest_ts: datetime | None = None,
) -> dict[str, Any]:
    payload = dict(event or {})
    payload_body_raw = payload.get("payload")
    payload_body: dict[str, Any] = (
        payload_body_raw if isinstance(payload_body_raw, dict) else {}
    )
    session_identity = build_session_identity(payload)
    ts = _parse_datetime(payload.get("ts"))
    raw_json = _to_json_text(payload)
    event_id = hashlib.sha1(
        f"{raw_file}:{raw_line}:{raw_json}".encode("utf-8", errors="ignore")
    ).hexdigest()
    decision_outcome = payload.get("decision_outcome")
    if isinstance(decision_outcome, (dict, list)):
        decision_outcome = _to_json_text(decision_outcome)
    symbol = resolve_runtime_symbol(payload)
    symbol_name = resolve_runtime_symbol_name(payload, symbol=symbol)
    return {
        "event_id": event_id,
        "ts": _format_clickhouse_datetime(ts),
        "event_day": ts.strftime("%Y-%m-%d"),
        "runtime_node": _normalized_text(payload.get("runtime_node")),
        "component": _normalized_text(payload.get("component")),
        "node": _normalized_text(payload.get("node")),
        "event_type": _normalized_text(payload.get("event_type")) or "trace_step",
        "status": _normalized_text(payload.get("status")) or "info",
        "trace_id": _normalized_text(payload.get("trace_id")),
        "intent_id": _normalized_text(payload.get("intent_id")),
        "request_id": _normalized_text(payload.get("request_id")),
        "internal_order_id": _normalized_text(payload.get("internal_order_id")),
        "session_key": session_identity["session_key"],
        "session_type": session_identity["session_type"],
        "symbol": symbol,
        "symbol_name": symbol_name,
        "message": _normalized_text(payload.get("message")),
        "reason_code": _normalized_text(payload.get("reason_code")),
        "source": _normalized_text(payload.get("source")),
        "strategy_name": _normalized_text(payload.get("strategy_name")),
        "decision_branch": _normalized_text(payload.get("decision_branch")),
        "decision_expr": _normalized_text(payload.get("decision_expr")),
        "decision_outcome": _normalized_text(decision_outcome),
        "error_type": _normalized_text(payload_body.get("error_type")),
        "error_message": _normalized_text(payload_body.get("error_message")),
        "is_issue": (
            1
            if _normalized_text(payload.get("status")).lower() in _ISSUE_STATUSES
            else 0
        ),
        "is_health": (
            1
            if _normalized_text(payload.get("event_type")) in _HEALTH_EVENT_TYPES
            else 0
        ),
        "payload_json": _to_json_text(
            payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        ),
        "metrics_json": _to_json_text(
            payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        ),
        "raw_json": raw_json,
        "raw_file": raw_file,
        "raw_line": int(raw_line),
        "ingest_ts": _format_clickhouse_datetime(
            ingest_ts or datetime.now().astimezone()
        ),
    }


class RuntimeObservabilityClickHouseStore:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        database: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self.base_url = str(
            base_url
            or os.environ.get("FQ_RUNTIME_CLICKHOUSE_URL")
            or "http://127.0.0.1:8123"
        ).rstrip("/")
        self.database = str(
            database or os.environ.get("FQ_RUNTIME_CLICKHOUSE_DATABASE") or "default"
        ).strip()
        self.username = str(
            username or os.environ.get("FQ_RUNTIME_CLICKHOUSE_USER") or "default"
        ).strip()
        self.password = str(
            password or os.environ.get("FQ_RUNTIME_CLICKHOUSE_PASSWORD") or ""
        )
        self.timeout_s = float(timeout_s)
        self._schema_ready = False

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        for statement in (
            """
            CREATE TABLE IF NOT EXISTS runtime_events (
                event_id String,
                ts DateTime64(3, 'Asia/Shanghai'),
                event_day Date,
                runtime_node LowCardinality(String),
                component LowCardinality(String),
                node LowCardinality(String),
                event_type LowCardinality(String),
                status LowCardinality(String),
                trace_id String,
                intent_id String,
                request_id String,
                internal_order_id String,
                session_key String,
                session_type LowCardinality(String),
                symbol String,
                symbol_name String,
                message String,
                reason_code String,
                source String,
                strategy_name String,
                decision_branch String,
                decision_expr String,
                decision_outcome String,
                error_type String,
                error_message String,
                is_issue UInt8,
                is_health UInt8,
                payload_json String,
                metrics_json String,
                raw_json String,
                raw_file String,
                raw_line UInt64,
                ingest_ts DateTime64(3, 'Asia/Shanghai')
            )
            ENGINE = MergeTree
            PARTITION BY toYYYYMM(event_day)
            ORDER BY (event_day, component, runtime_node, session_key, ts, event_id)
            """,
            """
            CREATE TABLE IF NOT EXISTS runtime_ingest_progress (
                raw_file String,
                offset_bytes UInt64,
                file_size UInt64,
                mtime Float64,
                updated_at DateTime64(3, 'Asia/Shanghai')
            )
            ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY raw_file
            """,
        ):
            self._execute_command(statement)
        self._schema_ready = True

    def load_progress(self, raw_file: str) -> int:
        self.ensure_schema()
        rows = self._select_rows(
            "SELECT argMax(offset_bytes, updated_at) AS offset_bytes "
            f"FROM runtime_ingest_progress WHERE raw_file = {_sql_string(raw_file)}"
        )
        return int(rows[0].get("offset_bytes") or 0) if rows else 0

    def record_progress(
        self,
        raw_file: str,
        offset_bytes: int,
        *,
        file_size: int | None = None,
        mtime: float | None = None,
    ) -> None:
        self.ensure_schema()
        self._insert_json_each_row(
            "runtime_ingest_progress",
            [
                {
                    "raw_file": raw_file,
                    "offset_bytes": int(offset_bytes),
                    "file_size": int(file_size or 0),
                    "mtime": float(mtime or 0.0),
                    "updated_at": _format_clickhouse_datetime(
                        datetime.now().astimezone()
                    ),
                }
            ],
        )

    def insert_events(
        self, events: list[dict[str, Any]] | tuple[dict[str, Any], ...]
    ) -> None:
        self.ensure_schema()
        rows = []
        for event in events or []:
            raw_file = (
                _normalized_text(event.get("raw_file"))
                if isinstance(event, dict)
                else ""
            )
            if not raw_file:
                continue
            rows.append(
                build_clickhouse_event_row(
                    event,
                    raw_file=raw_file,
                    raw_line=int(event.get("raw_line") or 0),
                )
            )
        if rows:
            self._insert_json_each_row("runtime_events", rows)

    def list_components(self) -> dict[str, Any]:
        self.ensure_schema()
        rows = self._select_rows(
            "SELECT DISTINCT runtime_node FROM runtime_events ORDER BY runtime_node ASC"
        )
        return {
            "root": str(get_runtime_log_root()),
            "runtime_nodes": [
                str(row.get("runtime_node") or "").strip()
                for row in rows
                if row.get("runtime_node")
            ],
            "components": list(COMPONENTS),
        }

    def get_health_summary(
        self,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        conditions = _build_where_conditions(start_time=start_time, end_time=end_time)
        query = f"""
        SELECT
            component,
            runtime_node,
            argMax(status, ts) AS latest_status,
            nullIf(
                maxIf(ts, is_health = 1),
                toDateTime64('1970-01-01 08:00:00', 3, 'Asia/Shanghai')
            ) AS heartbeat_ts,
            argMaxIf(metrics_json, ts, is_health = 1) AS metrics_json,
            countDistinctIf(session_key, session_key != '') AS trace_count,
            countDistinctIf(session_key, session_key != '' AND is_issue = 1) AS issue_trace_count,
            countIf(session_key != '' AND is_issue = 1) AS issue_step_count,
            nullIf(
                maxIf(ts, is_issue = 1),
                toDateTime64('1970-01-01 08:00:00', 3, 'Asia/Shanghai')
            ) AS last_issue_ts
        FROM runtime_events
        WHERE {conditions}
        GROUP BY component, runtime_node
        ORDER BY component ASC, runtime_node ASC
        """
        rows = self._select_rows(query)
        reference_time = (
            end_time.astimezone(_CLICKHOUSE_TIMEZONE)
            if end_time
            else datetime.now(_CLICKHOUSE_TIMEZONE)
        )
        items = []
        for row in rows:
            heartbeat_ts = _clickhouse_ts_to_datetime(row.get("heartbeat_ts"))
            items.append(
                {
                    "component": _normalized_text(row.get("component")),
                    "runtime_node": _normalized_text(row.get("runtime_node")),
                    "status": _normalized_text(row.get("latest_status")) or "unknown",
                    "heartbeat_age_s": (
                        None
                        if heartbeat_ts is None
                        else round(
                            max(0.0, (reference_time - heartbeat_ts).total_seconds()), 3
                        )
                    ),
                    "metrics": _decode_json_text(row.get("metrics_json")),
                    "trace_count": int(row.get("trace_count") or 0),
                    "issue_trace_count": int(row.get("issue_trace_count") or 0),
                    "issue_step_count": int(row.get("issue_step_count") or 0),
                    "last_issue_ts": _clickhouse_ts_to_iso(row.get("last_issue_ts"))
                    or None,
                    "is_placeholder": False,
                }
            )
        return {"components": items}

    def list_traces(
        self,
        *,
        filters: dict[str, Any] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 50,
        cursor_ts: str = "",
        cursor_trace_key: str = "",
    ) -> dict[str, Any]:
        self.ensure_schema()
        safe_limit = max(int(limit or 1), 1)
        base_query = _build_trace_summary_query(
            filters=filters,
            start_time=start_time,
            end_time=end_time,
        )
        cursor_condition = _build_trace_cursor_condition(cursor_ts, cursor_trace_key)
        rows = self._select_rows(
            f"""
            SELECT *
            FROM ({base_query})
            WHERE {cursor_condition}
            ORDER BY last_ts DESC, trace_key DESC
            LIMIT {safe_limit + 1}
            """
        )
        next_cursor = None
        if len(rows) > safe_limit:
            cursor_row = rows[safe_limit]
            next_cursor = {
                "ts": _clickhouse_ts_to_iso(cursor_row.get("last_ts")),
                "trace_key": _normalized_text(cursor_row.get("trace_key")),
            }
            rows = rows[:safe_limit]
        return {
            "items": [_serialize_trace_summary_row(row) for row in rows],
            "next_cursor": next_cursor,
        }

    def get_trace_detail(
        self,
        trace_key: str,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        step_limit: int = 200,
    ) -> dict[str, Any] | None:
        self.ensure_schema()
        normalized_trace_key = _normalized_text(trace_key)
        if not normalized_trace_key:
            return None
        rows = self._select_rows(
            _build_trace_summary_query(
                filters=None,
                start_time=start_time,
                end_time=end_time,
                trace_key=normalized_trace_key,
            )
        )
        if not rows:
            return None
        trace = _serialize_trace_summary_row(rows[0])
        step_page = self.list_trace_steps(
            normalized_trace_key,
            start_time=start_time,
            end_time=end_time,
            limit=step_limit,
        )
        return {
            "trace": trace,
            "steps": step_page["items"],
            "steps_next_cursor": step_page["next_cursor"],
        }

    def list_trace_steps(
        self,
        trace_key: str,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 200,
        cursor_ts: str = "",
        cursor_event_id: str = "",
    ) -> dict[str, Any]:
        self.ensure_schema()
        safe_limit = max(int(limit or 1), 1)
        conditions = _build_where_conditions(
            filters={"session_key": _normalized_text(trace_key)},
            start_time=start_time,
            end_time=end_time,
        )
        cursor_condition = _build_event_cursor_condition(cursor_ts, cursor_event_id)
        rows = self._select_rows(
            f"""
            SELECT
                event_id,
                session_key,
                ts,
                runtime_node,
                component,
                node,
                status,
                event_type,
                trace_id,
                intent_id,
                request_id,
                internal_order_id,
                symbol,
                symbol_name,
                message,
                reason_code,
                payload_json,
                metrics_json,
                raw_file,
                raw_line,
                error_type,
                error_message
            FROM runtime_events
            WHERE {conditions} AND {cursor_condition}
            ORDER BY ts DESC, event_id DESC
            LIMIT {safe_limit + 1}
            """
        )
        next_cursor = None
        if len(rows) > safe_limit:
            cursor_row = rows[safe_limit]
            next_cursor = {
                "ts": _clickhouse_ts_to_iso(cursor_row.get("ts")),
                "event_id": _normalized_text(cursor_row.get("event_id")),
            }
            rows = rows[:safe_limit]
        items = list(reversed(_serialize_event_rows(rows)))
        return {"items": items, "next_cursor": next_cursor}

    def list_events(
        self,
        *,
        filters: dict[str, Any] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 200,
        cursor_ts: str = "",
        cursor_event_id: str = "",
    ) -> dict[str, Any]:
        self.ensure_schema()
        safe_limit = max(int(limit or 1), 1)
        conditions = _build_where_conditions(
            filters=filters,
            start_time=start_time,
            end_time=end_time,
        )
        cursor_condition = _build_event_cursor_condition(cursor_ts, cursor_event_id)
        rows = self._select_rows(
            f"""
            SELECT
                event_id,
                session_key,
                ts,
                runtime_node,
                component,
                node,
                status,
                event_type,
                trace_id,
                intent_id,
                request_id,
                internal_order_id,
                symbol,
                symbol_name,
                message,
                reason_code,
                payload_json,
                metrics_json,
                raw_file,
                raw_line,
                error_type,
                error_message
            FROM runtime_events
            WHERE {conditions} AND {cursor_condition}
            ORDER BY ts DESC, event_id DESC
            LIMIT {safe_limit + 1}
            """
        )
        next_cursor = None
        if len(rows) > safe_limit:
            cursor_row = rows[safe_limit]
            next_cursor = {
                "ts": _clickhouse_ts_to_iso(cursor_row.get("ts")),
                "event_id": _normalized_text(cursor_row.get("event_id")),
            }
            rows = rows[:safe_limit]
        return {"items": _serialize_event_rows(rows), "next_cursor": next_cursor}

    def _insert_json_each_row(self, table: str, rows: list[dict[str, Any]]) -> None:
        payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
        self._execute_command(f"INSERT INTO {table} FORMAT JSONEachRow", data=payload)

    def _execute_command(self, query: str, *, data: str | None = None) -> None:
        try:
            response = requests.post(
                self.base_url,
                params={"database": self.database, "query": query},
                data=(data.encode("utf-8") if isinstance(data, str) else data),
                auth=(self.username, self.password),
                timeout=self.timeout_s,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeObservabilityStoreError(_request_error_message(exc)) from exc

    def _select_rows(self, query: str) -> list[dict[str, Any]]:
        try:
            response = requests.post(
                self.base_url,
                params={"database": self.database, "query": f"{query} FORMAT JSON"},
                auth=(self.username, self.password),
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeObservabilityStoreError(_request_error_message(exc)) from exc
        return payload.get("data") if isinstance(payload.get("data"), list) else []


def _parse_datetime(raw: Any) -> datetime:
    text = _normalized_text(raw)
    if text:
        try:
            return datetime.fromisoformat(text).astimezone()
        except ValueError:
            pass
    return datetime.now().astimezone()


def _format_clickhouse_datetime(value: datetime) -> str:
    dt = value.astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _to_json_text(value: Any) -> str:
    try:
        return json.dumps(
            value if value is not None else {}, ensure_ascii=False, sort_keys=True
        )
    except TypeError:
        return "{}"


def _request_error_message(exc: Exception) -> str:
    message = str(exc)
    response = getattr(exc, "response", None)
    body = ""
    if response is not None:
        try:
            body = str(response.text or "").strip()
        except Exception:
            body = ""
    if body and body not in message:
        return f"{message}: {body}"
    return message


def _runtime_symbol_lookup_candidates(record: Any) -> list[dict[str, Any]]:
    if not isinstance(record, dict):
        return []
    candidates: list[dict[str, Any]] = [record]
    for nested in (
        record.get("payload"),
        record.get("signal_summary"),
        record.get("metrics"),
    ):
        if isinstance(nested, dict):
            candidates.append(nested)
    payload = record.get("payload")
    if isinstance(payload, dict):
        nested_signal_summary = payload.get("signal_summary")
        if isinstance(nested_signal_summary, dict):
            candidates.append(nested_signal_summary)
    return candidates


def resolve_runtime_symbol(record: Any) -> str:
    for candidate in _runtime_symbol_lookup_candidates(record):
        for field in _SYMBOL_FIELDS:
            value = _normalized_text(candidate.get(field))
            if not value:
                continue
            normalized = normalize_to_base_code(value)
            return normalized or value
    return ""


def resolve_runtime_symbol_name(record: Any, *, symbol: str = "") -> str:
    for candidate in _runtime_symbol_lookup_candidates(record):
        inline_name = _find_inline_symbol_name(candidate)
        if inline_name:
            return inline_name
    normalized_symbol = _normalized_text(symbol) or resolve_runtime_symbol(record)
    if not normalized_symbol:
        return ""
    return _lookup_symbol_name(normalized_symbol) or ""


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


def _sql_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _build_trace_summary_query(
    *,
    filters: dict[str, Any] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    trace_key: str = "",
) -> str:
    matched_filters = dict(filters or {})
    trace_kind_filter = _normalized_text(matched_filters.pop("trace_kind", ""))
    if trace_key:
        matched_filters["session_key"] = trace_key
    matched_conditions = _build_where_conditions(
        filters=matched_filters,
        start_time=start_time,
        end_time=end_time,
        include_session_key=True,
    )
    outer_conditions = _build_where_conditions(
        start_time=start_time,
        end_time=end_time,
        include_session_key=True,
    )
    having_clause = (
        f"\n    HAVING trace_kind = {_sql_string(trace_kind_filter)}"
        if trace_kind_filter
        else ""
    )
    return f"""
    SELECT
        session_key AS trace_key,
        anyIf(trace_id, trace_id != '') AS trace_id,
        multiIf(
            countIf(component = 'guardian_strategy') > 0, 'guardian_signal',
            countIf(component = 'xt_report_ingest') > 0, 'external_reported',
            countIf(component = 'order_reconcile') > 0, 'external_inferred',
            countIf(component = 'tpsl_worker' AND (reason_code = 'takeprofit' OR lowerUTF8(message) LIKE '%takeprofit%')) > 0, 'takeprofit',
            countIf(component = 'tpsl_worker' AND (reason_code = 'stoploss' OR lowerUTF8(message) LIKE '%stoploss%')) > 0, 'stoploss',
            countIf(component = 'order_submit') > 0, 'manual_api_order',
            'unknown'
        ) AS trace_kind,
        multiIf(
            countIf(lowerUTF8(status) IN ('failed', 'error')) > 0, 'failed',
            countIf(lowerUTF8(status) IN ('warning', 'skipped')) > 0, 'broken',
            countIf(lowerUTF8(status) = 'success') > 0, 'completed',
            'open'
        ) AS trace_status,
        argMaxIf(
            multiIf(
                error_type != '', concat(lowerUTF8(status), '@', component, '.', node, ':', error_type),
                reason_code != '', concat(lowerUTF8(status), '@', component, '.', node, ':', reason_code),
                message != '', concat(lowerUTF8(status), '@', component, '.', node, ':', substring(message, 1, 96)),
                concat(lowerUTF8(status), '@', component, '.', node)
            ),
            ts,
            is_issue = 1
        ) AS break_reason,
        min(ts) AS first_ts,
        max(ts) AS last_ts,
        dateDiff('millisecond', min(ts), max(ts)) AS duration_ms,
        argMin(component, ts) AS entry_component,
        argMin(node, ts) AS entry_node,
        argMax(component, ts) AS exit_component,
        argMax(node, ts) AS exit_node,
        count() AS step_count,
        countIf(is_issue = 1) AS issue_count,
        anyIf(symbol, symbol != '') AS symbol,
        anyIf(symbol_name, symbol_name != '') AS symbol_name,
        groupUniqArrayIf(intent_id, intent_id != '') AS intent_ids,
        groupUniqArrayIf(request_id, request_id != '') AS request_ids,
        groupUniqArrayIf(internal_order_id, internal_order_id != '') AS internal_order_ids,
        arraySort(groupUniqArrayIf(component, is_issue = 1)) AS affected_components
    FROM runtime_events
    WHERE session_key IN (
        SELECT DISTINCT session_key
        FROM runtime_events
        WHERE {matched_conditions}
    )
      AND {outer_conditions}
    GROUP BY session_key
    {having_clause}
    """


def _build_where_conditions(
    *,
    filters: dict[str, Any] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    include_session_key: bool = False,
) -> str:
    conditions = ["1 = 1"]
    if include_session_key:
        conditions.append("session_key != ''")
    for field, value in (filters or {}).items():
        normalized = _normalized_text(value)
        if not normalized:
            continue
        if field not in {
            "session_key",
            "trace_id",
            "intent_id",
            "request_id",
            "internal_order_id",
            "symbol",
            "component",
            "event_type",
            "runtime_node",
        }:
            continue
        conditions.append(f"{field} = {_sql_string(normalized)}")
    if start_time is not None:
        conditions.append(
            f"ts >= toDateTime64({_sql_string(_format_clickhouse_datetime(start_time))}, 3, 'Asia/Shanghai')"
        )
    if end_time is not None:
        conditions.append(
            f"ts <= toDateTime64({_sql_string(_format_clickhouse_datetime(end_time))}, 3, 'Asia/Shanghai')"
        )
    return " AND ".join(conditions)


def _build_event_cursor_condition(cursor_ts: str, cursor_event_id: str) -> str:
    normalized_ts = _normalized_text(cursor_ts)
    normalized_event_id = _normalized_text(cursor_event_id)
    if not normalized_ts:
        return "1 = 1"
    parsed = _parse_datetime(normalized_ts)
    formatted_ts = _format_clickhouse_datetime(parsed)
    if normalized_event_id:
        return (
            f"(ts < toDateTime64({_sql_string(formatted_ts)}, 3, 'Asia/Shanghai') "
            f"OR (ts = toDateTime64({_sql_string(formatted_ts)}, 3, 'Asia/Shanghai') "
            f"AND event_id < {_sql_string(normalized_event_id)}))"
        )
    return f"ts < toDateTime64({_sql_string(formatted_ts)}, 3, 'Asia/Shanghai')"


def _build_trace_cursor_condition(cursor_ts: str, cursor_trace_key: str) -> str:
    normalized_ts = _normalized_text(cursor_ts)
    normalized_trace_key = _normalized_text(cursor_trace_key)
    if not normalized_ts:
        return "1 = 1"
    parsed = _parse_datetime(normalized_ts)
    formatted_ts = _format_clickhouse_datetime(parsed)
    if normalized_trace_key:
        return (
            f"(last_ts < toDateTime64({_sql_string(formatted_ts)}, 3, 'Asia/Shanghai') "
            f"OR (last_ts = toDateTime64({_sql_string(formatted_ts)}, 3, 'Asia/Shanghai') "
            f"AND trace_key < {_sql_string(normalized_trace_key)}))"
        )
    return f"last_ts < toDateTime64({_sql_string(formatted_ts)}, 3, 'Asia/Shanghai')"


def _serialize_trace_summary_row(row: dict[str, Any]) -> dict[str, Any]:
    affected_components = row.get("affected_components")
    if not isinstance(affected_components, list):
        affected_components = []
    symbol = resolve_runtime_symbol(row)
    symbol_name = resolve_runtime_symbol_name(row, symbol=symbol)
    return {
        "trace_key": _normalized_text(row.get("trace_key")),
        "trace_id": _normalized_text(row.get("trace_id")),
        "trace_kind": _normalized_text(row.get("trace_kind")) or "unknown",
        "trace_status": _normalized_text(row.get("trace_status")) or "open",
        "break_reason": _normalized_text(row.get("break_reason")),
        "first_ts": _clickhouse_ts_to_iso(row.get("first_ts")),
        "last_ts": _clickhouse_ts_to_iso(row.get("last_ts")),
        "duration_ms": int(row.get("duration_ms") or 0),
        "entry_component": _normalized_text(row.get("entry_component")),
        "entry_node": _normalized_text(row.get("entry_node")),
        "exit_component": _normalized_text(row.get("exit_component")),
        "exit_node": _normalized_text(row.get("exit_node")),
        "step_count": int(row.get("step_count") or 0),
        "issue_count": int(row.get("issue_count") or 0),
        "symbol": symbol,
        "symbol_name": symbol_name,
        "intent_ids": list(row.get("intent_ids") or []),
        "request_ids": list(row.get("request_ids") or []),
        "internal_order_ids": list(row.get("internal_order_ids") or []),
        "affected_components": [
            _normalized_text(item)
            for item in affected_components
            if _normalized_text(item)
        ],
    }


def _serialize_event_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_serialize_event_row(row) for row in rows]


def _serialize_event_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = _decode_json_text(row.get("payload_json"))
    metrics = _decode_json_text(row.get("metrics_json"))
    record = {
        **row,
        "payload": payload,
        "metrics": metrics,
    }
    symbol = resolve_runtime_symbol(record)
    symbol_name = resolve_runtime_symbol_name(record, symbol=symbol)
    return {
        "event_id": _normalized_text(row.get("event_id")),
        "session_key": _normalized_text(row.get("session_key")),
        "ts": _clickhouse_ts_to_iso(row.get("ts")),
        "runtime_node": _normalized_text(row.get("runtime_node")),
        "component": _normalized_text(row.get("component")),
        "node": _normalized_text(row.get("node")),
        "status": _normalized_text(row.get("status")) or "info",
        "event_type": _normalized_text(row.get("event_type")) or "trace_step",
        "trace_id": _normalized_text(row.get("trace_id")),
        "intent_id": _normalized_text(row.get("intent_id")),
        "request_id": _normalized_text(row.get("request_id")),
        "internal_order_id": _normalized_text(row.get("internal_order_id")),
        "symbol": symbol,
        "symbol_name": symbol_name,
        "message": _normalized_text(row.get("message")),
        "reason_code": _normalized_text(row.get("reason_code")),
        "payload": payload,
        "metrics": metrics,
        "raw_file": _normalized_text(row.get("raw_file")),
        "raw_line": int(row.get("raw_line") or 0),
        "error_type": _normalized_text(row.get("error_type")),
        "error_message": _normalized_text(row.get("error_message")),
    }


def _decode_json_text(raw: Any) -> dict[str, Any]:
    text = _normalized_text(raw)
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _clickhouse_ts_to_iso(raw: Any) -> str:
    dt = _clickhouse_ts_to_datetime(raw)
    return dt.isoformat() if dt is not None else ""


def _clickhouse_ts_to_datetime(raw: Any) -> datetime | None:
    text = _normalized_text(raw)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=_CLICKHOUSE_TIMEZONE)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text).astimezone(_CLICKHOUSE_TIMEZONE)
    except ValueError:
        return None


__all__ = [
    "RuntimeObservabilityClickHouseStore",
    "RuntimeObservabilityStoreError",
    "build_clickhouse_event_row",
]

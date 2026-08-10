"""运维控制台后端（S1+S2）：只读聚合端点。

- ``GET /api/ops/overview``：KPI + 依赖服务 + 账本摘要 + 最近异常摘要（服务端 5s 缓存）。
- ``GET /api/ops/kline-health``：数据链健康（producer / consumer / K 线 API 探针）。

全页面只读：本模块不包含任何写操作入口，任何数据源不可用时对应卡片显式降级，
不把缺失当健康，也不阻塞其他卡片。
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pymongo
import redis
import requests  # type: ignore[import-untyped]
from flask import Blueprint, jsonify

from freshquant.bootstrap_config import bootstrap_config
from freshquant.database.mongodb import DBfreshquant, DBOrderManagement
from freshquant.rear.runtime.routes import get_runtime_query_service
from freshquant.runtime_constants import TZ
from freshquant.runtime_observability.clickhouse_store import (
    RuntimeObservabilityStoreError,
)
from freshquant.util.period import (
    get_redis_cache_key,
    is_supported_realtime_period,
    to_backend_period,
)

logger = logging.getLogger(__name__)

ops_bp = Blueprint("ops", __name__, url_prefix="/api/ops")

# ---- 常量 ----
OVERVIEW_CACHE_TTL_S = 5.0
KLINE_PROBE_MIN_INTERVAL_S = 60.0
KLINE_503_WINDOW_S = 300.0
KLINE_PROBE_SYMBOL = "sz000001"
KLINE_PROBE_PERIOD = "5m"
HOST_SNAPSHOT_FILE = os.environ.get(
    "FQ_OPS_SNAPSHOT_FILE", "/freshquant/ops-snapshot/host-runtime.json"
)
HOST_SNAPSHOT_MAX_AGE_S = 900.0  # 5 分钟快照间隔，容忍 3 个周期

IN_FLIGHT_ORDER_STATES = frozenset(
    {
        "ACCEPTED",
        "QUEUED",
        "SUBMITTING",
        "SUBMITTED",
        "PARTIAL_FILLED",
        "BROKER_BYPASSED",
        "INFERRED_PENDING",
    }
)
TERMINAL_GAP_STATES = frozenset({"RESOLVED", "CLOSED"})
ISSUE_STATUSES = frozenset({"warning", "failed", "error", "skipped"})
ISSUE_CURRENT_WINDOW_S = 24 * 3600  # "最近异常"当前窗口：近 24h
GUARDIAN_STRATEGY_COMPONENT = "guardian_strategy"
SKIPPED_EXEMPT_COMPONENTS = frozenset({GUARDIAN_STRATEGY_COMPONENT})
TICK_QUEUE_BACKLOG_THRESHOLD = 10000
TRADING_SESSIONS = frozenset({"auction", "morning", "afternoon"})

KLINE_FRESHNESS_RED_S = 120.0
KLINE_FRESHNESS_YELLOW_S = 60.0
ACCOUNT_SYNC_YELLOW_S = 180.0
HEARTBEAT_YELLOW_S = 300.0

_PROBE_TIMEOUT_S = 2.5

# ---- 服务端 5s 缓存（overview） ----
_overview_cache: dict[str, Any] = {"at": 0.0, "payload": None}

# ---- K 线读取探针状态（低频 ≤1 次/分钟 + 近 5 分钟 503 计数窗口） ----
_probe_state: dict[str, Any] = {
    "last_run_at": 0.0,
    "last_result": None,
    "window": deque(),
}


def _now() -> datetime:
    return datetime.now(TZ)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _component_by_name(
    components: list[dict[str, Any]], name: str
) -> dict[str, Any] | None:
    for item in components or []:
        if str(item.get("component") or "") == name:
            return item
    return None


def _metrics(item: dict[str, Any] | None) -> dict[str, Any]:
    if not item:
        return {}
    metrics = item.get("metrics") or {}
    return metrics if isinstance(metrics, dict) else {}


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _degraded(label: str, reason: str) -> dict[str, Any]:
    return {
        "label": label,
        "ok": None,
        "status": "degraded",
        "tone": "degraded",
        "summary": "数据源不可用",
        "detail": reason,
        "source": None,
    }


def _placeholder(label: str, summary: str, detail: str) -> dict[str, Any]:
    return {
        "label": label,
        "ok": None,
        "status": "placeholder",
        "tone": "placeholder",
        "summary": summary,
        "detail": detail,
        "source": "S3",
    }


# ---- 宿主机只读快照（S3：宿主侧采集 -> JSON 快照 -> apiserver ro 挂载） ----


def _load_host_snapshot() -> dict[str, Any] | None:
    """只读加载宿主机快照 JSON；文件缺失/损坏/过期返回 None（降级）。"""
    try:
        path = Path(HOST_SNAPSHOT_FILE)
        if not path.exists():
            return None
        age_s = time.time() - path.stat().st_mtime
        if age_s > HOST_SNAPSHOT_MAX_AGE_S:
            logger.warning("ops host snapshot stale: age=%ss", round(age_s, 1))
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        payload["_age_s"] = round(age_s, 1)
        return payload
    except Exception as exc:
        logger.warning("ops host snapshot read failed: %s", exc)
        return None


def _build_supervisor_kpi(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    label = "Supervisor 进程"
    if snapshot is None:
        return _degraded(label, "宿主快照不可用（缺失/过期/读取失败）")
    supervisor = snapshot.get("supervisor") or {}
    if not supervisor.get("ok"):
        return _degraded(label, f"Supervisor 数据源不可用（{supervisor.get('error')}）")
    running = _to_int(supervisor.get("running_count"))
    expected = _to_int(supervisor.get("expected_count"), 9)
    programs = supervisor.get("programs") or []
    degraded = [
        program
        for program in programs
        if str(program.get("state") or "").upper() != "RUNNING"
    ]
    if degraded:
        status, tone, summary = "error", "error", f"Running {running}/{expected}"
    else:
        status, tone, summary = "ok", "ok", f"Running {running}/{expected}"
    detail = (
        f"异常 {len(degraded)} 个："
        + ", ".join(f"{item.get('name')}[{item.get('state')}]" for item in degraded[:3])
        if degraded
        else "全部正常"
    )
    return {
        "label": label,
        "ok": not degraded,
        "status": status,
        "tone": tone,
        "summary": summary,
        "detail": detail,
        "source": "host_snapshot",
    }


def _build_docker_kpi(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    label = "Docker 容器"
    if snapshot is None:
        return _degraded(label, "宿主快照不可用（缺失/过期/读取失败）")
    docker = snapshot.get("docker") or {}
    if not docker.get("ok"):
        return _degraded(label, f"Docker 数据源不可用（{docker.get('error')}）")
    running = _to_int(docker.get("running_count"))
    expected = _to_int(docker.get("expected_count"), 10)
    containers = docker.get("containers") or []
    degraded = [
        container
        for container in containers
        if str(container.get("state") or "").lower() != "running"
    ]
    if degraded:
        status, tone, summary = "error", "error", f"Up {running}/{expected}"
    else:
        status, tone, summary = "ok", "ok", f"Up {running}/{expected}"
    detail = (
        f"异常 {len(degraded)} 个："
        + ", ".join(f"{item.get('name')}[{item.get('state')}]" for item in degraded[:3])
        if degraded
        else "全部正常"
    )
    return {
        "label": label,
        "ok": not degraded,
        "status": status,
        "tone": tone,
        "summary": summary,
        "detail": detail,
        "source": "host_snapshot",
    }


def _build_host_payload(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """宿主机分层区明细：supervisor 程序表 + docker 容器表（含降级原因）。"""
    if snapshot is None:
        return {
            "available": False,
            "reason": "宿主快照不可用（缺失/过期/读取失败）",
            "captured_at": None,
            "supervisor": {"ok": False, "error": None, "programs": []},
            "docker": {"ok": False, "error": None, "containers": []},
        }
    supervisor = snapshot.get("supervisor") or {}
    docker = snapshot.get("docker") or {}
    return {
        "available": True,
        "reason": None,
        "captured_at": snapshot.get("captured_at"),
        "snapshot_age_s": snapshot.get("_age_s"),
        "expected": snapshot.get("expected") or {},
        "supervisor": {
            "ok": bool(supervisor.get("ok")),
            "error": supervisor.get("error"),
            "running_count": _to_int(supervisor.get("running_count")),
            "expected_count": _to_int(supervisor.get("expected_count"), 9),
            "programs": supervisor.get("programs") or [],
        },
        "docker": {
            "ok": bool(docker.get("ok")),
            "error": docker.get("error"),
            "compose_project": docker.get("compose_project"),
            "running_count": _to_int(docker.get("running_count")),
            "expected_count": _to_int(docker.get("expected_count"), 10),
            "containers": docker.get("containers") or [],
        },
    }


# ---- 交易日历 / 交易时段 ----


def _load_trade_dates() -> tuple[set[str] | None, str]:
    """只读交易日历（Mongo 缓存 -> 文件快照），绝不触发网络刷新。"""
    from freshquant.data.trade_calendar_cache import (
        STATUS_FILE_SNAPSHOT,
        STATUS_MONGO_CACHE,
        read_trade_calendar_cache,
        read_trade_calendar_snapshot,
    )

    try:
        frame = read_trade_calendar_cache(require_covering_today=False)
    except Exception as exc:  # pragma: no cover - 防御降级
        logger.warning("ops trade calendar mongo cache read failed: %s", exc)
        frame = None
    if frame is not None:
        return _frame_trade_date_set(frame), STATUS_MONGO_CACHE
    try:
        frame = read_trade_calendar_snapshot(require_covering_today=False)
    except Exception as exc:  # pragma: no cover - 防御降级
        logger.warning("ops trade calendar snapshot read failed: %s", exc)
        frame = None
    if frame is not None:
        return _frame_trade_date_set(frame), STATUS_FILE_SNAPSHOT
    return None, "unavailable"


def _frame_trade_date_set(frame: Any) -> set[str]:
    values = frame.get("trade_date")
    if values is None:
        return set()
    return {str(value).strip()[:10] for value in values if str(value).strip()}


def _compute_trade_session(
    now: datetime, trade_dates: set[str] | None
) -> dict[str, Any]:
    if trade_dates is None:
        return {
            "is_trade_day": None,
            "session": "unknown",
            "label": "时段未知",
            "calendar_status": "unavailable",
        }
    today = now.strftime("%Y-%m-%d")
    if today not in trade_dates:
        return {
            "is_trade_day": False,
            "session": "non_trade_day",
            "label": "非交易日",
            "calendar_status": "available",
        }
    hhmm = now.strftime("%H:%M")
    if "09:15" <= hhmm < "09:25":
        session, label = "auction", "竞价"
    elif "09:30" <= hhmm < "11:30":
        session, label = "morning", "盘中"
    elif "11:30" <= hhmm < "13:00":
        session, label = "noon_break", "午休"
    elif "13:00" <= hhmm < "15:00":
        session, label = "afternoon", "盘中"
    elif hhmm >= "15:05":
        session, label = "post_close", "盘后"
    else:
        session, label = "pre_open", "盘前"
    return {
        "is_trade_day": True,
        "session": session,
        "label": label,
        "calendar_status": "available",
    }


def _resolve_trade_session() -> dict[str, Any]:
    trade_dates, status = _load_trade_dates()
    session = _compute_trade_session(_now(), trade_dates)
    session["calendar_status"] = status if trade_dates is None else "available"
    return session


# ---- 依赖服务探针 ----


def _mongo_ping() -> tuple[bool, float | None, str | None]:
    client: pymongo.MongoClient = pymongo.MongoClient(
        host=bootstrap_config.mongodb.host,
        port=bootstrap_config.mongodb.port,
        serverSelectionTimeoutMS=2000,
        connectTimeoutMS=2000,
        socketTimeoutMS=2000,
        tz_aware=True,
        tzinfo=TZ,
    )
    try:
        started = time.monotonic()
        client.admin.command("ping")
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        return True, latency_ms, None
    except Exception as exc:
        return False, None, f"mongo ping 失败: {exc}"
    finally:
        client.close()


def _redis_ping() -> tuple[bool, float | None, str | None]:
    client = redis.StrictRedis(
        host=bootstrap_config.redis.host,
        port=bootstrap_config.redis.port,
        db=bootstrap_config.redis.db,
        password=bootstrap_config.redis.password or None,
        socket_timeout=2.0,
        socket_connect_timeout=2.0,
        decode_responses=True,
    )
    try:
        started = time.monotonic()
        ok = bool(client.ping())
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        return ok, latency_ms, None
    except Exception as exc:
        return False, None, f"redis ping 失败: {exc}"


def _clickhouse_ping() -> tuple[bool, float | None, str | None]:
    service = get_runtime_query_service()
    url = f"{service.base_url}/ping"
    try:
        started = time.monotonic()
        response = requests.get(url, timeout=_PROBE_TIMEOUT_S)
        ok = response.status_code == 200
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        if ok:
            return True, latency_ms, None
        return False, latency_ms, f"clickhouse ping HTTP {response.status_code}"
    except Exception as exc:
        return False, None, f"clickhouse ping 失败: {exc}"


def _resolve_tdxhq_endpoint() -> str:
    """解析 TDXHQ 端点：收敛单键 FRESHQUANT_TDX__HQ_ENDPOINT（与 compose env 一致）。

    旧键 FRESHQUANT_TDX__HQ__ENDPOINT 命中时告警（过渡兼容，不再作为首选）。
    """
    primary = os.environ.get("FRESHQUANT_TDX__HQ_ENDPOINT")
    if primary and str(primary).strip():
        return str(primary).strip()
    legacy = os.environ.get("FRESHQUANT_TDX__HQ__ENDPOINT")
    if legacy and str(legacy).strip():
        logger.warning(
            "TDXHQ legacy env key FRESHQUANT_TDX__HQ__ENDPOINT is set; "
            "converge to FRESHQUANT_TDX__HQ_ENDPOINT"
        )
        return str(legacy).strip()
    endpoint = str(bootstrap_config.tdx.hq_endpoint or "").strip()
    return endpoint or "http://127.0.0.1:15001"


def _tdxhq_ping() -> tuple[bool, float | None, str | None]:
    endpoint = _resolve_tdxhq_endpoint()
    parsed = urlparse(endpoint if "://" in endpoint else f"//{endpoint}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        started = time.monotonic()
        with socket.create_connection((host, port), timeout=_PROBE_TIMEOUT_S):
            pass
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        return True, latency_ms, None
    except Exception as exc:
        return False, None, f"tdxhq TCP 探测失败: {exc}"


def _probe_dependencies() -> dict[str, Any]:
    probes = {
        "mongo": _mongo_ping,
        "redis": _redis_ping,
        "clickhouse": _clickhouse_ping,
        "tdxhq": _tdxhq_ping,
        "tick_queue": _tick_queue_depth_probe,
    }
    result: dict[str, Any] = {}
    for name, probe in probes.items():
        ok, latency_ms, error = probe()
        entry: dict[str, Any] = {
            "ok": bool(ok),
            "latency_ms": latency_ms,
            "error": error,
        }
        if name == "tick_queue":
            entry["depth"] = latency_ms
            entry.pop("latency_ms", None)
        result[name] = entry
    return result


def _tick_queue_depth_probe() -> tuple[bool, int | None, str | None]:
    """tick 队列积压探针：REDIS_TICK_QUEUE_PREFIX 各 shard 长度求和 + 阈值告警。

    tpsl 停摆时 tick 队列会无限膨胀（consumer 的 backlog_sum 是 K 线队列，
    不覆盖 tick 队列），此探针用于早期发现止盈止损链静默停摆。
    """
    try:
        from freshquant.market_data.xtdata.constants import (
            REDIS_QUEUE_SHARDS,
            REDIS_TICK_QUEUE_PREFIX,
        )
    except Exception as exc:
        return False, None, f"tick queue probe unavailable: {exc}"
    try:
        probe_redis = redis.Redis(
            host=bootstrap_config.redis.host,
            port=bootstrap_config.redis.port,
            db=bootstrap_config.redis.db,
            password=(bootstrap_config.redis.password or None),
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
            decode_responses=True,
        )
        depth = 0
        for index in range(int(REDIS_QUEUE_SHARDS)):
            depth += int(probe_redis.llen(f"{REDIS_TICK_QUEUE_PREFIX}:{index}") or 0)
        if depth > TICK_QUEUE_BACKLOG_THRESHOLD:
            return (
                False,
                depth,
                f"tick queue backlog {depth} > {TICK_QUEUE_BACKLOG_THRESHOLD}",
            )
        return True, depth, None
    except Exception as exc:
        return False, None, f"tick queue probe failed: {exc}"


# ---- KPI 构建 ----


def _build_xtdata_connection(item: dict[str, Any] | None) -> dict[str, Any]:
    label = "XTData 连接"
    if item is None:
        return _degraded(label, "health/summary 缺少 xt_producer")
    metrics = _metrics(item)
    connected = _to_int(metrics.get("connected"), -1)
    retry_count = _to_int(metrics.get("retry_count"))
    ok = connected == 1
    return {
        "label": label,
        "ok": ok,
        "status": "ok" if ok else "error",
        "tone": "ok" if ok else "error",
        "summary": "connected" if ok else "disconnected",
        "detail": f"retry_count={retry_count}",
        "source": "health_summary",
    }


def _build_kline_freshness(
    item: dict[str, Any] | None, session: dict[str, Any]
) -> dict[str, Any]:
    label = "K 线新鲜度"
    if item is None:
        return _degraded(label, "health/summary 缺少 xt_consumer")
    metrics = _metrics(item)
    last_bar_age_s = _to_float(metrics.get("last_bar_age_s"))
    catchup = _to_int(metrics.get("catchup_mode"))
    backlog = _to_int(metrics.get("backlog_sum"))
    in_trading = session.get("session") in TRADING_SESSIONS
    if last_bar_age_s is None:
        status, tone, summary = "unknown", "unknown", "无数据"
    elif in_trading and last_bar_age_s > KLINE_FRESHNESS_RED_S:
        status, tone, summary = "error", "error", f"{last_bar_age_s:g}s"
    elif in_trading and last_bar_age_s > KLINE_FRESHNESS_YELLOW_S:
        status, tone, summary = "warn", "warn", f"{last_bar_age_s:g}s"
    elif not in_trading and last_bar_age_s > KLINE_FRESHNESS_RED_S * 2:
        status, tone, summary = "warn", "warn", f"{last_bar_age_s:g}s"
    else:
        status, tone, summary = "ok", "ok", f"{last_bar_age_s:g}s"
    return {
        "label": label,
        "ok": status == "ok",
        "status": status,
        "tone": tone,
        "summary": summary,
        "detail": f"catchup={catchup} backlog={backlog}",
        "source": "health_summary",
    }


def _build_account_sync(last_seen_epoch: Any) -> dict[str, Any]:
    label = "账户同步新鲜度"
    age = None
    if last_seen_epoch is not None:
        try:
            age = max(0.0, time.time() - float(last_seen_epoch))
        except (TypeError, ValueError):
            age = None
    if age is None:
        return {
            "label": label,
            "ok": None,
            "status": "unknown",
            "tone": "unknown",
            "summary": "无数据",
            "detail": "xt_positions 无 sync_last_seen_at",
            "source": "mongo",
        }
    status, tone = ("warn", "warn") if age > ACCOUNT_SYNC_YELLOW_S else ("ok", "ok")
    return {
        "label": label,
        "ok": status == "ok",
        "status": status,
        "tone": tone,
        "summary": f"{age:g}s",
        "detail": f"sync_last_seen_at={float(last_seen_epoch):g}",
        "source": "mongo",
    }


def _build_guardian_heartbeat(item: dict[str, Any] | None) -> dict[str, Any]:
    label = "Guardian 心跳"
    if item is None:
        return _degraded(label, "health/summary 缺少 guardian_strategy")
    heartbeat_age_s = _to_float(item.get("heartbeat_age_s"))
    issue_step_count = _to_int(item.get("issue_step_count"))
    issue_trace_count = _to_int(item.get("issue_trace_count"))
    if heartbeat_age_s is None:
        status, tone, summary = "unknown", "unknown", "无心跳"
    elif heartbeat_age_s > HEARTBEAT_YELLOW_S:
        status, tone, summary = "warn", "warn", f"{heartbeat_age_s:g}s"
    else:
        status, tone, summary = "ok", "ok", f"{heartbeat_age_s:g}s"
    return {
        "label": label,
        "ok": status == "ok",
        "status": status,
        "tone": tone,
        "summary": summary,
        "detail": f"issue_step={issue_step_count} trace={issue_trace_count}",
        "source": "health_summary",
    }


def _build_broker_connection(item: dict[str, Any] | None) -> dict[str, Any]:
    label = "Broker 连接"
    if item is None:
        return _degraded(label, "health/summary 缺少 broker_gateway")
    metrics = _metrics(item)
    connected = _to_int(metrics.get("connected"), -1)
    retry_count = _to_int(metrics.get("retry_count"))
    ok = connected == 1
    return {
        "label": label,
        "ok": ok,
        "status": "ok" if ok else "error",
        "tone": "ok" if ok else "error",
        "summary": "connected" if ok else "disconnected",
        "detail": f"retry_count={retry_count}",
        "source": "health_summary",
    }


def _build_ledger_consistency(
    gaps: int, in_flight_orders: int, in_flight_broker_orders: int
) -> dict[str, Any]:
    label = "账本一致性"
    total_in_flight = in_flight_orders + in_flight_broker_orders
    status, tone = (
        ("ok", "ok") if gaps == 0 and total_in_flight == 0 else ("warn", "warn")
    )
    return {
        "label": label,
        "ok": status == "ok",
        "status": status,
        "tone": tone,
        "summary": "一致" if status == "ok" else f"{gaps} 异常",
        "detail": f"gaps={gaps} in_flight={total_in_flight}",
        "source": "mongo",
    }


def _query_ledger_counts() -> dict[str, Any]:
    gaps = DBOrderManagement["om_reconciliation_gaps"].count_documents(
        {"state": {"$nin": list(TERMINAL_GAP_STATES)}}
    )
    in_flight_query = {"state": {"$in": list(IN_FLIGHT_ORDER_STATES)}}
    in_flight_orders = DBOrderManagement["om_orders"].count_documents(in_flight_query)
    in_flight_broker_orders = DBOrderManagement["om_broker_orders"].count_documents(
        in_flight_query
    )
    return {
        "gaps": _to_int(gaps),
        "in_flight_orders": _to_int(in_flight_orders),
        "in_flight_broker_orders": _to_int(in_flight_broker_orders),
    }


def _query_account_sync_age() -> Any:
    doc = DBfreshquant["xt_positions"].find_one(
        {},
        projection={"sync_last_seen_at": 1},
        sort=[("sync_last_seen_at", -1)],
    )
    return None if doc is None else doc.get("sync_last_seen_at")


def _build_issue_aggregate(components: list[dict[str, Any]]) -> dict[str, Any]:
    issue_components = []
    issue_trace_count = 0
    issue_step_count = 0
    last_issue_ts: str | None = None
    window_seconds = ISSUE_CURRENT_WINDOW_S
    recent_components: set[str] = set()
    recent_trace_count = 0
    recent_step_count = 0
    for item in components or []:
        status = str(item.get("status") or "").lower()
        component = str(item.get("component") or "")
        trace_count = _to_int(item.get("issue_trace_count"))
        step_count = _to_int(item.get("issue_step_count"))
        issue_ts = item.get("last_issue_ts")
        # P4-B：guardian_strategy 的 skipped 是"非策略机设计性跳过"，不计异常。
        skipped_exempt = status == "skipped" and component in SKIPPED_EXEMPT_COMPONENTS
        if status in ISSUE_STATUSES and not skipped_exempt:
            issue_components.append(
                {
                    "component": component,
                    "status": status,
                    "issue_trace_count": trace_count,
                    "issue_step_count": step_count,
                    "last_issue_ts": issue_ts,
                }
            )
        if skipped_exempt:
            continue
        issue_trace_count += trace_count
        issue_step_count += step_count
        if issue_ts and (last_issue_ts is None or str(issue_ts) > last_issue_ts):
            last_issue_ts = str(issue_ts)
        if _issue_ts_within_window(issue_ts, window_seconds=window_seconds):
            recent_components.add(component)
            recent_trace_count += trace_count
            recent_step_count += step_count
    issue_components.sort(key=lambda item: item["last_issue_ts"] or "", reverse=True)
    return {
        "component_issue_count": len(issue_components),
        "issue_trace_count": issue_trace_count,
        "issue_step_count": issue_step_count,
        "last_issue_ts": last_issue_ts,
        "components": issue_components,
        # P4-B：current(24h)/historical 分离——前端"最近异常"用 recent_*，
        # 历史累计保留在 issue_* 上（不破坏累计语义）。
        "window_seconds": window_seconds,
        "recent_component_count": len(recent_components),
        "recent_issue_trace_count": recent_trace_count,
        "recent_issue_step_count": recent_step_count,
        "recent_components": sorted(recent_components),
    }


def _issue_ts_within_window(value: Any, *, window_seconds: int) -> bool:
    """判断 issue 时间戳是否落在当前窗口内（兼容 ISO8601 / epoch 秒 / 毫秒）。"""
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return (time.time() - ts) <= window_seconds
    text = str(value or "").strip()
    if not text:
        return False
    try:
        dt = datetime.fromisoformat(text)
        return (time.time() - dt.timestamp()) <= window_seconds
    except ValueError:
        pass
    try:
        ts = float(text)
        if ts > 1e12:
            ts /= 1000.0
        return (time.time() - ts) <= window_seconds
    except ValueError:
        return False


def _build_overview() -> dict[str, Any]:
    session = _resolve_trade_session()
    components: list[dict[str, Any]] = []
    health_error: str | None = None
    try:
        summary = get_runtime_query_service().get_health_summary(
            start_time=None, end_time=None
        )
        components = summary.get("components") or []
    except RuntimeObservabilityStoreError as exc:
        health_error = f"ClickHouse 数据源不可用（{exc}）"
        logger.warning("ops overview health summary failed: %s", exc)
    except Exception as exc:  # pragma: no cover - 防御降级
        health_error = f"ClickHouse 数据源不可用（{exc}）"
        logger.warning("ops overview health summary failed: %s", exc)

    host_snapshot = _load_host_snapshot()
    kpi_items: dict[str, Any] = {
        "supervisor": _build_supervisor_kpi(host_snapshot),
        "docker_containers": _build_docker_kpi(host_snapshot),
    }
    if health_error is None:
        kpi_items["xtdata_connection"] = _build_xtdata_connection(
            _component_by_name(components, "xt_producer")
        )
        kpi_items["kline_freshness"] = _build_kline_freshness(
            _component_by_name(components, "xt_consumer"), session
        )
        kpi_items["guardian_heartbeat"] = _build_guardian_heartbeat(
            _component_by_name(components, "guardian_strategy")
        )
        kpi_items["broker_connection"] = _build_broker_connection(
            _component_by_name(components, "broker_gateway")
        )
        issue_aggregate = _build_issue_aggregate(components)
    else:
        for key, label in (
            ("xtdata_connection", "XTData 连接"),
            ("kline_freshness", "K 线新鲜度"),
            ("guardian_heartbeat", "Guardian 心跳"),
            ("broker_connection", "Broker 连接"),
        ):
            kpi_items[key] = _degraded(label, health_error)
        issue_aggregate = {
            "component_issue_count": 0,
            "issue_trace_count": 0,
            "issue_step_count": 0,
            "last_issue_ts": None,
            "components": [],
            "window_seconds": ISSUE_CURRENT_WINDOW_S,
            "recent_component_count": 0,
            "recent_issue_trace_count": 0,
            "recent_issue_step_count": 0,
            "recent_components": [],
            "degraded_reason": health_error,
        }

    mongo_error: str | None = None
    account_sync: dict[str, Any]
    ledger: dict[str, Any]
    try:
        account_sync = _build_account_sync(_query_account_sync_age())
        ledger_counts = _query_ledger_counts()
        ledger = _build_ledger_consistency(
            ledger_counts["gaps"],
            ledger_counts["in_flight_orders"],
            ledger_counts["in_flight_broker_orders"],
        )
    except Exception as exc:
        mongo_error = f"Mongo 数据源不可用（{exc}）"
        logger.warning("ops overview mongo read failed: %s", exc)
        account_sync = _degraded("账户同步新鲜度", mongo_error)
        ledger = _degraded("账本一致性", mongo_error)
    kpi_items["account_sync"] = account_sync
    kpi_items["ledger_consistency"] = ledger

    dependencies = _probe_dependencies()
    degraded_count = sum(
        1 for kpi in kpi_items.values() if kpi.get("status") in {"degraded", "error"}
    )
    return {
        "generated_at": _iso(_now()),
        "trade_session": session,
        "kpis": kpi_items,
        "dependencies": dependencies,
        "issues": issue_aggregate,
        "host": _build_host_payload(host_snapshot),
        "summary": {
            "degraded_count": degraded_count,
            "total_kpis": len(kpi_items),
            "health_source": "degraded" if health_error else "ok",
            "mongo_source": "degraded" if mongo_error else "ok",
        },
    }


def _overview_with_cache() -> tuple[dict[str, Any], bool]:
    now = time.monotonic()
    cached_payload = _overview_cache.get("payload")
    if (
        cached_payload is not None
        and now - _overview_cache.get("at", 0.0) < OVERVIEW_CACHE_TTL_S
    ):
        return cached_payload, True
    payload = _build_overview()
    _overview_cache["at"] = now
    _overview_cache["payload"] = payload
    return payload, False


@ops_bp.get("/overview")
def ops_overview():
    payload, cached = _overview_with_cache()
    payload = dict(payload)
    payload["cache"] = {"ttl_s": OVERVIEW_CACHE_TTL_S, "cached": cached}
    return jsonify(payload)


@ops_bp.get("/host-runtime")
def ops_host_runtime():
    """宿主机只读运行面明细（Supervisor 程序表 + Docker 容器表）。"""
    snapshot = _load_host_snapshot()
    return jsonify(_build_host_payload(snapshot))


# ---- K 线读取探针（S2） ----


def _read_realtime_cache_sample() -> dict[str, Any]:
    """读取样例标的的 realtimeCache，返回成功/无数据/失败三种结果之一。"""
    from freshquant.database.redis import redis_db as probe_redis

    period_backend = to_backend_period(KLINE_PROBE_PERIOD)
    if not is_supported_realtime_period(period_backend):
        return {"status": "error", "realtime_cache": False, "detail": "非法周期配置"}
    prefix = f"CACHE:KLINE:{KLINE_PROBE_SYMBOL}:{period_backend}:"
    try:
        found_key = next(
            iter(probe_redis.scan_iter(match=f"{prefix}*", count=100)), None
        )
    except Exception as exc:
        return {
            "status": "error",
            "realtime_cache": False,
            "detail": f"Redis 不可用（{exc}）",
        }
    if not found_key:
        return {
            "status": "no_data",
            "realtime_cache": True,
            "detail": "realtimeCache 尚无缓存（K 线消费未写入）",
        }
    try:
        raw = probe_redis.get(found_key)
    except Exception as exc:
        return {
            "status": "error",
            "realtime_cache": False,
            "detail": f"Redis 读取失败（{exc}）",
        }
    if not raw:
        return {
            "status": "no_data",
            "realtime_cache": True,
            "detail": "realtimeCache 缓存已过期",
        }
    try:
        raw_text = raw if isinstance(raw, str) else ""
        payload = json.loads(raw_text)
    except (TypeError, ValueError) as exc:
        return {
            "status": "error",
            "realtime_cache": True,
            "detail": f"realtimeCache payload 解析失败（{exc}）",
        }
    dates = payload.get("date") if isinstance(payload, dict) else None
    has_bars = isinstance(dates, list) and len(dates) > 0
    return {
        "status": "success" if has_bars else "no_data",
        "realtime_cache": True,
        "detail": (
            f"realtimeCache 命中 {len(dates) if isinstance(dates, list) else 0} 根 K 线"
            if has_bars
            else "realtimeCache 存在但无 K 线数据"
        ),
    }


def _execute_kline_probe(now_ts: float) -> dict[str, Any]:
    try:
        result = _read_realtime_cache_sample()
    except Exception as exc:  # pragma: no cover - 防御降级
        result = {
            "status": "error",
            "realtime_cache": False,
            "detail": f"K 线读取探针异常（{exc}）",
        }
    result["checked_at"] = datetime.fromtimestamp(now_ts, tz=TZ).isoformat()
    return result


def _prune_probe_window(now_ts: float) -> None:
    cutoff = now_ts - KLINE_503_WINDOW_S
    window = _probe_state["window"]
    while window and window[0][0] < cutoff:
        window.popleft()


def _kline_probe_if_due(now_ts: float | None = None) -> dict[str, Any]:
    current_ts = float(now_ts if now_ts is not None else time.time())
    last_result = _probe_state.get("last_result")
    if (
        last_result is not None
        and current_ts - _probe_state.get("last_run_at", 0.0)
        < KLINE_PROBE_MIN_INTERVAL_S
    ):
        return last_result
    result = _execute_kline_probe(current_ts)
    _probe_state["last_run_at"] = current_ts
    _probe_state["last_result"] = result
    _probe_state["window"].append((current_ts, result["status"]))
    _prune_probe_window(current_ts)
    return result


def _build_kline_segments(
    producer_item: dict[str, Any] | None,
    consumer_item: dict[str, Any] | None,
    session: dict[str, Any],
) -> dict[str, Any]:
    in_trading = session.get("session") in TRADING_SESSIONS
    segments: dict[str, Any] = {}

    # producer
    if producer_item is None:
        segments["producer"] = {
            "label": "producer",
            "status": "degraded",
            "tone": "degraded",
            "summary": "无数据",
            "detail": "health/summary 缺少 xt_producer",
            "log_component": "xt_producer",
            "last_issue_ts": None,
        }
    else:
        metrics = _metrics(producer_item)
        connected = _to_int(metrics.get("connected"), -1)
        rx_age_s = _to_float(metrics.get("rx_age_s"))
        subscribed_codes = _to_int(metrics.get("subscribed_codes"))
        tick_batches_5m = _to_int(metrics.get("tick_batches_5m"))
        dropped = _to_int(metrics.get("tick_quote_dropped_batches"))
        if connected != 1 or (rx_age_s is not None and rx_age_s > 300):
            status, tone, summary = "error", "error", "异常"
        elif (rx_age_s is not None and rx_age_s > 120) or dropped > 0:
            status, tone, summary = "warn", "warn", "降级"
        else:
            status, tone, summary = "ok", "ok", "正常"
        segments["producer"] = {
            "label": "producer",
            "status": status,
            "tone": tone,
            "summary": summary,
            "detail": (
                (
                    f"connected={connected} rx_age={rx_age_s:g}s"
                    if rx_age_s is not None
                    else f"connected={connected}"
                )
            )
            + f" 订阅={subscribed_codes} tick5m={tick_batches_5m}",
            "log_component": "xt_producer",
            "last_issue_ts": producer_item.get("last_issue_ts"),
        }

    # consumer
    if consumer_item is None:
        segments["consumer"] = {
            "label": "consumer",
            "status": "degraded",
            "tone": "degraded",
            "summary": "无数据",
            "detail": "health/summary 缺少 xt_consumer",
            "log_component": "xt_consumer",
            "last_issue_ts": None,
        }
    else:
        metrics = _metrics(consumer_item)
        last_bar_age_s = _to_float(metrics.get("last_bar_age_s"))
        catchup = _to_int(metrics.get("catchup_mode"))
        backlog = _to_int(metrics.get("backlog_sum"))
        processed = _to_int(metrics.get("processed_bars_5m"))
        if catchup:
            status, tone, summary = "warn", "warn", "catchup"
        elif last_bar_age_s is None:
            status, tone, summary = "unknown", "unknown", "无数据"
        elif in_trading and last_bar_age_s > KLINE_FRESHNESS_RED_S:
            status, tone, summary = "error", "error", "停更"
        elif in_trading and last_bar_age_s > KLINE_FRESHNESS_YELLOW_S:
            status, tone, summary = "warn", "warn", "滞后"
        elif not in_trading and last_bar_age_s > KLINE_FRESHNESS_RED_S * 2:
            status, tone, summary = "warn", "warn", "盘后停更"
        else:
            status, tone, summary = "ok", "ok", "正常"
        age_detail = f"{last_bar_age_s:g}s" if last_bar_age_s is not None else "无"
        segments["consumer"] = {
            "label": "consumer",
            "status": status,
            "tone": tone,
            "summary": summary,
            "detail": f"last_bar_age={age_detail} backlog={backlog} catchup={catchup} bars5m={processed}",
            "log_component": "xt_consumer",
            "last_issue_ts": consumer_item.get("last_issue_ts"),
        }

    # K 线 API（realtimeCache 可用性 + 近 5 分钟 503 计数）
    probe = _kline_probe_if_due()
    window = _probe_state["window"]
    now_ts = time.time()
    _prune_probe_window(now_ts)
    recent_503 = sum(
        1
        for (ts, status) in window
        if status == "error" and now_ts - ts <= KLINE_503_WINDOW_S
    )
    if probe["status"] == "error":
        kline_status, kline_tone, kline_summary = "error", "error", "不可用"
    elif recent_503 > 0:
        kline_status, kline_tone, kline_summary = (
            "warn",
            "warn",
            f"近期 503 ×{recent_503}",
        )
    elif probe["status"] == "no_data":
        kline_status, kline_tone, kline_summary = "warn", "warn", "无缓存"
    else:
        kline_status, kline_tone, kline_summary = "ok", "ok", "正常"
    segments["kline_api"] = {
        "label": "K 线 API",
        "status": kline_status,
        "tone": kline_tone,
        "summary": kline_summary,
        "detail": (f"{probe.get('detail')}；近5分钟503={recent_503}"),
        "log_component": "xt_consumer",
        "last_issue_ts": (
            probe.get("checked_at") if probe["status"] == "error" else None
        ),
        "probe": probe,
    }
    return segments


@ops_bp.get("/kline-health")
def ops_kline_health():
    session = _resolve_trade_session()
    components: list[dict[str, Any]] = []
    health_error: str | None = None
    try:
        summary = get_runtime_query_service().get_health_summary(
            start_time=None, end_time=None
        )
        components = summary.get("components") or []
    except RuntimeObservabilityStoreError as exc:
        health_error = f"ClickHouse 数据源不可用（{exc}）"
        logger.warning("ops kline-health summary failed: %s", exc)
    except Exception as exc:  # pragma: no cover - 防御降级
        health_error = f"ClickHouse 数据源不可用（{exc}）"
        logger.warning("ops kline-health summary failed: %s", exc)

    segments = _build_kline_segments(
        _component_by_name(components, "xt_producer"),
        _component_by_name(components, "xt_consumer"),
        session,
    )
    return jsonify(
        {
            "generated_at": _iso(_now()),
            "trade_session": session,
            "segments": segments,
            "health_error": health_error,
        }
    )

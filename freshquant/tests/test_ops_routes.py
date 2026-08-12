"""运维控制台 ops 路由测试（S1+S2）。"""

from __future__ import annotations

import time
from datetime import datetime

import pytest
from flask import Flask

from freshquant.rear.ops import routes as ops_routes
from freshquant.runtime_constants import TZ
from freshquant.runtime_observability.clickhouse_store import (
    RuntimeObservabilityStoreError,
)


def _health_item(
    component: str,
    *,
    status: str = "info",
    heartbeat_age_s=None,
    metrics: dict | None = None,
    trace_count: int = 0,
    issue_trace_count: int = 0,
    issue_step_count: int = 0,
    last_issue_ts=None,
) -> dict:
    return {
        "component": component,
        "runtime_node": f"host:{component}",
        "status": status,
        "heartbeat_age_s": heartbeat_age_s,
        "metrics": metrics or {},
        "trace_count": trace_count,
        "issue_trace_count": issue_trace_count,
        "issue_step_count": issue_step_count,
        "last_issue_ts": last_issue_ts,
        "is_placeholder": False,
    }


class _FakeOpsService:
    def __init__(self, summary=None, error=None):
        self.summary = summary or {"components": []}
        self.error = error
        self.calls = 0

    def get_health_summary(self, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.summary


class _FakeCollection:
    def __init__(self, docs=None, count=0):
        self.docs = docs or []
        self.count_value = count

    def find_one(self, *args, **kwargs):
        return self.docs[0] if self.docs else None

    def find(self, query=None, **kwargs):
        return iter(self.docs)

    def count_documents(self, query, **kwargs):
        return self.count_value


class _FakeDb:
    def __init__(self, collections):
        self._collections = collections

    def __getitem__(self, name):
        return self._collections[name]


@pytest.fixture(autouse=True)
def _reset_ops_state():
    ops_routes._overview_cache["at"] = 0.0
    ops_routes._overview_cache["payload"] = None
    ops_routes._probe_state["last_run_at"] = 0.0
    ops_routes._probe_state["last_result"] = None
    ops_routes._probe_state["window"].clear()
    yield
    ops_routes._overview_cache["at"] = 0.0
    ops_routes._overview_cache["payload"] = None
    ops_routes._probe_state["last_run_at"] = 0.0
    ops_routes._probe_state["last_result"] = None
    ops_routes._probe_state["window"].clear()


@pytest.fixture
def ops_app(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(ops_routes.ops_bp)
    app.testing = True

    monkeypatch.setattr(ops_routes, "_mongo_ping", lambda: (True, 1.2, None))
    monkeypatch.setattr(ops_routes, "_redis_ping", lambda: (True, 0.8, None))
    monkeypatch.setattr(ops_routes, "_clickhouse_ping", lambda: (True, 2.1, None))
    monkeypatch.setattr(ops_routes, "_tdxhq_ping", lambda: (True, 3.3, None))
    monkeypatch.setattr(
        ops_routes,
        "_load_trade_dates",
        lambda: ({"2026-08-07"}, "available"),
    )
    monkeypatch.setattr(
        ops_routes,
        "_now",
        lambda: datetime(2026, 8, 7, 10, 30, 0, tzinfo=TZ),
    )
    return app


def _default_summary() -> dict:
    return {
        "components": [
            _health_item(
                "xt_producer",
                metrics={"connected": 1, "retry_count": 0, "rx_age_s": 5.0},
            ),
            _health_item(
                "xt_consumer",
                metrics={
                    "last_bar_age_s": 30.0,
                    "catchup_mode": 0,
                    "backlog_sum": 0,
                    "processed_bars_5m": 12,
                },
            ),
            _health_item(
                "guardian_strategy",
                status="warning",
                heartbeat_age_s=8.0,
                trace_count=31,
                issue_trace_count=25,
                issue_step_count=50,
                last_issue_ts="2026-08-07T16:15:32+08:00",
            ),
            _health_item(
                "broker_gateway",
                metrics={"connected": 1, "retry_count": 0},
            ),
        ]
    }


def _patch_mongo(monkeypatch, *, positions=None, gaps=0, in_flight=0):
    collections = {
        "xt_positions": _FakeCollection(
            docs=positions or [{"sync_last_seen_at": int(time.time())}]
        ),
        "om_reconciliation_gaps": _FakeCollection(count=gaps),
        "om_orders": _FakeCollection(count=in_flight),
        "om_broker_orders": _FakeCollection(count=0),
    }
    monkeypatch.setattr(ops_routes, "DBfreshquant", _FakeDb(collections))
    monkeypatch.setattr(ops_routes, "DBOrderManagement", _FakeDb(collections))


def test_ops_overview_aggregates_kpis_and_ledger(ops_app, monkeypatch):
    service = _FakeOpsService(summary=_default_summary())
    monkeypatch.setattr(ops_routes, "get_runtime_query_service", lambda: service)
    _patch_mongo(
        monkeypatch,
        positions=[{"sync_last_seen_at": int(time.time()) - 5}],
        gaps=0,
        in_flight=0,
    )

    response = ops_app.test_client().get("/api/ops/overview")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["trade_session"]["session"] == "morning"
    assert payload["trade_session"]["label"] == "盘中"

    kpis = payload["kpis"]
    # S3 后宿主机卡由快照驱动；测试环境无快照文件 -> 显式降级而非占位
    assert kpis["supervisor"]["status"] == "degraded"
    assert kpis["docker_containers"]["status"] == "degraded"
    assert kpis["xtdata_connection"]["ok"] is True
    assert kpis["xtdata_connection"]["summary"] == "connected"
    assert kpis["kline_freshness"]["status"] == "ok"
    assert kpis["kline_freshness"]["summary"] == "30s"
    assert kpis["account_sync"]["source"] == "mongo"
    assert kpis["account_sync"]["status"] == "ok"
    assert kpis["guardian_heartbeat"]["status"] == "ok"
    assert kpis["broker_connection"]["ok"] is True
    assert kpis["ledger_consistency"]["summary"] == "一致"

    for name in ("mongo", "redis", "clickhouse", "tdxhq"):
        assert payload["dependencies"][name]["ok"] is True

    issues = payload["issues"]
    assert issues["component_issue_count"] == 1
    assert issues["issue_trace_count"] == 25
    assert issues["issue_step_count"] == 50
    assert issues["last_issue_ts"] == "2026-08-07T16:15:32+08:00"
    assert issues["components"][0]["component"] == "guardian_strategy"


def test_ops_overview_kline_freshness_red_in_trading_session(ops_app, monkeypatch):
    summary = _default_summary()
    summary["components"][1]["metrics"]["last_bar_age_s"] = 200.0
    service = _FakeOpsService(summary=summary)
    monkeypatch.setattr(ops_routes, "get_runtime_query_service", lambda: service)
    _patch_mongo(monkeypatch, positions=[{"sync_last_seen_at": int(time.time()) - 5}])

    response = ops_app.test_client().get("/api/ops/overview")
    payload = response.get_json()
    kpi = payload["kpis"]["kline_freshness"]
    assert kpi["status"] == "error"
    assert kpi["tone"] == "error"
    assert kpi["summary"] == "200s"


def test_ops_overview_degrades_when_clickhouse_unavailable(ops_app, monkeypatch):
    service = _FakeOpsService(
        summary=_default_summary(),
        error=RuntimeObservabilityStoreError("clickhouse down"),
    )
    monkeypatch.setattr(ops_routes, "get_runtime_query_service", lambda: service)
    _patch_mongo(monkeypatch, positions=[{"sync_last_seen_at": int(time.time()) - 5}])

    response = ops_app.test_client().get("/api/ops/overview")
    payload = response.get_json()

    assert payload["summary"]["health_source"] == "degraded"
    for key in (
        "xtdata_connection",
        "kline_freshness",
        "guardian_heartbeat",
        "broker_connection",
    ):
        assert payload["kpis"][key]["status"] == "degraded"
        assert "ClickHouse" in payload["kpis"][key]["detail"]
    # Mongo 派生卡片不受 ClickHouse 故障影响
    assert payload["kpis"]["account_sync"]["status"] == "ok"
    assert payload["kpis"]["ledger_consistency"]["status"] == "ok"


def test_ops_overview_degrades_when_mongo_unavailable(ops_app, monkeypatch):
    service = _FakeOpsService(summary=_default_summary())
    monkeypatch.setattr(ops_routes, "get_runtime_query_service", lambda: service)

    class _BoomDb:
        def __getitem__(self, name):
            raise RuntimeError("mongo down")

    monkeypatch.setattr(ops_routes, "DBfreshquant", _BoomDb())
    monkeypatch.setattr(ops_routes, "DBOrderManagement", _BoomDb())

    response = ops_app.test_client().get("/api/ops/overview")
    payload = response.get_json()

    assert payload["summary"]["mongo_source"] == "degraded"
    assert payload["kpis"]["account_sync"]["status"] == "degraded"
    assert payload["kpis"]["ledger_consistency"]["status"] == "degraded"
    assert payload["kpis"]["xtdata_connection"]["ok"] is True


def test_ops_overview_5s_cache_avoids_repeated_queries(ops_app, monkeypatch):
    service = _FakeOpsService(summary=_default_summary())
    monkeypatch.setattr(ops_routes, "get_runtime_query_service", lambda: service)
    _patch_mongo(monkeypatch, positions=[{"sync_last_seen_at": int(time.time()) - 5}])

    # 注入固定时钟：缓存窗口判定与机器速度解耦，避免慢 runner 上真实 5s
    # 超时导致第二次请求被误判为缓存未生效（时序类 flaky）。
    clock = {"now": 1000.0}
    monkeypatch.setattr(ops_routes, "_monotonic", lambda: clock["now"])

    client = ops_app.test_client()
    first = client.get("/api/ops/overview").get_json()
    clock["now"] += 1.0  # TTL 窗口内
    second = client.get("/api/ops/overview").get_json()

    assert service.calls == 1
    assert first["cache"]["cached"] is False
    assert second["cache"]["cached"] is True
    assert first["generated_at"] == second["generated_at"]

    # 超过 TTL 后应重新查询并重建缓存
    clock["now"] += 10.0
    third = client.get("/api/ops/overview").get_json()
    assert service.calls == 2
    assert third["cache"]["cached"] is False


def test_ops_kline_health_segment_status(ops_app, monkeypatch):
    summary = _default_summary()
    summary["components"][0]["metrics"] = {
        "connected": 0,
        "rx_age_s": 800.0,
        "subscribed_codes": 60,
        "tick_batches_5m": 0,
    }
    summary["components"][1]["metrics"] = {
        "last_bar_age_s": 240.0,
        "catchup_mode": 0,
        "backlog_sum": 5,
        "processed_bars_5m": 0,
    }
    service = _FakeOpsService(summary=summary)
    monkeypatch.setattr(ops_routes, "get_runtime_query_service", lambda: service)
    monkeypatch.setattr(
        ops_routes,
        "_read_realtime_cache_sample",
        lambda: {"status": "success", "realtime_cache": True, "detail": "命中"},
    )

    response = ops_app.test_client().get("/api/ops/kline-health")
    assert response.status_code == 200
    payload = response.get_json()

    producer = payload["segments"]["producer"]
    assert producer["status"] == "error"
    assert producer["log_component"] == "xt_producer"
    assert "rx_age" in producer["detail"]

    consumer = payload["segments"]["consumer"]
    assert consumer["status"] == "error"
    assert consumer["summary"] == "停更"
    assert consumer["log_component"] == "xt_consumer"

    kline_api = payload["segments"]["kline_api"]
    assert kline_api["status"] == "ok"


def test_ops_kline_health_probe_error_counts_503_window(ops_app, monkeypatch):
    service = _FakeOpsService(summary=_default_summary())
    monkeypatch.setattr(ops_routes, "get_runtime_query_service", lambda: service)
    monkeypatch.setattr(
        ops_routes,
        "_read_realtime_cache_sample",
        lambda: {
            "status": "error",
            "realtime_cache": False,
            "detail": "Redis 不可用（boom）",
        },
    )

    response = ops_app.test_client().get("/api/ops/kline-health")
    payload = response.get_json()

    kline_api = payload["segments"]["kline_api"]
    assert kline_api["status"] == "error"
    assert kline_api["summary"] == "不可用"
    assert kline_api["probe"]["status"] == "error"
    assert kline_api["last_issue_ts"] is not None
    # 探针窗口记录了一次 error
    window_statuses = [status for (_ts, status) in ops_routes._probe_state["window"]]
    assert window_statuses.count("error") == 1


def test_ops_ledger_invariants_reports_violations(ops_app, monkeypatch):
    """#582 PR4：/api/ops/ledger-invariants 只读探针返回守恒违规。"""

    class FakeRepository:
        def list_position_entries(self, *, symbol=None, entry_ids=None, status=None):
            return [
                {
                    "entry_id": "entry_1",
                    "symbol": "600104",
                    "status": "OPEN",
                    "original_quantity": 7400,
                    "remaining_quantity": 7400,
                    "aggregation_members": [
                        {"broker_order_key": "k1", "quantity": 300}
                    ],
                }
            ]

        def list_all_entry_slices(self):
            return [{"entry_id": "entry_1", "original_quantity": 7400}]

        def list_broker_orders(self, **kwargs):
            return []

        def list_order_requests(self, **kwargs):
            return []

        def list_orders(self, **kwargs):
            return []

    monkeypatch.setattr(
        "freshquant.order_management.repository.OrderManagementRepository",
        lambda: FakeRepository(),
    )
    _patch_mongo(monkeypatch, positions=[{"stock_code": "600104.SH", "volume": 7400}])

    resp = ops_app.test_client().get("/api/ops/ledger-invariants")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is False
    assert payload["violation_count"] >= 1
    assert len(payload["violations"]["entry_member_conservation"]) == 1


def test_ops_ledger_invariants_ok_when_conserved(ops_app, monkeypatch):
    class FakeRepository:
        def list_position_entries(self, *, symbol=None, entry_ids=None, status=None):
            return [
                {
                    "entry_id": "entry_1",
                    "symbol": "600104",
                    "status": "OPEN",
                    "original_quantity": 7400,
                    "remaining_quantity": 7400,
                    "aggregation_members": [
                        {"broker_order_key": "k1", "quantity": 7400}
                    ],
                }
            ]

        def list_all_entry_slices(self):
            return [{"entry_id": "entry_1", "original_quantity": 7400}]

        def list_broker_orders(self, **kwargs):
            return []

        def list_order_requests(self, **kwargs):
            return []

        def list_orders(self, **kwargs):
            return []

    monkeypatch.setattr(
        "freshquant.order_management.repository.OrderManagementRepository",
        lambda: FakeRepository(),
    )
    _patch_mongo(monkeypatch, positions=[{"stock_code": "600104.SH", "volume": 7400}])

    resp = ops_app.test_client().get("/api/ops/ledger-invariants")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["violation_count"] == 0


def test_ops_kline_health_unknown_when_no_bar_age(ops_app, monkeypatch):
    summary = _default_summary()
    summary["components"][1]["metrics"]["last_bar_age_s"] = None
    service = _FakeOpsService(summary=summary)
    monkeypatch.setattr(ops_routes, "get_runtime_query_service", lambda: service)
    monkeypatch.setattr(
        ops_routes,
        "_read_realtime_cache_sample",
        lambda: {"status": "no_data", "realtime_cache": True, "detail": "无缓存"},
    )

    response = ops_app.test_client().get("/api/ops/kline-health")
    payload = response.get_json()
    assert payload["segments"]["consumer"]["status"] == "unknown"
    assert payload["segments"]["kline_api"]["status"] == "warn"


def test_compute_trade_session_cases():
    trade_dates = {"2026-08-07"}

    def run(hhmm):
        hour, minute = (int(part) for part in hhmm.split(":"))
        return ops_routes._compute_trade_session(
            datetime(2026, 8, 7, hour, minute, tzinfo=TZ), trade_dates
        )

    assert run("09:20")["session"] == "auction"
    assert run("10:00")["session"] == "morning"
    assert run("12:00")["session"] == "noon_break"
    assert run("14:00")["session"] == "afternoon"
    assert run("15:30")["session"] == "post_close"
    assert (
        ops_routes._compute_trade_session(
            datetime(2026, 8, 8, 10, 0, tzinfo=TZ), trade_dates
        )["session"]
        == "non_trade_day"
    )
    assert (
        ops_routes._compute_trade_session(datetime(2026, 8, 8, 10, 0, tzinfo=TZ), None)[
            "session"
        ]
        == "unknown"
    )


def test_resolve_tdxhq_endpoint_prefers_compose_env(monkeypatch):
    monkeypatch.delenv("FRESHQUANT_TDX__HQ_ENDPOINT", raising=False)
    monkeypatch.delenv("FRESHQUANT_TDX__HQ__ENDPOINT", raising=False)
    assert ops_routes._resolve_tdxhq_endpoint() == "http://127.0.0.1:15001"

    monkeypatch.setenv("FRESHQUANT_TDX__HQ_ENDPOINT", "http://fq_tdxhq:5001")
    assert ops_routes._resolve_tdxhq_endpoint() == "http://fq_tdxhq:5001"

    monkeypatch.setenv("FRESHQUANT_TDX__HQ__ENDPOINT", "http://fallback:6000")
    assert ops_routes._resolve_tdxhq_endpoint() == "http://fq_tdxhq:5001"


def test_resolve_tdxhq_endpoint_legacy_key_warns_and_still_works(monkeypatch):
    monkeypatch.delenv("FRESHQUANT_TDX__HQ_ENDPOINT", raising=False)
    monkeypatch.setenv("FRESHQUANT_TDX__HQ__ENDPOINT", "http://legacy:7000")
    assert ops_routes._resolve_tdxhq_endpoint() == "http://legacy:7000"


def _fake_host_snapshot(
    *,
    supervisor_ok=True,
    supervisor_running=9,
    supervisor_expected=9,
    supervisor_error=None,
    docker_ok=True,
    docker_running=10,
    docker_expected=10,
    docker_error=None,
    captured_at="2026-08-07T23:00:00+00:00",
):
    return {
        "captured_at": captured_at,
        "expected": {
            "supervisor_programs": supervisor_expected,
            "docker_containers": docker_expected,
        },
        "supervisor": {
            "ok": supervisor_ok,
            "error": supervisor_error,
            "running_count": supervisor_running,
            "expected_count": supervisor_expected,
            "programs": [
                {
                    "name": f"prog_{index}",
                    "group": "g",
                    "state": "Running" if index < supervisor_running else "FATAL",
                    "pid": 100 + index,
                    "uptime_s": 60,
                    "description": "desc",
                }
                for index in range(supervisor_expected)
            ],
        },
        "docker": {
            "ok": docker_ok,
            "error": docker_error,
            "compose_project": "fqnext_20260223",
            "running_count": docker_running,
            "expected_count": docker_expected,
            "containers": [
                {
                    "name": f"fqnext_20260223-svc_{index}-1",
                    "image": "img",
                    "state": "running" if index < docker_running else "exited",
                    "status": "Up" if index < docker_running else "Exited",
                    "compose_project": "fqnext_20260223",
                    "compose_service": f"svc_{index}",
                }
                for index in range(docker_expected)
            ],
        },
    }


def test_supervisor_kpi_reports_running_and_degraded_programs():
    kpi = ops_routes._build_supervisor_kpi(_fake_host_snapshot())
    assert kpi["status"] == "ok"
    assert kpi["summary"] == "Running 9/9"
    assert kpi["source"] == "host_snapshot"

    degraded = ops_routes._build_supervisor_kpi(
        _fake_host_snapshot(supervisor_running=7)
    )
    assert degraded["status"] == "error"
    assert degraded["summary"] == "Running 7/9"
    assert "prog_7" in degraded["detail"]


def test_docker_kpi_reports_running_and_degraded_containers():
    kpi = ops_routes._build_docker_kpi(_fake_host_snapshot())
    assert kpi["status"] == "ok"
    assert kpi["summary"] == "Up 10/10"

    degraded = ops_routes._build_docker_kpi(_fake_host_snapshot(docker_running=9))
    assert degraded["status"] == "error"
    assert degraded["summary"] == "Up 9/10"
    assert "svc_9" in degraded["detail"]


def test_host_kpis_degrade_when_snapshot_missing(monkeypatch, ops_app):
    monkeypatch.setattr(ops_routes, "_load_host_snapshot", lambda: None)
    service = _FakeOpsService(summary=_default_summary())
    monkeypatch.setattr(ops_routes, "get_runtime_query_service", lambda: service)
    _patch_mongo(monkeypatch, positions=[{"sync_last_seen_at": int(time.time()) - 5}])

    response = ops_app.test_client().get("/api/ops/overview")
    payload = response.get_json()
    assert payload["kpis"]["supervisor"]["status"] == "degraded"
    assert payload["kpis"]["supervisor"]["summary"] == "数据源不可用"
    assert "宿主快照不可用" in payload["kpis"]["supervisor"]["detail"]
    assert payload["kpis"]["docker_containers"]["status"] == "degraded"
    assert payload["host"]["available"] is False


def test_host_kpis_degrade_when_supervisor_source_down(monkeypatch, ops_app):
    monkeypatch.setattr(
        ops_routes,
        "_load_host_snapshot",
        lambda: _fake_host_snapshot(
            supervisor_ok=False,
            supervisor_error="supervisor XML-RPC 失败: boom",
        ),
    )
    service = _FakeOpsService(summary=_default_summary())
    monkeypatch.setattr(ops_routes, "get_runtime_query_service", lambda: service)
    _patch_mongo(monkeypatch, positions=[{"sync_last_seen_at": int(time.time()) - 5}])

    payload = ops_app.test_client().get("/api/ops/overview").get_json()
    assert payload["kpis"]["supervisor"]["status"] == "degraded"
    assert "Supervisor 数据源不可用" in payload["kpis"]["supervisor"]["detail"]
    # docker 卡独立于 supervisor 源
    assert payload["kpis"]["docker_containers"]["status"] == "ok"


def test_host_runtime_endpoint_returns_snapshot_detail(monkeypatch, ops_app):
    monkeypatch.setattr(
        ops_routes,
        "_load_host_snapshot",
        lambda: _fake_host_snapshot(),
    )
    response = ops_app.test_client().get("/api/ops/host-runtime")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["available"] is True
    assert payload["supervisor"]["running_count"] == 9
    assert payload["supervisor"]["expected_count"] == 9
    assert len(payload["supervisor"]["programs"]) == 9
    assert payload["docker"]["running_count"] == 10
    assert len(payload["docker"]["containers"]) == 10
    assert payload["docker"]["compose_project"] == "fqnext_20260223"

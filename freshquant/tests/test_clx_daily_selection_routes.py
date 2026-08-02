from __future__ import annotations

import json
import sys
from types import ModuleType

from flask import Flask

from freshquant.clx_daily_selection.service import ClxDailySelectionService


class FakeQFQDataNotReadyError(RuntimeError):
    error_code = "QFQ_DATA_NOT_READY"

    def __init__(self, message, *, scope=None, code=None, missing_dates=None):
        self.scope = str(scope or "")
        self.code = str(code or "")
        self.missing_dates = list(missing_dates or [])
        super().__init__(f"QFQ_DATA_NOT_READY: {message}")

    def as_dict(self):
        return {
            "ok": False,
            "error_code": self.error_code,
            "message": str(self),
            "scope": self.scope,
            "code": self.code,
            "missing_dates": self.missing_dates,
        }


class _EmptySnapshotCollection:
    def find(self, _query):
        return []


def install_qfq_reader(monkeypatch):
    module = ModuleType("freshquant.data.qfq_reader")
    module.QFQDataNotReadyError = FakeQFQDataNotReadyError
    module.QFQ_DATA_NOT_READY_HTTP_STATUS = 503
    monkeypatch.setitem(sys.modules, module.__name__, module)


def make_client(monkeypatch, service):
    install_qfq_reader(monkeypatch)
    from freshquant.rear.clx_daily_selection.routes import clx_daily_selection_bp

    monkeypatch.setattr(
        "freshquant.rear.clx_daily_selection.routes._get_service", lambda: service
    )
    app = Flask("test_clx_daily_selection_routes")
    app.register_blueprint(clx_daily_selection_bp)
    return app.test_client()


def test_model_catalog_route_exposes_real_filter_contract(monkeypatch):
    service = ClxDailySelectionService(
        repository=object(),
        market_data_provider=object(),
        engine=object(),
    )

    response = make_client(monkeypatch, service).get(
        "/api/clx-daily-selection/model-catalog"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["schema_version"] == "clx-daily-selection.v2"
    assert payload["condition_catalog_version"] == "clx18-condition-v1"
    assert payload["evaluation_profile"]["id"] == "production_v1"
    assert payload["evaluation_profile"]["switch_opt"] == 1
    assert [item["model_key"] for item in payload["models"]] == [
        f"S{model_id:04d}" for model_id in range(18)
    ]
    assert [item["production_model_id"] for item in payload["models"]] == list(
        range(10000, 10018)
    )
    assert [item["key"] for item in payload["conditions"]] == [
        *(f"entrypoint_{entrypoint}" for entrypoint in range(1, 10)),
        "buy_engulfing",
        "buy_normal_fractal_fallback",
        "sell_engulfing",
        "sell_normal_fractal_fallback",
        "entrypoint_3_unknown",
        "decoder_unknown",
    ]
    assert all(item["label"] for item in payload["conditions"])


def test_batch_routes_preserve_final_default_and_explicit_partial(monkeypatch):
    captured = []

    class Service:
        def list_batches(self, *, limit, include_partial):
            captured.append(("list", limit, include_partial))
            return {"items": [{"batch_id": "clx-2026-03-19-production_v1"}]}

        def get_latest_batch(self, *, include_partial):
            captured.append(("latest", include_partial))
            return {
                "batch_id": "clx-2026-03-19-production_v1",
                "release_status": "partial" if include_partial else "final",
                "is_final": not include_partial,
            }

    client = make_client(monkeypatch, Service())

    batches = client.get("/api/clx-daily-selection/batches?limit=12&include_partial=1")
    latest_final = client.get("/api/clx-daily-selection/batches/latest")
    latest_partial = client.get(
        "/api/clx-daily-selection/batches/latest?include_partial=1"
    )

    assert batches.status_code == 200
    assert latest_final.get_json()["is_final"] is True
    assert latest_partial.get_json()["release_status"] == "partial"
    assert captured == [("list", 12, True), ("latest", False), ("latest", True)]


def test_summary_results_detail_and_statistics_routes_delegate_contract(monkeypatch):
    captured = {}

    class Service:
        def get_batch_summary(self, batch_id):
            captured["summary"] = batch_id
            return {"batch_id": batch_id, "status": "completed", "is_final": True}

        def query_results(self, batch_id, payload):
            captured["results"] = (batch_id, payload)
            return {"batch_id": batch_id, "rows": [{"symbol": "000001"}]}

        def get_result_detail(self, batch_id, asset_type, symbol):
            captured["detail"] = (batch_id, asset_type, symbol)
            return {
                "batch_id": batch_id,
                "snapshot": {"asset_type": asset_type, "symbol": symbol},
                "memberships": [],
            }

        def get_statistics(self, batch_id):
            captured["statistics"] = batch_id
            return {"batch_id": batch_id, "models": []}

    client = make_client(monkeypatch, Service())
    batch_id = "clx-2026-03-19-production_v1"

    summary = client.get(f"/api/clx-daily-selection/batches/{batch_id}/summary")
    results = client.post(
        f"/api/clx-daily-selection/batches/{batch_id}/results",
        data=json.dumps(
            {
                "asset_types": ["stock"],
                "model_keys": ["S0001"],
                "min_model_count": 2,
                "limit": 50,
            }
        ),
        content_type="application/json",
    )
    detail = client.get(
        f"/api/clx-daily-selection/batches/{batch_id}/results/stock/000001"
    )
    statistics = client.get(f"/api/clx-daily-selection/batches/{batch_id}/statistics")

    assert summary.get_json()["is_final"] is True
    assert results.get_json()["rows"][0]["symbol"] == "000001"
    assert detail.get_json()["snapshot"]["asset_type"] == "stock"
    assert statistics.get_json()["models"] == []
    assert captured["summary"] == batch_id
    assert captured["results"][1]["model_keys"] == ["S0001"]
    assert captured["detail"] == (batch_id, "stock", "000001")
    assert captured["statistics"] == batch_id


def test_statistics_route_maps_non_final_batch_contract_error(monkeypatch):
    batch_id = "clx-2026-03-19-production_v1-partial"

    class Service:
        def get_statistics(self, requested_batch_id):
            raise ValueError(
                f"statistics require a final CLX batch: {requested_batch_id}"
            )

    response = make_client(monkeypatch, Service()).get(
        f"/api/clx-daily-selection/batches/{batch_id}/statistics"
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "code": "invalid_request",
        "message": f"statistics require a final CLX batch: {batch_id}",
        "retryable": False,
    }


def test_results_route_maps_invalid_line_flags_to_http_400(monkeypatch):
    batch_id = "clx-2026-03-19-production_v1"

    class Service:
        def query_results(self, requested_batch_id, payload):
            assert requested_batch_id == batch_id
            assert payload["line_flags"] == {"above_ma250": "false"}
            raise ValueError("unsupported line_flags value: above_ma250=false")

    response = make_client(monkeypatch, Service()).post(
        f"/api/clx-daily-selection/batches/{batch_id}/results/query",
        json={"line_flags": {"above_ma250": "false"}},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "code": "invalid_request",
        "message": "unsupported line_flags value: above_ma250=false",
        "retryable": False,
    }


def test_results_query_post_rejects_object_min_model_count(monkeypatch):
    batch_id = "clx-2026-03-19-production_v1"

    class Service:
        def query_results(self, _batch_id, payload):
            from freshquant.clx_daily_selection.repository import (
                ClxDailySelectionRepository,
            )

            repository = ClxDailySelectionRepository.__new__(
                ClxDailySelectionRepository
            )
            repository.snapshots = _EmptySnapshotCollection()
            return repository.query_snapshots([], payload)

    response = make_client(monkeypatch, Service()).post(
        f"/api/clx-daily-selection/batches/{batch_id}/results/query",
        json={"min_model_count": {"value": 2}},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "code": "invalid_request",
        "message": "min_model_count must be an integer",
        "retryable": False,
    }


def test_results_post_rejects_list_limit(monkeypatch):
    batch_id = "clx-2026-03-19-production_v1"

    class Service:
        def query_results(self, _batch_id, payload):
            from freshquant.clx_daily_selection.repository import (
                ClxDailySelectionRepository,
            )

            repository = ClxDailySelectionRepository.__new__(
                ClxDailySelectionRepository
            )
            repository.snapshots = _EmptySnapshotCollection()
            return repository.query_snapshots([], payload)

    response = make_client(monkeypatch, Service()).post(
        f"/api/clx-daily-selection/batches/{batch_id}/results",
        json={"limit": [50]},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "code": "invalid_request",
        "message": "limit must be an integer",
        "retryable": False,
    }


def test_sync_selected_results_to_tdx_route_forwards_only_explicit_items(monkeypatch):
    batch_id = "clx-2026-07-31-production_v1-final"
    captured = {}

    class Service:
        def sync_selected_results_to_tdx(self, requested_batch_id, payload):
            captured["call"] = (requested_batch_id, payload)
            return {
                "group_name": "clx_18",
                "file_name": "CLX_18.blk",
                "requested_count": 2,
                "written_count": 2,
                "scope_id": requested_batch_id,
                "trade_date": "2026-07-31",
            }

    response = make_client(monkeypatch, Service()).post(
        f"/api/clx-daily-selection/batches/{batch_id}/results/sync-selected-to-tdx",
        json={
            "items": [
                {"asset_type": "stock", "symbol": "000001"},
                {"asset_type": "etf", "symbol": "159577"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.get_json()["written_count"] == 2
    assert response.get_json()["group_name"] == "clx_18"
    assert captured["call"] == (
        batch_id,
        {
            "items": [
                {"asset_type": "stock", "symbol": "000001"},
                {"asset_type": "etf", "symbol": "159577"},
            ]
        },
    )


def test_sync_selected_results_to_tdx_route_reports_failure_and_old_group(monkeypatch):
    batch_id = "clx-2026-07-31-production_v1-final"

    class Service:
        def sync_selected_results_to_tdx(self, _batch_id, _payload):
            raise RuntimeError("replace denied")

    response = make_client(monkeypatch, Service()).post(
        f"/api/clx-daily-selection/batches/{batch_id}/results/sync-selected-to-tdx",
        json={"items": [{"asset_type": "stock", "symbol": "000001"}]},
    )

    assert response.status_code == 500
    assert response.get_json() == {
        "code": "tdx_sync_failed",
        "message": "replace denied；旧分组已保留",
        "retryable": True,
    }


def test_obsolete_filter_export_route_is_not_registered(monkeypatch):
    response = make_client(monkeypatch, object()).post(
        "/api/clx-daily-selection/batches/batch/results/sync-to-tdx",
        json={"items": [{"asset_type": "stock", "symbol": "000001"}]},
    )

    assert response.status_code == 404


def test_history_signals_route_normalizes_query_and_exposes_etag(monkeypatch):
    captured = {}

    class Service:
        def get_history_signals(self, **kwargs):
            captured.update(kwargs)
            return {
                "schema_version": "clx-daily-selection.v1",
                "symbol": kwargs["symbol"],
                "asset_type": kwargs["asset_type"],
                "period": "1d",
                "bars": [{"date": "2026-03-19"}],
                "signals_by_model": {"S0001": [1101]},
                "markers_by_model": {"S0001": [{"bar_index": 0}]},
                "query_hash": "abc123",
                "qfq_effective_version": "stock-snapshot-20260319",
                "future_function_guard": {"passed": True},
            }

    client = make_client(monkeypatch, Service())

    response = client.get(
        "/api/clx-daily-selection/history/signals"
        "?symbol=000001&assetType=stock&period=1d&endDate=2026-03-19"
        "&barCount=250&modelKeys=S0001,S0002&conditionKeys=entrypoint_1"
        "&includeRaw=1"
    )

    assert response.status_code == 200
    assert response.headers["ETag"] == '"abc123:stock-snapshot-20260319"'
    assert response.headers["X-QFQ-Effective-Version"] == "stock-snapshot-20260319"
    assert response.get_json()["qfq_effective_version"] == ("stock-snapshot-20260319")
    assert response.get_json()["future_function_guard"]["passed"] is True
    assert captured == {
        "symbol": "000001",
        "asset_type": "stock",
        "period": "1d",
        "end_date": "2026-03-19",
        "bar_count": 250,
        "model_keys": ["S0001", "S0002"],
        "condition_keys": ["entrypoint_1"],
        "include_raw": True,
    }


def test_history_signals_route_rejects_non_daily_period(monkeypatch):
    class Service:
        def get_history_signals(self, **_kwargs):
            raise ValueError("period must be 1d")

    response = make_client(monkeypatch, Service()).get(
        "/api/clx-daily-selection/history/signals?symbol=000001&period=5m"
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_request"


def test_history_signals_route_maps_qfq_not_ready_to_http_503(monkeypatch):
    class Service:
        def get_history_signals(self, **_kwargs):
            raise FakeQFQDataNotReadyError(
                "active snapshot is not ready",
                scope="stock",
                code="000001",
                missing_dates=["2026-03-19"],
            )

    response = make_client(monkeypatch, Service()).get(
        "/api/clx-daily-selection/history/signals"
        "?symbol=000001&assetType=stock&period=1d&endDate=2026-03-19"
    )

    assert response.status_code == 503
    assert response.get_json() == {
        "ok": False,
        "error_code": "QFQ_DATA_NOT_READY",
        "message": "QFQ_DATA_NOT_READY: active snapshot is not ready",
        "scope": "stock",
        "code": "000001",
        "missing_dates": ["2026-03-19"],
    }

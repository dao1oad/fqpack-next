import types
from datetime import datetime
from typing import Any

import pytest
from flask import Flask

from freshquant.rear.gantt import routes as gantt_routes


def _build_readmodel_stub() -> Any:
    svc_module: Any = types.ModuleType("freshquant.data.gantt_readmodel")
    svc_module.DBGantt = {}
    svc_module.get_trade_dates_between = lambda start_date, end_date: []
    svc_module.query_gantt_plate_matrix = lambda **kwargs: {}
    svc_module.query_gantt_plate_reason_map = lambda **kwargs: {}
    svc_module.query_gantt_stock_matrix = lambda **kwargs: {}
    svc_module.query_stock_hot_reason_rows = lambda **kwargs: []
    svc_module.query_shouban30_plate_rows = lambda **kwargs: []
    svc_module.query_shouban30_stock_rows = lambda **kwargs: []
    svc_module._load_shouban30_credit_subject_lookup = lambda *args, **kwargs: {}
    svc_module._load_shouban30_quality_subject_lookup = lambda *args, **kwargs: {}
    svc_module._resolve_shouban30_extra_filter_result = lambda *args, **kwargs: {
        "tag": None,
        "matches": {},
    }
    return svc_module


def _build_shouban30_stub() -> Any:
    shouban_module: Any = types.ModuleType("freshquant.shouban30_pool_service")
    shouban_module.SHOUBAN30_PRE_POOL_CATEGORY = "三十涨停Pro预选"
    shouban_module.SHOUBAN30_STOCK_POOL_CATEGORY = "三十涨停Pro自选"
    shouban_module.SHOUBAN30_BLK_FILENAME = "30RYZT.blk"
    shouban_module.replace_pre_pool = lambda items, context=None: {}
    shouban_module.append_pre_pool = lambda items, context=None: {}
    shouban_module.list_pre_pool = lambda: []
    shouban_module.add_pre_pool_item_to_stock_pool = lambda code6: "created"
    shouban_module.sync_pre_pool_to_stock_pool = lambda: {}
    shouban_module.sync_pre_pool_to_blk = lambda: {}
    shouban_module.clear_pre_pool = lambda: {}
    shouban_module.delete_pre_pool_item = lambda code6: {}
    shouban_module.list_stock_pool = lambda: []
    shouban_module.add_stock_pool_item_to_must_pool = lambda code6: "created"
    shouban_module.sync_stock_pool_to_must_pool = lambda: {}
    shouban_module.sync_stock_pool_to_blk = lambda: {}
    shouban_module.clear_stock_pool = lambda: {}
    shouban_module.delete_stock_pool_item = lambda code6: {}
    shouban_module.sync_must_pool_to_blk = lambda: {}
    shouban_module.clear_must_pool = lambda: {}
    return shouban_module


@pytest.fixture(autouse=True)
def _stub_gantt_route_dependencies(monkeypatch):
    monkeypatch.setattr(gantt_routes, "svc", _build_readmodel_stub())


class FakeCollection:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, query=None, projection=None):
        query = query or {}
        return [doc for doc in self.docs if _matches(doc, query)]


def _matches(doc, query):
    for key, expected in (query or {}).items():
        actual = doc.get(key)
        if isinstance(expected, dict):
            if "$gte" in expected and actual < expected["$gte"]:
                return False
            if "$lte" in expected and actual > expected["$lte"]:
                return False
            if "$in" in expected and actual not in expected["$in"]:
                return False
            continue
        if actual != expected:
            return False
    return True


def _fake_db(**collections):
    return {name: FakeCollection(rows) for name, rows in collections.items()}


def test_get_gantt_plates_reads_readmodel_collection(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes.svc,
        "query_gantt_plate_matrix",
        lambda **kwargs: {
            "dates": ["2026-03-04", "2026-03-05"],
            "y_axis": [{"id": "11", "name": "robotics"}],
            "series": [
                [0, 0, 2],
                [1, 0, 1],
            ],
        },
    )
    monkeypatch.setattr(
        gantt_routes.svc,
        "query_gantt_plate_reason_map",
        lambda **kwargs: {
            "2026-03-04|11": {
                "reason_text": "day1 reason",
                "reason_ref": {"trade_date": "2026-03-04", "plate_id": 11},
            },
            "2026-03-05|11": {
                "reason_text": "day2 reason",
                "reason_ref": {"trade_date": "2026-03-05", "plate_id": 11},
            },
        },
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get("/api/gantt/plates?provider=xgb&days=30")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["dates"] == ["2026-03-04", "2026-03-05"]
    assert payload["data"]["y_axis"] == [{"id": "11", "name": "robotics"}]
    assert payload["meta"]["reason_map"] == {
        "2026-03-04|11": {
            "reason_text": "day1 reason",
            "reason_ref": {"trade_date": "2026-03-04", "plate_id": 11},
        },
        "2026-03-05|11": {
            "reason_text": "day2 reason",
            "reason_ref": {"trade_date": "2026-03-05", "plate_id": 11},
        },
    }


def test_get_gantt_plates_keeps_trade_date_axis_for_calendar_window(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes.svc,
        "query_gantt_plate_matrix",
        lambda **kwargs: {
            "dates": ["2026-03-04", "2026-03-05", "2026-03-06"],
            "y_axis": [{"id": "robotics", "name": "robotics"}],
            "series": [
                [0, 0, 2],
                [2, 0, 1],
            ],
        },
    )
    monkeypatch.setattr(
        gantt_routes.svc,
        "query_gantt_plate_reason_map",
        lambda **kwargs: {
            "2026-03-04|robotics": {
                "reason_text": "day1 reason",
                "reason_ref": {
                    "trade_date": "2026-03-04",
                    "board_key": "robotics",
                },
            },
            "2026-03-06|robotics": {
                "reason_text": "day3 reason",
                "reason_ref": {
                    "trade_date": "2026-03-06",
                    "board_key": "robotics",
                },
            },
        },
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get("/api/gantt/plates?provider=jygs&days=3&end_date=2026-03-06")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["dates"] == ["2026-03-04", "2026-03-05", "2026-03-06"]
    assert [item[0] for item in payload["data"]["series"]] == [0, 2]


def test_get_gantt_stocks_requires_plate_key():
    from freshquant.rear.gantt import routes as gantt_routes

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get("/api/gantt/stocks?provider=xgb")

    assert response.status_code == 400
    assert response.get_json()["message"] == "plate_key required"


def test_get_gantt_stock_reasons_requires_code6():
    from freshquant.rear.gantt import routes as gantt_routes

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get("/api/gantt/stocks/reasons?provider=all")

    assert response.status_code == 400
    assert response.get_json()["message"] == "code6 required"


def test_get_gantt_stock_reasons_reads_stock_hot_reason_rows(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    called = {}

    def fake_query_stock_hot_reason_rows(*, code6, provider, limit):
        called.update({"code6": code6, "provider": provider, "limit": limit})
        return [
            {
                "date": "2026-03-05",
                "time": "09:31",
                "provider": "xgb",
                "plate_name": "robotics",
                "plate_reason": "xgb plate reason",
                "stock_reason": "xgb stock reason",
            }
        ]

    monkeypatch.setattr(
        gantt_routes.svc,
        "query_stock_hot_reason_rows",
        fake_query_stock_hot_reason_rows,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get("/api/gantt/stocks/reasons?code6=000001&provider=all")

    assert response.status_code == 200
    assert called == {"code6": "000001", "provider": "all", "limit": 0}
    assert response.get_json()["data"]["items"] == [
        {
            "date": "2026-03-05",
            "time": "09:31",
            "provider": "xgb",
            "plate_name": "robotics",
            "plate_reason": "xgb plate reason",
            "stock_reason": "xgb stock reason",
        }
    ]


def test_get_gantt_plates_rejects_invalid_end_date(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    fake_db = _fake_db(
        gantt_plate_daily=[
            {
                "provider": "xgb",
                "trade_date": "2026-03-05",
                "plate_key": "11",
                "plate_name": "robotics",
                "rank": 1,
                "hot_stock_count": 8,
                "limit_up_count": 3,
                "stock_codes": ["000001"],
            }
        ]
    )
    monkeypatch.setattr(gantt_routes.svc, "DBGantt", fake_db)

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get("/api/gantt/plates?provider=xgb&end_date=20260305")

    assert response.status_code == 400
    assert response.get_json()["message"] == "end_date must be YYYY-MM-DD"


def test_get_gantt_stocks_rejects_invalid_end_date(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    fake_db = _fake_db(
        gantt_stock_daily=[
            {
                "provider": "xgb",
                "trade_date": "2026-03-05",
                "plate_key": "11",
                "plate_name": "robotics",
                "code6": "000001",
                "name": "alpha",
                "is_limit_up": 1,
                "stock_reason": "stock reason",
            }
        ]
    )
    monkeypatch.setattr(gantt_routes.svc, "DBGantt", fake_db)

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get(
        "/api/gantt/stocks?provider=xgb&plate_key=11&end_date=20260305"
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "end_date must be YYYY-MM-DD"

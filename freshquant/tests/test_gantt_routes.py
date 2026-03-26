import types
import sys
from datetime import datetime

from flask import Flask

svc_module = types.ModuleType("freshquant.data.gantt_readmodel")
svc_module.DBGantt = {}
svc_module.get_trade_dates_between = lambda start_date, end_date: []
svc_module.query_gantt_plate_matrix = lambda **kwargs: {}
svc_module.query_gantt_plate_reason_map = lambda **kwargs: {}
svc_module.query_gantt_stock_matrix = lambda **kwargs: {}
svc_module.query_stock_hot_reason_rows = lambda **kwargs: []
svc_module.query_shouban30_plate_rows = lambda **kwargs: []
svc_module.query_shouban30_stock_rows = lambda **kwargs: []
sys.modules.setdefault("freshquant.data.gantt_readmodel", svc_module)

shouban_module = types.ModuleType("freshquant.shouban30_pool_service")
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
sys.modules.setdefault("freshquant.shouban30_pool_service", shouban_module)


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


def test_get_shouban30_plates_reads_days_and_end_date(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    seen = {}

    def query_shouban30_plate_rows_stub(**kwargs):
        seen["kwargs"] = kwargs
        return [
            {
                "provider": "xgb",
                "as_of_date": "2026-03-05",
                "stock_window_days": 60,
                "plate_key": "22",
                "stocks_count": 1,
                "candidate_stocks_count": 2,
                "failed_stocks_count": 1,
                "chanlun_filter_version": "30m_v1",
            }
        ]

    monkeypatch.setattr(
        gantt_routes.svc,
        "query_shouban30_plate_rows",
        query_shouban30_plate_rows_stub,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get(
        "/api/gantt/shouban30/plates?provider=xgb&days=60&end_date=2026-03-05"
    )

    assert response.status_code == 200
    assert seen["kwargs"] == {
        "provider": "xgb",
        "days": 60,
        "end_date": "2026-03-05",
    }
    payload = response.get_json()
    assert payload["data"]["items"] == [
        {
            "provider": "xgb",
            "as_of_date": "2026-03-05",
            "stock_window_days": 60,
            "plate_key": "22",
            "stocks_count": 1,
            "candidate_stocks_count": 2,
            "failed_stocks_count": 1,
            "chanlun_filter_version": "30m_v1",
        }
    ]
    assert payload["data"]["meta"] == {
        "days": 60,
        "end_date": "2026-03-05",
        "as_of_date": "2026-03-05",
        "stock_window_days": 60,
        "chanlun_filter_version": "30m_v1",
    }


def test_get_shouban30_stocks_accepts_legacy_as_of_date_and_stock_window_days(
    monkeypatch,
):
    from freshquant.rear.gantt import routes as gantt_routes

    seen = {}

    def query_shouban30_stock_rows_stub(**kwargs):
        seen["kwargs"] = kwargs
        return []

    monkeypatch.setattr(
        gantt_routes.svc,
        "query_shouban30_stock_rows",
        query_shouban30_stock_rows_stub,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get(
        "/api/gantt/shouban30/stocks?provider=xgb&plate_key=11&as_of_date=2026-03-05&stock_window_days=90"
    )

    assert response.status_code == 200
    assert seen["kwargs"] == {
        "provider": "xgb",
        "plate_key": "11",
        "days": 90,
        "end_date": "2026-03-05",
    }
    assert response.get_json()["data"]["meta"] == {
        "days": 90,
        "end_date": "2026-03-05",
        "as_of_date": "2026-03-05",
        "stock_window_days": 90,
        "chanlun_filter_version": None,
    }


def test_get_shouban30_plates_meta_keeps_requested_end_date_and_actual_snapshot_date(
    monkeypatch,
):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes.svc,
        "query_shouban30_plate_rows",
        lambda **kwargs: [
            {
                "provider": "xgb",
                "as_of_date": "2026-03-07",
                "stock_window_days": 30,
                "plate_key": "11",
                "stocks_count": 1,
                "candidate_stocks_count": 1,
                "failed_stocks_count": 0,
                "chanlun_filter_version": "30m_v1",
            }
        ],
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get(
        "/api/gantt/shouban30/plates?provider=xgb&days=30&end_date=2026-03-08"
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["meta"] == {
        "days": 30,
        "end_date": "2026-03-08",
        "as_of_date": "2026-03-07",
        "stock_window_days": 30,
        "chanlun_filter_version": "30m_v1",
    }


def test_get_shouban30_stocks_returns_empty_when_missing(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    fake_db = _fake_db(shouban30_stocks=[])
    monkeypatch.setattr(gantt_routes.svc, "DBGantt", fake_db)

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get(
        "/api/gantt/shouban30/stocks?provider=xgb&plate_key=11&as_of_date=2026-03-05&stock_window_days=90"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["items"] == []
    assert payload["data"]["meta"] == {
        "days": 90,
        "end_date": "2026-03-05",
        "as_of_date": "2026-03-05",
        "stock_window_days": 90,
        "chanlun_filter_version": None,
    }


def test_get_shouban30_stocks_returns_chanlun_snapshot_fields(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes.svc,
        "query_shouban30_stock_rows",
        lambda **kwargs: [
            {
                "provider": "xgb",
                "plate_key": "11",
                "code6": "000001",
                "as_of_date": "2026-03-05",
                "stock_window_days": 60,
                "chanlun_passed": True,
                "chanlun_reason": "passed",
                "chanlun_higher_multiple": 2.0,
                "chanlun_segment_multiple": 2.5,
                "chanlun_bi_gain_percent": 20.0,
                "chanlun_filter_version": "30m_v1",
                "is_credit_subject": True,
                "credit_subject_snapshot_ready": True,
                "near_long_term_ma_passed": True,
                "near_long_term_ma_basis": "ma250",
                "close_price": 103.0,
                "ma250": 100.0,
                "ma500": 99.0,
                "ma1000": 98.0,
                "ma250_distance_pct": 3.0,
                "ma500_distance_pct": 4.0404,
                "ma1000_distance_pct": 5.102,
                "is_quality_subject": False,
                "quality_subject_snapshot_ready": True,
                "quality_subject_source_version": "xgt_hot_blocks_v1",
            }
        ],
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get(
        "/api/gantt/shouban30/stocks?provider=xgb&plate_key=11&as_of_date=2026-03-05&stock_window_days=60"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["items"] == [
        {
            "provider": "xgb",
            "plate_key": "11",
            "code6": "000001",
            "as_of_date": "2026-03-05",
            "stock_window_days": 60,
            "chanlun_passed": True,
            "chanlun_reason": "passed",
            "chanlun_higher_multiple": 2.0,
            "chanlun_segment_multiple": 2.5,
            "chanlun_bi_gain_percent": 20.0,
            "chanlun_filter_version": "30m_v1",
            "is_credit_subject": True,
            "credit_subject_snapshot_ready": True,
            "near_long_term_ma_passed": True,
            "near_long_term_ma_basis": "ma250",
            "close_price": 103.0,
            "ma250": 100.0,
            "ma500": 99.0,
            "ma1000": 98.0,
            "ma250_distance_pct": 3.0,
            "ma500_distance_pct": 4.0404,
            "ma1000_distance_pct": 5.102,
            "is_quality_subject": False,
            "quality_subject_snapshot_ready": True,
            "quality_subject_source_version": "xgt_hot_blocks_v1",
        }
    ]
    assert payload["data"]["meta"] == {
        "days": 60,
        "end_date": "2026-03-05",
        "as_of_date": "2026-03-05",
        "stock_window_days": 60,
        "chanlun_filter_version": "30m_v1",
    }


def test_get_shouban30_plates_returns_409_when_chanlun_snapshot_not_ready(
    monkeypatch,
):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes.svc,
        "query_shouban30_plate_rows",
        lambda **kwargs: (_ for _ in ()).throw(
            ValueError("shouban30 chanlun snapshot not ready")
        ),
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get(
        "/api/gantt/shouban30/plates?provider=xgb&as_of_date=2026-03-05&stock_window_days=60"
    )

    assert response.status_code == 409
    assert response.get_json()["message"] == "shouban30 chanlun snapshot not ready"


def test_get_shouban30_plates_rejects_invalid_days():
    from freshquant.rear.gantt import routes as gantt_routes

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get("/api/gantt/shouban30/plates?provider=xgb&days=15")

    assert response.status_code == 400
    assert response.get_json()["message"] == "days must be one of 30|45|60|90"


def test_replace_shouban30_pre_pool_requires_items(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes,
        "shouban30_pool_service",
        types.SimpleNamespace(),
        raising=False,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.post("/api/gantt/shouban30/pre-pool/replace", json={})

    assert response.status_code == 400
    assert response.get_json()["message"] == "items required"


def test_replace_shouban30_pre_pool_returns_blk_sync_meta(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    def fake_replace(items, context):
        assert items == [{"code6": "600001", "name": "alpha"}]
        assert context == {
            "replace_scope": "current_filter",
            "days": 30,
            "end_date": "2026-03-06",
            "stock_window_days": 30,
            "as_of_date": "2026-03-06",
            "selected_extra_filters": ["chanlun_passed"],
            "plate_key": "",
        }
        return {
            "saved_count": 1,
            "deleted_count": 2,
            "category": "三十涨停Pro预选",
            "blk_sync": {
                "success": True,
                "file_path": "D:/tdx/T0002/blocknew/30RYZT.blk",
                "count": 1,
            },
        }

    monkeypatch.setattr(
        gantt_routes,
        "shouban30_pool_service",
        types.SimpleNamespace(replace_pre_pool=fake_replace),
        raising=False,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.post(
        "/api/gantt/shouban30/pre-pool/replace",
        json={
            "items": [{"code6": "600001", "name": "alpha"}],
            "replace_scope": "current_filter",
            "days": 30,
            "end_date": "2026-03-06",
            "selected_extra_filters": ["chanlun_passed"],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"] == {
        "saved_count": 1,
        "deleted_count": 2,
        "category": "三十涨停Pro预选",
    }
    assert payload["meta"] == {
        "blk_sync": {
            "success": True,
            "file_path": "D:/tdx/T0002/blocknew/30RYZT.blk",
            "count": 1,
        }
    }


def test_append_shouban30_pre_pool_returns_append_counts(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    def fake_append(items, context):
        assert items == [{"code6": "600001", "name": "alpha"}]
        assert context == {
            "replace_scope": "single_plate",
            "days": 30,
            "end_date": "2026-03-06",
            "stock_window_days": 30,
            "as_of_date": "2026-03-06",
            "selected_extra_filters": ["chanlun_passed"],
            "plate_key": "11",
        }
        return {
            "appended_count": 1,
            "skipped_count": 0,
            "category": "三十涨停Pro预选",
        }

    monkeypatch.setattr(
        gantt_routes,
        "shouban30_pool_service",
        types.SimpleNamespace(append_pre_pool=fake_append),
        raising=False,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.post(
        "/api/gantt/shouban30/pre-pool/append",
        json={
            "items": [{"code6": "600001", "name": "alpha"}],
            "replace_scope": "single_plate",
            "days": 30,
            "end_date": "2026-03-06",
            "selected_extra_filters": ["chanlun_passed"],
            "plate_key": "11",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "appended_count": 1,
        "skipped_count": 0,
        "category": "三十涨停Pro预选",
    }


def test_list_shouban30_pre_pool_reads_workspace_items(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes,
        "shouban30_pool_service",
        types.SimpleNamespace(
            SHOUBAN30_PRE_POOL_CATEGORY="三十涨停Pro预选",
            SHOUBAN30_BLK_FILENAME="30RYZT.blk",
            list_pre_pool=lambda: [
                {
                    "code6": "600001",
                    "name": "alpha",
                    "category": "三十涨停Pro预选",
                }
            ],
        ),
        raising=False,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get("/api/gantt/shouban30/pre-pool")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["items"] == [
        {
            "code6": "600001",
            "name": "alpha",
            "category": "三十涨停Pro预选",
        }
    ]
    assert payload["meta"] == {
        "category": "三十涨停Pro预选",
        "blk_filename": "30RYZT.blk",
    }


def test_add_shouban30_pre_pool_item_to_stock_pool(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes,
        "shouban30_pool_service",
        types.SimpleNamespace(
            add_pre_pool_item_to_stock_pool=lambda code6: (
                "created" if code6 == "600001" else "unexpected"
            )
        ),
        raising=False,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.post(
        "/api/gantt/shouban30/pre-pool/add-to-stock-pools",
        json={"code6": "600001"},
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == {"status": "created"}


def test_sync_shouban30_pre_pool_to_stock_pool_returns_counts(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes,
        "shouban30_pool_service",
        types.SimpleNamespace(
            sync_pre_pool_to_stock_pool=lambda: {
                "appended_count": 2,
                "skipped_count": 1,
                "category": "三十涨停Pro自选",
            }
        ),
        raising=False,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.post("/api/gantt/shouban30/pre-pool/sync-to-stock-pool")

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "appended_count": 2,
        "skipped_count": 1,
        "category": "三十涨停Pro自选",
    }


def test_sync_shouban30_pre_pool_to_tdx_returns_blk_sync_meta(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes,
        "shouban30_pool_service",
        types.SimpleNamespace(
            sync_pre_pool_to_blk=lambda: {
                "success": True,
                "file_path": "D:/tdx_biduan/T0002/blocknew/30RYZT.blk",
                "count": 3,
            }
        ),
        raising=False,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.post("/api/gantt/shouban30/pre-pool/sync-to-tdx")

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "blk_sync": {
            "success": True,
            "file_path": "D:/tdx_biduan/T0002/blocknew/30RYZT.blk",
            "count": 3,
        }
    }


def test_clear_shouban30_pre_pool_returns_blk_sync_meta(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes,
        "shouban30_pool_service",
        types.SimpleNamespace(
            clear_pre_pool=lambda: {
                "deleted_count": 2,
                "category": "三十涨停Pro预选",
                "blk_sync": {
                    "success": True,
                    "file_path": "D:/tdx_biduan/T0002/blocknew/30RYZT.blk",
                    "count": 0,
                },
            }
        ),
        raising=False,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.post("/api/gantt/shouban30/pre-pool/clear")

    assert response.status_code == 200
    assert response.get_json() == {
        "data": {
            "deleted_count": 2,
            "category": "三十涨停Pro预选",
        },
        "meta": {
            "blk_sync": {
                "success": True,
                "file_path": "D:/tdx_biduan/T0002/blocknew/30RYZT.blk",
                "count": 0,
            }
        },
    }


def test_add_shouban30_stock_pool_item_to_must_pool(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes,
        "shouban30_pool_service",
        types.SimpleNamespace(
            add_stock_pool_item_to_must_pool=lambda code6: (
                "created" if code6 == "600001" else "unexpected"
            )
        ),
        raising=False,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.post(
        "/api/gantt/shouban30/stock-pool/add-to-must-pool",
        json={"code6": "600001"},
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == {"status": "created"}


def test_sync_shouban30_stock_pool_to_must_pool_returns_counts(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes,
        "shouban30_pool_service",
        types.SimpleNamespace(
            sync_stock_pool_to_must_pool=lambda: {
                "created_count": 1,
                "updated_count": 2,
                "total_count": 3,
                "category": "三十涨停Pro",
            }
        ),
        raising=False,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.post("/api/gantt/shouban30/stock-pool/sync-to-must-pool")

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "created_count": 1,
        "updated_count": 2,
        "total_count": 3,
    }


def test_sync_shouban30_stock_pool_to_tdx_returns_blk_sync_meta(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes,
        "shouban30_pool_service",
        types.SimpleNamespace(
            sync_stock_pool_to_blk=lambda: {
                "success": True,
                "file_path": "D:/tdx_biduan/T0002/blocknew/30RYZT.blk",
                "count": 2,
            }
        ),
        raising=False,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.post("/api/gantt/shouban30/stock-pool/sync-to-tdx")

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "blk_sync": {
            "success": True,
            "file_path": "D:/tdx_biduan/T0002/blocknew/30RYZT.blk",
            "count": 2,
        }
    }


def test_clear_shouban30_stock_pool_returns_blk_sync_meta(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes,
        "shouban30_pool_service",
        types.SimpleNamespace(
            clear_stock_pool=lambda: {
                "deleted_count": 0,
                "category": "三十涨停Pro自选",
                "blk_sync": {
                    "success": True,
                    "file_path": "D:/tdx_biduan/T0002/blocknew/30RYZT.blk",
                    "count": 0,
                },
            }
        ),
        raising=False,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.post("/api/gantt/shouban30/stock-pool/clear")

    assert response.status_code == 200
    assert response.get_json() == {
        "data": {
            "deleted_count": 0,
            "category": "三十涨停Pro自选",
        },
        "meta": {
            "blk_sync": {
                "success": True,
                "file_path": "D:/tdx_biduan/T0002/blocknew/30RYZT.blk",
                "count": 0,
            }
        },
    }


def test_sync_shouban30_must_pool_to_tdx_returns_blk_sync(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes,
        "shouban30_pool_service",
        types.SimpleNamespace(
            sync_must_pool_to_blk=lambda: {
                "success": True,
                "file_path": "D:/tdx_biduan/T0002/blocknew/30RYZT.blk",
                "count": 3,
            }
        ),
        raising=False,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.post("/api/gantt/shouban30/must-pool/sync-to-tdx")

    assert response.status_code == 200
    assert response.get_json() == {
        "data": {
            "blk_sync": {
                "success": True,
                "file_path": "D:/tdx_biduan/T0002/blocknew/30RYZT.blk",
                "count": 3,
            }
        }
    }


def test_clear_shouban30_must_pool_returns_blk_sync_meta(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    monkeypatch.setattr(
        gantt_routes,
        "shouban30_pool_service",
        types.SimpleNamespace(
            clear_must_pool=lambda: {
                "deleted_count": 2,
                "blk_sync": {
                    "success": True,
                    "file_path": "D:/tdx_biduan/T0002/blocknew/30RYZT.blk",
                    "count": 0,
                },
            }
        ),
        raising=False,
    )

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.post("/api/gantt/shouban30/must-pool/clear")

    assert response.status_code == 200
    assert response.get_json() == {
        "data": {
            "deleted_count": 2,
        },
        "meta": {
            "blk_sync": {
                "success": True,
                "file_path": "D:/tdx_biduan/T0002/blocknew/30RYZT.blk",
                "count": 0,
            }
        },
    }

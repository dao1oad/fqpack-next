from flask import Flask


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

    fake_db = _fake_db(
        gantt_plate_daily=[
            {
                "provider": "xgb",
                "trade_date": "2026-03-04",
                "plate_key": "11",
                "plate_name": "robotics",
                "rank": 2,
                "hot_stock_count": 5,
                "limit_up_count": 1,
                "stock_codes": ["000001", "000002"],
                "reason_text": "day1 reason",
                "reason_ref": {"trade_date": "2026-03-04", "plate_id": 11},
            },
            {
                "provider": "xgb",
                "trade_date": "2026-03-05",
                "plate_key": "11",
                "plate_name": "robotics",
                "rank": 1,
                "hot_stock_count": 8,
                "limit_up_count": 3,
                "stock_codes": ["000001", "000002", "000003"],
                "reason_text": "day2 reason",
                "reason_ref": {"trade_date": "2026-03-05", "plate_id": 11},
            },
        ]
    )
    monkeypatch.setattr(gantt_routes.svc, "DBGantt", fake_db)

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


def test_get_shouban30_plates_reads_as_of_date(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    fake_db = _fake_db(
        shouban30_plates=[
            {"provider": "xgb", "as_of_date": "2026-03-04", "plate_key": "11"},
            {"provider": "xgb", "as_of_date": "2026-03-05", "plate_key": "22"},
        ]
    )
    monkeypatch.setattr(gantt_routes.svc, "DBGantt", fake_db)

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get(
        "/api/gantt/shouban30/plates?provider=xgb&as_of_date=2026-03-05"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["items"] == [
        {"provider": "xgb", "as_of_date": "2026-03-05", "plate_key": "22"}
    ]


def test_get_shouban30_stocks_returns_empty_when_missing(monkeypatch):
    from freshquant.rear.gantt import routes as gantt_routes

    fake_db = _fake_db(shouban30_stocks=[])
    monkeypatch.setattr(gantt_routes.svc, "DBGantt", fake_db)

    app = Flask(__name__)
    app.register_blueprint(gantt_routes.gantt_bp)
    client = app.test_client()
    response = client.get(
        "/api/gantt/shouban30/stocks?provider=xgb&plate_key=11&as_of_date=2026-03-05"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["items"] == []

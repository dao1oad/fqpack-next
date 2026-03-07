from freshquant.data.gantt_source_xgb import normalize_xgb_history_row


def test_xgb_history_row_keeps_plate_description_as_reason_source():
    raw = {
        "trade_date": "2026-03-05",
        "plate_id": 1234,
        "plate_name": "robotics",
        "description": "core automation theme",
        "rank": 1,
        "hot_stocks": [{"symbol": "000001", "stock_name": "sample"}],
    }

    row = normalize_xgb_history_row(raw)

    assert row["provider"] == "xgb"
    assert row["plate_key"] == "1234"
    assert row["reason_text"] == "core automation theme"
    assert row["reason_source"] == "xgb_top_gainer_history.description"


class FakeCollection:
    def __init__(self):
        self.docs = []

    def create_index(self, *args, **kwargs):
        return None

    def update_one(self, query, update, upsert=False):
        target = None
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                target = doc
                break
        if target is None:
            target = dict(query)
            self.docs.append(target)
        target.update(update.get("$set", {}))

    def delete_many(self, query):
        self.docs = [
            doc
            for doc in self.docs
            if not all(doc.get(key) == value for key, value in query.items())
        ]


class FakeDB(dict):
    def __getitem__(self, name):
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def test_sync_xgb_history_for_date_writes_dbgantt(monkeypatch):
    from freshquant.data import gantt_source_xgb as svc

    def fake_fetch_json(url, params=None):
        if url.endswith("/surge_stock/plates"):
            return {
                "data": {
                    "items": [
                        {"id": 11, "name": "robotics", "description": "plate reason"}
                    ]
                }
            }
        if url.endswith("/plate/data"):
            return {
                "data": {
                    "11": {
                        "plate_name": "robotics",
                        "limit_up_count": 2,
                    }
                }
            }
        if url.endswith("/surge_stock/stocks"):
            return {
                "data": {
                    "fields": [
                        "code",
                        "prod_name",
                        "description",
                        "plates",
                        "up_limit",
                    ],
                    "items": [
                        [
                            "000001",
                            "alpha",
                            "stock reason",
                            [{"id": 11, "name": "robotics"}],
                            1,
                        ]
                    ],
                }
            }
        raise AssertionError(url)

    fake_db = FakeDB()
    monkeypatch.setattr(svc, "DBGantt", fake_db)
    monkeypatch.setattr(svc, "_fetch_json", fake_fetch_json)

    count = svc.sync_xgb_history_for_date("2026-03-05")

    assert count == 1
    assert fake_db[svc.COL_XGB_TOP_GAINER_HISTORY].docs == [
        {
            "trade_date": "2026-03-05",
            "plate_id": 11,
            "plate_name": "robotics",
            "description": "plate reason",
            "limit_up_count": 2,
            "rank": 1,
            "hot_stocks": [
                {
                    "symbol": "000001",
                    "stock_name": "alpha",
                    "description": "stock reason",
                    "up_limit": 1,
                    "plates": [{"id": 11, "name": "robotics"}],
                }
            ],
            "provider": "xgb",
        }
    ]


def test_sync_xgb_history_for_date_uses_plate_set_desc_and_skips_others(monkeypatch):
    from freshquant.data import gantt_source_xgb as svc

    def fake_fetch_json(url, params=None):
        if url.endswith("/surge_stock/plates"):
            return {
                "data": {
                    "items": [
                        {"id": -1, "name": "其他", "description": ""},
                        {"id": 11, "name": "robotics", "description": ""},
                    ]
                }
            }
        if url.endswith("/plate/data"):
            return {
                "data": {
                    "-1": {"plate_name": "其他", "limit_up_count": 0},
                    "11": {"plate_name": "robotics", "limit_up_count": 2},
                }
            }
        if url.endswith("/plate/plate_set"):
            assert params == {"id": 11}
            return {"data": {"name": "robotics", "desc": "detail reason"}}
        if url.endswith("/surge_stock/stocks"):
            return {"data": {"fields": [], "items": []}}
        raise AssertionError(url)

    fake_db = FakeDB()
    monkeypatch.setattr(svc, "DBGantt", fake_db)
    monkeypatch.setattr(svc, "_fetch_json", fake_fetch_json)

    count = svc.sync_xgb_history_for_date("2026-03-05")

    assert count == 1
    assert fake_db[svc.COL_XGB_TOP_GAINER_HISTORY].docs == [
        {
            "trade_date": "2026-03-05",
            "plate_id": 11,
            "plate_name": "robotics",
            "description": "detail reason",
            "limit_up_count": 2,
            "rank": 2,
            "hot_stocks": [],
            "provider": "xgb",
        }
    ]


def test_sync_xgb_history_for_date_skips_synthetic_announcement_bucket(monkeypatch):
    from freshquant.data import gantt_source_xgb as svc

    def fake_fetch_json(url, params=None):
        if url.endswith("/surge_stock/plates"):
            return {
                "data": {
                    "items": [
                        {"id": -1, "name": "公告", "description": ""},
                        {"id": 11, "name": "robotics", "description": ""},
                    ]
                }
            }
        if url.endswith("/plate/data"):
            return {
                "data": {
                    "-1": {"plate_name": "公告", "limit_up_count": 0},
                    "11": {"plate_name": "robotics", "limit_up_count": 2},
                }
            }
        if url.endswith("/plate/plate_set"):
            assert params == {"id": 11}
            return {"data": {"name": "robotics", "desc": "detail reason"}}
        if url.endswith("/surge_stock/stocks"):
            return {"data": {"fields": [], "items": []}}
        raise AssertionError(url)

    fake_db = FakeDB()
    monkeypatch.setattr(svc, "DBGantt", fake_db)
    monkeypatch.setattr(svc, "_fetch_json", fake_fetch_json)

    count = svc.sync_xgb_history_for_date("2026-03-05")

    assert count == 1
    assert fake_db[svc.COL_XGB_TOP_GAINER_HISTORY].docs == [
        {
            "trade_date": "2026-03-05",
            "plate_id": 11,
            "plate_name": "robotics",
            "description": "detail reason",
            "limit_up_count": 2,
            "rank": 2,
            "hot_stocks": [],
            "provider": "xgb",
        }
    ]


def test_sync_xgb_history_for_date_replaces_stale_rows(monkeypatch):
    from freshquant.data import gantt_source_xgb as svc

    def fake_fetch_json(url, params=None):
        if url.endswith("/surge_stock/plates"):
            return {
                "data": {
                    "items": [
                        {"id": 11, "name": "robotics", "description": "plate reason"}
                    ]
                }
            }
        if url.endswith("/plate/data"):
            return {
                "data": {
                    "11": {
                        "plate_name": "robotics",
                        "limit_up_count": 2,
                    }
                }
            }
        if url.endswith("/surge_stock/stocks"):
            return {"data": {"fields": [], "items": []}}
        raise AssertionError(url)

    fake_db = FakeDB()
    fake_db[svc.COL_XGB_TOP_GAINER_HISTORY].docs = [
        {
            "trade_date": "2026-03-05",
            "plate_id": 99,
            "plate_name": "stale plate",
            "description": "stale reason",
            "provider": "xgb",
        }
    ]
    monkeypatch.setattr(svc, "DBGantt", fake_db)
    monkeypatch.setattr(svc, "_fetch_json", fake_fetch_json)

    svc.sync_xgb_history_for_date("2026-03-05")

    assert fake_db[svc.COL_XGB_TOP_GAINER_HISTORY].docs == [
        {
            "trade_date": "2026-03-05",
            "plate_id": 11,
            "plate_name": "robotics",
            "description": "plate reason",
            "limit_up_count": 2,
            "rank": 1,
            "hot_stocks": [],
            "provider": "xgb",
        }
    ]

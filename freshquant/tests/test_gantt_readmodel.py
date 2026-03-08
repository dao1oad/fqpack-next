import pytest

from freshquant.data.gantt_readmodel import (
    _build_xgb_gantt_rows,
    _group_shouban30_plate_candidates,
    build_plate_reason_daily,
    build_shouban30_plate_rows,
    build_stock_hot_reason_rows,
    select_shouban30_plate_rows,
    select_shouban30_stock_rows,
)


def test_build_plate_reason_daily_uses_xgb_description():
    rows = build_plate_reason_daily(
        xgb_history_rows=[
            {
                "trade_date": "2026-03-05",
                "plate_id": 11,
                "plate_name": "robotics",
                "description": "xgb reason",
            }
        ],
        jygs_action_rows=[],
    )

    assert rows == [
        {
            "provider": "xgb",
            "trade_date": "2026-03-05",
            "plate_key": "11",
            "plate_name": "robotics",
            "reason_text": "xgb reason",
            "reason_source": "xgb_top_gainer_history.description",
            "source_ref": {"trade_date": "2026-03-05", "plate_id": 11},
        }
    ]


def test_build_plate_reason_daily_uses_jygs_action_reason():
    rows = build_plate_reason_daily(
        xgb_history_rows=[],
        jygs_action_rows=[
            {
                "action_field_id": "f-1",
                "name": "robotics*12",
                "reason": "jygs reason",
                "count": 12,
            }
        ],
        trade_date="2026-03-05",
    )

    assert rows == [
        {
            "provider": "jygs",
            "trade_date": "2026-03-05",
            "plate_key": "robotics",
            "plate_name": "robotics",
            "reason_text": "jygs reason",
            "reason_source": "jygs_action_fields.reason",
            "source_ref": {
                "trade_date": "2026-03-05",
                "board_key": "robotics",
                "action_field_id": "f-1",
            },
        }
    ]


def test_build_plate_reason_daily_fails_when_reason_missing():
    with pytest.raises(ValueError, match="reason_text"):
        build_plate_reason_daily(
            xgb_history_rows=[
                {
                    "trade_date": "2026-03-05",
                    "plate_id": 11,
                    "plate_name": "robotics",
                    "description": "",
                }
            ],
            jygs_action_rows=[],
        )


def test_build_shouban30_joins_reason_from_plate_reason_daily_only():
    rows = build_shouban30_plate_rows(
        plate_rows=[
            {
                "provider": "xgb",
                "plate_key": "11",
                "plate_name": "robotics",
                "seg_to": "2026-03-05",
                "appear_days_30": 2,
                "seg_from": "2026-03-04",
                "hit_trade_dates_30": ["2026-03-04", "2026-03-05"],
                "stock_window_days": 60,
                "stocks_count": 8,
                "stock_window_from": "2026-01-06",
                "stock_window_to": "2026-03-05",
            }
        ],
        plate_reason_rows=[
            {
                "provider": "xgb",
                "plate_key": "11",
                "trade_date": "2026-03-05",
                "plate_name": "robotics",
                "reason_text": "canonical reason",
                "reason_source": "xgb_top_gainer_history.description",
                "source_ref": {"trade_date": "2026-03-05", "plate_id": 11},
            }
        ],
        as_of_date="2026-03-05",
    )

    assert rows[0]["reason_text"] == "canonical reason"
    assert rows[0]["reason_ref"] == {
        "trade_date": "2026-03-05",
        "plate_id": 11,
    }
    assert rows[0]["stock_window_days"] == 60
    assert rows[0]["stocks_count"] == 8
    assert rows[0]["hit_trade_dates_30"] == ["2026-03-04", "2026-03-05"]


def test_build_shouban30_fails_when_plate_reason_is_missing():
    with pytest.raises(ValueError, match="missing plate reason"):
        build_shouban30_plate_rows(
            plate_rows=[
                {
                    "provider": "xgb",
                    "plate_key": "11",
                    "plate_name": "robotics",
                    "seg_to": "2026-03-05",
                    "appear_days_30": 2,
                    "seg_from": "2026-03-04",
                    "stock_window_days": 60,
                    "stocks_count": 8,
                    "stock_window_from": "2026-01-06",
                    "stock_window_to": "2026-03-05",
                }
            ],
            plate_reason_rows=[],
            as_of_date="2026-03-05",
        )


def test_select_shouban30_plate_rows_distinguishes_stock_window_days():
    rows = [
        {
            "provider": "xgb",
            "plate_key": "11",
            "as_of_date": "2026-03-07",
            "stock_window_days": 30,
            "plate_name": "robotics-30",
        },
        {
            "provider": "xgb",
            "plate_key": "11",
            "as_of_date": "2026-03-07",
            "stock_window_days": 60,
            "plate_name": "robotics-60",
        },
    ]

    items = select_shouban30_plate_rows(
        rows,
        provider="xgb",
        as_of_date="2026-03-07",
        stock_window_days=60,
    )

    assert items == [rows[1]]


def test_select_shouban30_stock_rows_distinguishes_stock_window_days():
    rows = [
        {
            "provider": "xgb",
            "plate_key": "11",
            "code6": "000001",
            "as_of_date": "2026-03-07",
            "stock_window_days": 30,
        },
        {
            "provider": "xgb",
            "plate_key": "11",
            "code6": "000001",
            "as_of_date": "2026-03-07",
            "stock_window_days": 90,
        },
    ]

    items = select_shouban30_stock_rows(
        rows,
        provider="xgb",
        plate_key="11",
        as_of_date="2026-03-07",
        stock_window_days=90,
    )

    assert items == [rows[1]]


def test_group_shouban30_plate_candidates_uses_trade_date_axis():
    items = _group_shouban30_plate_candidates(
        [
            {
                "provider": "xgb",
                "plate_key": "11",
                "plate_name": "robotics",
                "trade_date": "2026-03-06",
            },
            {
                "provider": "xgb",
                "plate_key": "11",
                "plate_name": "robotics",
                "trade_date": "2026-03-09",
            },
        ],
        as_of_date="2026-03-09",
        trade_dates=["2026-03-06", "2026-03-09"],
    )

    assert items == [
        {
            "provider": "xgb",
            "plate_key": "11",
            "plate_name": "robotics",
            "appear_days_30": 2,
            "seg_from": "2026-03-06",
            "seg_to": "2026-03-09",
            "hit_trade_dates_30": ["2026-03-06", "2026-03-09"],
        }
    ]


def test_build_stock_hot_reason_rows_joins_plate_reason_and_sorts_desc():
    rows = build_stock_hot_reason_rows(
        gantt_stock_rows=[
            {
                "provider": "xgb",
                "trade_date": "2026-03-05",
                "plate_key": "11",
                "plate_name": "robotics",
                "code6": "000001",
                "name": "alpha",
                "stock_reason": "xgb stock reason",
                "time": "09:31",
            },
            {
                "provider": "xgb",
                "trade_date": "2026-03-04",
                "plate_key": "11",
                "plate_name": "robotics",
                "code6": "000001",
                "name": "alpha",
                "stock_reason": "older stock reason",
                "time": "14:00",
            },
            {
                "provider": "jygs",
                "trade_date": "2026-03-05",
                "plate_key": "robotics",
                "plate_name": "robotics",
                "code6": "000001",
                "name": "alpha",
                "stock_reason": "jygs stock reason",
                "time": "",
            },
        ],
        plate_reason_rows=[
            {
                "provider": "xgb",
                "trade_date": "2026-03-05",
                "plate_key": "11",
                "plate_name": "robotics",
                "reason_text": "xgb plate reason",
                "source_ref": {"trade_date": "2026-03-05", "plate_id": 11},
            },
            {
                "provider": "xgb",
                "trade_date": "2026-03-04",
                "plate_key": "11",
                "plate_name": "robotics",
                "reason_text": "older plate reason",
                "source_ref": {"trade_date": "2026-03-04", "plate_id": 11},
            },
            {
                "provider": "jygs",
                "trade_date": "2026-03-05",
                "plate_key": "robotics",
                "plate_name": "robotics",
                "reason_text": "jygs plate reason",
                "source_ref": {
                    "trade_date": "2026-03-05",
                    "board_key": "robotics",
                    "action_field_id": "field-1",
                },
            },
        ],
    )

    assert rows == [
        {
            "trade_date": "2026-03-05",
            "provider": "xgb",
            "code6": "000001",
            "name": "alpha",
            "plate_key": "11",
            "plate_name": "robotics",
            "plate_reason": "xgb plate reason",
            "stock_reason": "xgb stock reason",
            "time": "09:31",
            "reason_ref": {"trade_date": "2026-03-05", "plate_id": 11},
        },
        {
            "trade_date": "2026-03-05",
            "provider": "jygs",
            "code6": "000001",
            "name": "alpha",
            "plate_key": "robotics",
            "plate_name": "robotics",
            "plate_reason": "jygs plate reason",
            "stock_reason": "jygs stock reason",
            "time": None,
            "reason_ref": {
                "trade_date": "2026-03-05",
                "board_key": "robotics",
                "action_field_id": "field-1",
            },
        },
        {
            "trade_date": "2026-03-04",
            "provider": "xgb",
            "code6": "000001",
            "name": "alpha",
            "plate_key": "11",
            "plate_name": "robotics",
            "plate_reason": "older plate reason",
            "stock_reason": "older stock reason",
            "time": "14:00",
            "reason_ref": {"trade_date": "2026-03-04", "plate_id": 11},
        },
    ]


def test_build_stock_hot_reason_rows_fails_when_plate_reason_missing():
    with pytest.raises(ValueError, match="missing stock hot reason"):
        build_stock_hot_reason_rows(
            gantt_stock_rows=[
                {
                    "provider": "xgb",
                    "trade_date": "2026-03-05",
                    "plate_key": "11",
                    "plate_name": "robotics",
                    "code6": "000001",
                    "name": "alpha",
                    "stock_reason": "stock reason",
                }
            ],
            plate_reason_rows=[],
        )


def test_build_xgb_gantt_rows_normalizes_symbol_to_code6():
    plate_rows, stock_rows = _build_xgb_gantt_rows(
        "2025-10-24",
        [
            {
                "trade_date": "2025-10-24",
                "plate_id": 16793689,
                "plate_name": "apple",
                "description": "plate reason",
                "rank": 11,
                "limit_up_count": 0,
                "hot_stocks": [
                    {
                        "symbol": "002475.SZ",
                        "stock_name": "luxshare",
                        "description": "stock reason",
                        "up_limit": 0,
                        "enter_time": 1761271489,
                    }
                ],
            }
        ],
    )

    assert plate_rows == [
        {
            "provider": "xgb",
            "trade_date": "2025-10-24",
            "plate_key": "16793689",
            "plate_name": "apple",
            "rank": 11,
            "hot_stock_count": 1,
            "limit_up_count": 0,
            "stock_codes": ["002475"],
        }
    ]
    assert stock_rows == [
        {
            "provider": "xgb",
            "trade_date": "2025-10-24",
            "plate_key": "16793689",
            "plate_name": "apple",
            "code6": "002475",
            "name": "luxshare",
            "is_limit_up": 0,
            "stock_reason": "stock reason",
            "time": "10:04",
        }
    ]


class FakeCollection:
    def __init__(self, docs=None, indexes=None):
        self.docs = list(docs or [])
        self.indexes = list(
            indexes
            or [
                {
                    "name": "_id_",
                    "key": {"_id": 1},
                }
            ]
        )

    def create_index(self, keys, unique=False, name=None):
        key = dict(keys)
        index_name = name or "_".join(
            f"{field}_{direction}" for field, direction in keys
        )
        self.indexes = [item for item in self.indexes if item.get("name") != index_name]
        self.indexes.append({"name": index_name, "key": key, "unique": unique})
        return index_name

    def list_indexes(self):
        return list(self.indexes)

    def drop_index(self, name):
        self.indexes = [item for item in self.indexes if item.get("name") != name]

    def find(self, query=None, projection=None):
        query = query or {}
        return [doc for doc in self.docs if _matches(doc, query)]

    def update_one(self, query, update, upsert=False):
        target = None
        for doc in self.docs:
            if _matches(doc, query):
                target = doc
                break
        if target is None:
            target = dict(query)
            self.docs.append(target)
        target.update(update.get("$set", {}))

    def delete_many(self, query):
        self.docs = [doc for doc in self.docs if not _matches(doc, query)]


class FakeDB(dict):
    def __getitem__(self, name):
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def _matches(doc, query):
    for key, expected in query.items():
        actual = doc.get(key)
        if isinstance(expected, dict):
            if "$exists" in expected and (key in doc) != bool(expected["$exists"]):
                return False
            if "$gte" in expected and actual < expected["$gte"]:
                return False
            if "$lte" in expected and actual > expected["$lte"]:
                return False
            continue
        if actual != expected:
            return False
    return True


def test_persist_plate_reason_daily_for_date_reads_raw_sources(monkeypatch):
    from freshquant.data import gantt_readmodel as svc

    fake_db = FakeDB(
        xgb_top_gainer_history=FakeCollection(
            [
                {
                    "trade_date": "2026-03-05",
                    "plate_id": 11,
                    "plate_name": "robotics",
                    "description": "xgb reason",
                }
            ]
        ),
        jygs_action_fields=FakeCollection(
            [
                {
                    "date": "2026-03-05",
                    "action_field_id": "f-1",
                    "name": "robotics*12",
                    "reason": "jygs reason",
                    "count": 12,
                }
            ]
        ),
    )
    monkeypatch.setattr(svc, "DBGantt", fake_db)

    count = svc.persist_plate_reason_daily_for_date("2026-03-05")

    assert count == 2
    assert fake_db[svc.COL_PLATE_REASON_DAILY].docs == [
        {
            "provider": "xgb",
            "trade_date": "2026-03-05",
            "plate_key": "11",
            "plate_name": "robotics",
            "reason_text": "xgb reason",
            "reason_source": "xgb_top_gainer_history.description",
            "source_ref": {"trade_date": "2026-03-05", "plate_id": 11},
        },
        {
            "provider": "jygs",
            "trade_date": "2026-03-05",
            "plate_key": "robotics",
            "plate_name": "robotics",
            "reason_text": "jygs reason",
            "reason_source": "jygs_action_fields.reason",
            "source_ref": {
                "trade_date": "2026-03-05",
                "board_key": "robotics",
                "action_field_id": "f-1",
            },
        },
    ]


def test_persist_gantt_daily_for_date_writes_xgb_and_jygs_rows(monkeypatch):
    from freshquant.data import gantt_readmodel as svc

    fake_db = FakeDB(
        plate_reason_daily=FakeCollection(
            [
                {
                    "provider": "xgb",
                    "trade_date": "2026-03-05",
                    "plate_key": "11",
                    "plate_name": "robotics",
                    "reason_text": "xgb plate reason",
                    "reason_source": "xgb_top_gainer_history.description",
                    "source_ref": {"trade_date": "2026-03-05", "plate_id": 11},
                },
                {
                    "provider": "jygs",
                    "trade_date": "2026-03-05",
                    "plate_key": "robotics",
                    "plate_name": "robotics",
                    "reason_text": "jygs plate reason",
                    "reason_source": "jygs_action_fields.reason",
                    "source_ref": {
                        "trade_date": "2026-03-05",
                        "board_key": "robotics",
                        "action_field_id": "field-1",
                    },
                },
            ]
        ),
        xgb_top_gainer_history=FakeCollection(
            [
                {
                    "trade_date": "2026-03-05",
                    "plate_id": 11,
                    "plate_name": "robotics",
                    "rank": 1,
                    "limit_up_count": 2,
                    "hot_stocks": [
                        {
                            "symbol": "000001",
                            "stock_name": "alpha",
                            "description": "stock reason",
                            "up_limit": 1,
                            "enter_time": "09:31:15",
                        }
                    ],
                }
            ]
        ),
        jygs_yidong=FakeCollection(
            [
                {
                    "date": "2026-03-05",
                    "stock_code": "000002",
                    "stock_name": "beta",
                    "analysis": "jygs stock reason",
                    "limit_up_time": "10:08:42",
                    "boards": [
                        {
                            "field_id": "field-1",
                            "name": "robotics*12",
                            "board_key": "robotics",
                            "count": 12,
                        }
                    ],
                }
            ]
        ),
    )
    monkeypatch.setattr(svc, "DBGantt", fake_db)

    result = svc.persist_gantt_daily_for_date("2026-03-05")

    assert result == {"trade_date": "2026-03-05", "plates": 2, "stocks": 2}
    assert fake_db[svc.COL_GANTT_PLATE_DAILY].docs == [
        {
            "provider": "xgb",
            "trade_date": "2026-03-05",
            "plate_key": "11",
            "plate_name": "robotics",
            "rank": 1,
            "hot_stock_count": 1,
            "limit_up_count": 2,
            "stock_codes": ["000001"],
            "reason_text": "xgb plate reason",
            "reason_ref": {"trade_date": "2026-03-05", "plate_id": 11},
        },
        {
            "provider": "jygs",
            "trade_date": "2026-03-05",
            "plate_key": "robotics",
            "plate_name": "robotics*12",
            "rank": 1,
            "hot_stock_count": 1,
            "limit_up_count": 0,
            "stock_codes": ["000002"],
            "reason_text": "jygs plate reason",
            "reason_ref": {
                "trade_date": "2026-03-05",
                "board_key": "robotics",
                "action_field_id": "field-1",
            },
        },
    ]
    assert fake_db[svc.COL_GANTT_STOCK_DAILY].docs == [
        {
            "provider": "xgb",
            "trade_date": "2026-03-05",
            "plate_key": "11",
            "plate_name": "robotics",
            "code6": "000001",
            "name": "alpha",
            "is_limit_up": 1,
            "stock_reason": "stock reason",
            "time": "09:31",
        },
        {
            "provider": "jygs",
            "trade_date": "2026-03-05",
            "plate_key": "robotics",
            "plate_name": "robotics*12",
            "code6": "000002",
            "name": "beta",
            "is_limit_up": 0,
            "stock_reason": "jygs stock reason",
            "time": "10:08",
        },
    ]


def test_persist_gantt_daily_for_date_fails_when_plate_reason_is_missing(monkeypatch):
    from freshquant.data import gantt_readmodel as svc

    fake_db = FakeDB(
        plate_reason_daily=FakeCollection([]),
        xgb_top_gainer_history=FakeCollection(
            [
                {
                    "trade_date": "2026-03-05",
                    "plate_id": 11,
                    "plate_name": "robotics",
                    "rank": 1,
                    "limit_up_count": 2,
                    "hot_stocks": [{"symbol": "000001", "stock_name": "alpha"}],
                }
            ]
        ),
        jygs_yidong=FakeCollection([]),
    )
    monkeypatch.setattr(svc, "DBGantt", fake_db)

    with pytest.raises(ValueError, match="missing plate reason"):
        svc.persist_gantt_daily_for_date("2026-03-05")


def test_persist_shouban30_for_date_joins_plate_reason(monkeypatch):
    from freshquant.data import gantt_readmodel as svc

    fake_db = FakeDB(
        plate_reason_daily=FakeCollection(
            [
                {
                    "provider": "xgb",
                    "trade_date": "2026-03-05",
                    "plate_key": "11",
                    "plate_name": "robotics",
                    "reason_text": "canonical reason",
                    "reason_source": "xgb_top_gainer_history.description",
                    "source_ref": {"trade_date": "2026-03-05", "plate_id": 11},
                }
            ]
        ),
        gantt_plate_daily=FakeCollection(
            [
                {
                    "provider": "xgb",
                    "trade_date": "2026-03-04",
                    "plate_key": "11",
                    "plate_name": "robotics",
                    "rank": 2,
                    "hot_stock_count": 1,
                    "limit_up_count": 1,
                    "stock_codes": ["000001"],
                },
                {
                    "provider": "xgb",
                    "trade_date": "2026-03-05",
                    "plate_key": "11",
                    "plate_name": "robotics",
                    "rank": 1,
                    "hot_stock_count": 1,
                    "limit_up_count": 1,
                    "stock_codes": ["000001"],
                },
                {
                    "provider": "xgb",
                    "trade_date": "2026-03-03",
                    "plate_key": "22",
                    "plate_name": "broken",
                    "rank": 2,
                    "hot_stock_count": 1,
                    "limit_up_count": 1,
                    "stock_codes": ["000009"],
                },
                {
                    "provider": "xgb",
                    "trade_date": "2026-03-05",
                    "plate_key": "22",
                    "plate_name": "broken",
                    "rank": 1,
                    "hot_stock_count": 1,
                    "limit_up_count": 1,
                    "stock_codes": ["000009"],
                },
            ]
        ),
        gantt_stock_daily=FakeCollection(
            [
                {
                    "provider": "xgb",
                    "trade_date": "2026-02-10",
                    "plate_key": "11",
                    "plate_name": "robotics",
                    "code6": "000001",
                    "name": "alpha",
                    "is_limit_up": 1,
                    "stock_reason": "older stock reason",
                },
                {
                    "provider": "xgb",
                    "trade_date": "2026-03-05",
                    "plate_key": "11",
                    "plate_name": "robotics",
                    "code6": "000001",
                    "name": "alpha",
                    "is_limit_up": 1,
                    "stock_reason": "stock reason",
                },
            ]
        ),
    )
    monkeypatch.setattr(svc, "DBGantt", fake_db)

    result = svc.persist_shouban30_for_date("2026-03-05", stock_window_days=60)

    assert result == {
        "as_of_date": "2026-03-05",
        "plates": 1,
        "stocks": 1,
        "stock_window_days": 60,
    }
    assert fake_db[svc.COL_SHOUBAN30_PLATES].docs == [
        {
            "provider": "xgb",
            "as_of_date": "2026-03-05",
            "plate_key": "11",
            "plate_name": "robotics",
            "stock_window_days": 60,
            "appear_days_30": 2,
            "seg_from": "2026-03-04",
            "seg_to": "2026-03-05",
            "hit_trade_dates_30": ["2026-03-04", "2026-03-05"],
            "stocks_count": 1,
            "stock_window_from": "2026-02-10",
            "stock_window_to": "2026-03-05",
            "reason_text": "canonical reason",
            "reason_ref": {"trade_date": "2026-03-05", "plate_id": 11},
        }
    ]
    assert fake_db[svc.COL_SHOUBAN30_STOCKS].docs == [
        {
            "provider": "xgb",
            "as_of_date": "2026-03-05",
            "plate_key": "11",
            "plate_name": "robotics",
            "code6": "000001",
            "name": "alpha",
            "stock_window_days": 60,
            "hit_count_30": 1,
            "hit_count_window": 2,
            "hit_trade_dates_30": ["2026-03-05"],
            "hit_trade_dates_window": ["2026-02-10", "2026-03-05"],
            "latest_trade_date": "2026-03-05",
            "latest_reason": "stock reason",
        }
    ]


def test_ensure_readmodel_indexes_drops_legacy_shouban30_unique_indexes(monkeypatch):
    from freshquant.data import gantt_readmodel as svc

    fake_db = FakeDB(
        shouban30_plates=FakeCollection(
            indexes=[
                {"name": "_id_", "key": {"_id": 1}},
                {
                    "name": "provider_1_plate_key_1_as_of_date_1",
                    "key": {"provider": 1, "plate_key": 1, "as_of_date": 1},
                    "unique": True,
                },
            ]
        ),
        shouban30_stocks=FakeCollection(
            indexes=[
                {"name": "_id_", "key": {"_id": 1}},
                {
                    "name": "provider_1_plate_key_1_code6_1_as_of_date_1",
                    "key": {
                        "provider": 1,
                        "plate_key": 1,
                        "code6": 1,
                        "as_of_date": 1,
                    },
                    "unique": True,
                },
            ]
        ),
    )
    monkeypatch.setattr(svc, "DBGantt", fake_db)

    svc.ensure_readmodel_indexes()

    plate_index_names = {
        item["name"] for item in fake_db[svc.COL_SHOUBAN30_PLATES].list_indexes()
    }
    stock_index_names = {
        item["name"] for item in fake_db[svc.COL_SHOUBAN30_STOCKS].list_indexes()
    }

    assert "provider_1_plate_key_1_as_of_date_1" not in plate_index_names
    assert (
        "provider_1_plate_key_1_as_of_date_1_stock_window_days_1" in plate_index_names
    )
    assert "provider_1_plate_key_1_code6_1_as_of_date_1" not in stock_index_names
    assert (
        "provider_1_plate_key_1_code6_1_as_of_date_1_stock_window_days_1"
        in stock_index_names
    )


def test_persist_stock_hot_reason_daily_for_date_joins_and_queries(monkeypatch):
    from freshquant.data import gantt_readmodel as svc

    fake_db = FakeDB(
        plate_reason_daily=FakeCollection(
            [
                {
                    "provider": "xgb",
                    "trade_date": "2026-03-05",
                    "plate_key": "11",
                    "plate_name": "robotics",
                    "reason_text": "xgb plate reason",
                    "reason_source": "xgb_top_gainer_history.description",
                    "source_ref": {"trade_date": "2026-03-05", "plate_id": 11},
                },
                {
                    "provider": "jygs",
                    "trade_date": "2026-03-05",
                    "plate_key": "robotics",
                    "plate_name": "robotics",
                    "reason_text": "jygs plate reason",
                    "reason_source": "jygs_action_fields.reason",
                    "source_ref": {
                        "trade_date": "2026-03-05",
                        "board_key": "robotics",
                        "action_field_id": "field-1",
                    },
                },
            ]
        ),
        gantt_stock_daily=FakeCollection(
            [
                {
                    "provider": "xgb",
                    "trade_date": "2026-03-05",
                    "plate_key": "11",
                    "plate_name": "robotics",
                    "code6": "000001",
                    "name": "alpha",
                    "stock_reason": "xgb stock reason",
                    "time": "09:31",
                },
                {
                    "provider": "jygs",
                    "trade_date": "2026-03-05",
                    "plate_key": "robotics",
                    "plate_name": "robotics",
                    "code6": "000001",
                    "name": "alpha",
                    "stock_reason": "jygs stock reason",
                },
            ]
        ),
    )
    monkeypatch.setattr(svc, "DBGantt", fake_db)

    count = svc.persist_stock_hot_reason_daily_for_date("2026-03-05")
    rows = svc.query_stock_hot_reason_rows(code6="000001", provider="all", limit=0)

    assert count == 2
    assert fake_db[svc.COL_STOCK_HOT_REASON_DAILY].docs == [
        {
            "trade_date": "2026-03-05",
            "provider": "xgb",
            "code6": "000001",
            "name": "alpha",
            "plate_key": "11",
            "plate_name": "robotics",
            "plate_reason": "xgb plate reason",
            "stock_reason": "xgb stock reason",
            "time": "09:31",
            "reason_ref": {"trade_date": "2026-03-05", "plate_id": 11},
        },
        {
            "trade_date": "2026-03-05",
            "provider": "jygs",
            "code6": "000001",
            "name": "alpha",
            "plate_key": "robotics",
            "plate_name": "robotics",
            "plate_reason": "jygs plate reason",
            "stock_reason": "jygs stock reason",
            "time": None,
            "reason_ref": {
                "trade_date": "2026-03-05",
                "board_key": "robotics",
                "action_field_id": "field-1",
            },
        },
    ]
    assert rows == [
        {
            "date": "2026-03-05",
            "time": "09:31",
            "provider": "xgb",
            "plate_name": "robotics",
            "plate_reason": "xgb plate reason",
            "stock_reason": "xgb stock reason",
        },
        {
            "date": "2026-03-05",
            "time": None,
            "provider": "jygs",
            "plate_name": "robotics",
            "plate_reason": "jygs plate reason",
            "stock_reason": "jygs stock reason",
        },
    ]

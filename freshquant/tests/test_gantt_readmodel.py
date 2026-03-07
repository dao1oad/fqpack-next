import pytest

from freshquant.data.gantt_readmodel import (
    build_plate_reason_daily,
    build_shouban30_plate_rows,
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
                "stocks_count_90": 8,
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
                    "stocks_count_90": 8,
                }
            ],
            plate_reason_rows=[],
            as_of_date="2026-03-05",
        )


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def create_index(self, *args, **kwargs):
        return None

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
                    "is_limit_up": 1,
                    "stock_reason": "stock reason",
                }
            ]
        ),
    )
    monkeypatch.setattr(svc, "DBGantt", fake_db)

    result = svc.persist_shouban30_for_date("2026-03-05")

    assert result == {"as_of_date": "2026-03-05", "plates": 1, "stocks": 1}
    assert fake_db[svc.COL_SHOUBAN30_PLATES].docs == [
        {
            "provider": "xgb",
            "as_of_date": "2026-03-05",
            "plate_key": "11",
            "plate_name": "robotics",
            "appear_days_30": 2,
            "seg_from": "2026-03-04",
            "seg_to": "2026-03-05",
            "stocks_count_90": 1,
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
            "appear_days_90": 1,
            "latest_trade_date": "2026-03-05",
            "stock_reason": "stock reason",
        }
    ]

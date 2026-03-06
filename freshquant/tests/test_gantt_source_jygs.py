import pytest

from freshquant.data.gantt_source_jygs import normalize_jygs_action_field_row


def test_jygs_board_key_is_derived_from_board_name_not_action_field_id():
    raw = {
        "action_field_id": "9988",
        "name": "robotics*15",
        "reason": "theme: humanoid supply chain",
        "count": 15,
    }

    row = normalize_jygs_action_field_row("2026-03-05", raw)

    assert row["provider"] == "jygs"
    assert row["plate_key"] == "robotics"
    assert row["action_field_id"] == "9988"
    assert row["plate_key"] != row["action_field_id"]


def test_jygs_action_reason_is_required_when_board_is_present():
    raw = {
        "action_field_id": "9988",
        "name": "robotics",
        "reason": "",
    }

    with pytest.raises(ValueError, match="reason_text"):
        normalize_jygs_action_field_row("2026-03-05", raw)


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


def test_sync_jygs_action_for_date_writes_action_fields_and_yidong(monkeypatch):
    from freshquant.data import gantt_source_jygs as svc

    fake_db = FakeDB()
    monkeypatch.setattr(svc, "DBGantt", fake_db)
    monkeypatch.setattr(
        svc,
        "fetch_action_count",
        lambda trade_date: {"data": {"date": trade_date}},
    )
    monkeypatch.setattr(
        svc,
        "fetch_action_field",
        lambda trade_date: {
            "data": [
                {
                    "action_field_id": "field-1",
                    "name": "robotics*12",
                    "count": 12,
                    "reason": "plate reason",
                }
            ]
        },
    )
    monkeypatch.setattr(
        svc,
        "fetch_action_list",
        lambda params: {
            "data": [
                {
                    "code": "000001",
                    "name": "alpha",
                    "article": {
                        "title": "article title",
                        "action_info": {
                            "reason": "stock reason",
                        },
                    },
                }
            ]
        },
    )

    result = svc.sync_jygs_action_for_date("2026-03-05")

    assert result == {"trade_date": "2026-03-05", "action_fields": 1, "yidong": 1}
    assert fake_db[svc.COL_JYGS_ACTION_FIELDS].docs == [
        {
            "date": "2026-03-05",
            "board_key": "robotics",
            "action_field_id": "field-1",
            "name": "robotics*12",
            "count": 12,
            "reason": "plate reason",
        }
    ]
    assert fake_db[svc.COL_JYGS_YIDONG].docs == [
        {
            "date": "2026-03-05",
            "stock_code": "000001",
            "stock_name": "alpha",
            "analysis": "stock reason",
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


def test_sync_jygs_action_for_date_replaces_stale_rows(monkeypatch):
    from freshquant.data import gantt_source_jygs as svc

    fake_db = FakeDB()
    fake_db[svc.COL_JYGS_ACTION_FIELDS].docs = [
        {
            "date": "2026-03-05",
            "board_key": "stale",
            "action_field_id": "old-field",
            "name": "stale*9",
            "count": 9,
            "reason": "stale reason",
        }
    ]
    fake_db[svc.COL_JYGS_YIDONG].docs = [
        {
            "date": "2026-03-05",
            "stock_code": "000999",
            "stock_name": "stale",
            "analysis": "stale stock reason",
            "boards": [{"field_id": "old-field", "board_key": "stale"}],
        }
    ]
    monkeypatch.setattr(svc, "DBGantt", fake_db)
    monkeypatch.setattr(
        svc,
        "fetch_action_count",
        lambda trade_date: {"data": {"date": trade_date}},
    )
    monkeypatch.setattr(
        svc,
        "fetch_action_field",
        lambda trade_date: {
            "data": [
                {
                    "action_field_id": "field-1",
                    "name": "robotics*12",
                    "count": 12,
                    "reason": "plate reason",
                }
            ]
        },
    )
    monkeypatch.setattr(
        svc,
        "fetch_action_list",
        lambda params: {
            "data": [
                {
                    "code": "000001",
                    "name": "alpha",
                    "article": {
                        "title": "article title",
                        "action_info": {
                            "reason": "stock reason",
                        },
                    },
                }
            ]
        },
    )

    svc.sync_jygs_action_for_date("2026-03-05")

    assert fake_db[svc.COL_JYGS_ACTION_FIELDS].docs == [
        {
            "date": "2026-03-05",
            "board_key": "robotics",
            "action_field_id": "field-1",
            "name": "robotics*12",
            "count": 12,
            "reason": "plate reason",
        }
    ]
    assert fake_db[svc.COL_JYGS_YIDONG].docs == [
        {
            "date": "2026-03-05",
            "stock_code": "000001",
            "stock_name": "alpha",
            "analysis": "stock reason",
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

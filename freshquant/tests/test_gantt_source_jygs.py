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


def test_get_auth_cookies_uses_session_and_admin_cookie(monkeypatch):
    from freshquant.data import gantt_source_jygs as svc

    monkeypatch.setenv("JYGS_SESSION", "session-from-env")
    monkeypatch.setenv(
        "JYGS_COOKIE",
        "foo=bar; admin=%7B%22sessionToken%22%3A%22session-from-admin%22%7D",
    )

    cookies = svc.get_auth_cookies()

    assert cookies["foo"] == "bar"
    assert cookies["SESSION"] == "session-from-env"


def test_get_auth_cookies_reads_jygs_env_file(monkeypatch, tmp_path):
    from freshquant.data import gantt_source_jygs as svc

    env_file = tmp_path / "envs.conf"
    env_file.write_text(
        "JYGS_COOKIE=\"foo=bar; admin=%7B%22sessionToken%22%3A%22session-from-admin%22%7D\"\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("JYGS_COOKIE", raising=False)
    monkeypatch.delenv("JYGS_SESSION", raising=False)
    monkeypatch.setenv("JYGS_ENV_FILE", str(env_file))

    cookies = svc.get_auth_cookies()

    assert cookies["foo"] == "bar"
    assert cookies["SESSION"] == "session-from-admin"


def test_get_auth_cookies_backfills_missing_partial_env_from_file(
    monkeypatch, tmp_path
):
    from freshquant.data import gantt_source_jygs as svc

    env_file = tmp_path / "envs.conf"
    env_file.write_text(
        "\n".join(
            [
                "JYGS_COOKIE=foo=bar; admin=%7B%22sessionToken%22%3A%22session-from-admin%22%7D",
                "JYGS_SESSION=session-from-file",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("JYGS_COOKIE", "foo=from-env")
    monkeypatch.delenv("JYGS_SESSION", raising=False)
    monkeypatch.setenv("JYGS_ENV_FILE", str(env_file))

    cookies = svc.get_auth_cookies()

    assert cookies["foo"] == "from-env"
    assert cookies["SESSION"] == "session-from-file"


def test_fetch_action_count_uses_auth_cookies_and_retries_form(monkeypatch):
    from freshquant.data import gantt_source_jygs as svc

    monkeypatch.setenv("JYGS_SESSION", "session-from-env")
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_post(url, json=None, data=None, headers=None, cookies=None, timeout=None):
        calls.append(
            {
                "url": url,
                "json": json,
                "data": data,
                "headers": headers,
                "cookies": cookies,
                "timeout": timeout,
            }
        )
        if len(calls) == 1:
            return FakeResponse({"errCode": "1", "msg": "登录失效", "data": {}})
        return FakeResponse({"errCode": "0", "data": {"date": "2026-03-05"}})

    monkeypatch.setattr(svc.requests, "post", fake_post)

    payload = svc.fetch_action_count("2026-03-05")

    assert payload == {"errCode": "0", "data": {"date": "2026-03-05"}}
    assert len(calls) == 2
    assert calls[0]["cookies"]["SESSION"] == "session-from-env"
    assert calls[0]["headers"]["Content-Type"] == "application/json"
    assert calls[1]["data"] == {"date": "2026-03-05"}
    assert (
        calls[1]["headers"]["Content-Type"]
        == "application/x-www-form-urlencoded;charset=utf-8"
    )


def test_sync_jygs_action_for_date_skips_non_theme_buckets(monkeypatch):
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
                    "action_field_id": "",
                    "name": "简图",
                    "count": 0,
                    "reason": "",
                },
                {
                    "action_field_id": "field-ignore",
                    "name": "其他",
                    "count": 16,
                    "reason": "",
                },
                {
                    "action_field_id": "field-1",
                    "name": "robotics*12",
                    "count": 12,
                    "reason": "plate reason",
                },
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

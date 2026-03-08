from __future__ import annotations

from freshquant.market_data.xtdata import pools
from freshquant.preset import params


class FakeParamsCollection:
    def __init__(self, docs: list[dict] | None = None):
        self.docs = {
            str(doc.get("code") or ""): dict(doc)
            for doc in (docs or [])
            if doc.get("code")
        }

    def find_one(self, query: dict):
        return self.docs.get(str(query.get("code") or ""))

    def update_one(self, query: dict, update: dict, upsert: bool = False):
        code = str(query.get("code") or "")
        doc = self.docs.get(code)
        if doc is None:
            if not upsert:
                return
            doc = {"code": code}
            self.docs[code] = doc
            inserted = True
        else:
            inserted = False

        for key, value in (update.get("$setOnInsert") or {}).items():
            if inserted:
                _set_nested_value(doc, key, value)

        for key, value in (update.get("$set") or {}).items():
            _set_nested_value(doc, key, value)


class FakeDb:
    def __init__(self, docs: list[dict] | None = None):
        self.params = FakeParamsCollection(docs)


def _set_nested_value(doc: dict, key: str, value):
    parts = str(key).split(".")
    cur = doc
    for part in parts[:-1]:
        next_value = cur.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            cur[part] = next_value
        cur = next_value
    cur[parts[-1]] = value


def test_normalize_xtdata_mode_defaults_to_guardian_1m():
    assert pools.normalize_xtdata_mode(None) == "guardian_1m"
    assert pools.normalize_xtdata_mode("") == "guardian_1m"
    assert pools.normalize_xtdata_mode("  ") == "guardian_1m"
    assert pools.normalize_xtdata_mode("unknown_mode") == "guardian_1m"
    assert pools.normalize_xtdata_mode("GUARDIAN_1M") == "guardian_1m"
    assert pools.normalize_xtdata_mode("CLX_15_30") == "clx_15_30"


def test_load_monitor_codes_defaults_unknown_mode_to_guardian(monkeypatch):
    calls: list[tuple[str, int]] = []

    monkeypatch.setattr(
        pools,
        "_load_guardian_codes",
        lambda limit: calls.append(("guardian", limit)) or ["sz000001"],
    )
    monkeypatch.setattr(
        pools,
        "_load_clx_codes",
        lambda limit: calls.append(("clx", limit)) or ["sz000002"],
    )

    assert pools.load_monitor_codes(mode="missing_mode", max_symbols=12) == ["sz000001"]
    assert calls == [("guardian", 12)]


def test_load_monitor_codes_preserves_explicit_clx_mode(monkeypatch):
    calls: list[tuple[str, int]] = []

    monkeypatch.setattr(
        pools,
        "_load_guardian_codes",
        lambda limit: calls.append(("guardian", limit)) or ["sz000001"],
    )
    monkeypatch.setattr(
        pools,
        "_load_clx_codes",
        lambda limit: calls.append(("clx", limit)) or ["sz000002"],
    )

    assert pools.load_monitor_codes(mode="clx_15_30", max_symbols=7) == ["sz000002"]
    assert calls == [("clx", 7)]


def test_init_param_dict_persists_guardian_default_when_mode_missing(monkeypatch):
    fake_db = FakeDb()
    monkeypatch.setattr(params, "DBfreshquant", fake_db)
    monkeypatch.setattr(params, "mask", lambda value, show_chars=0: value)

    params.init_param_dict(quiet=True)

    monitor_doc = fake_db.params.docs["monitor"]
    assert monitor_doc["value"]["xtdata"]["mode"] == "guardian_1m"


def test_init_param_dict_preserves_explicit_clx_mode(monkeypatch):
    fake_db = FakeDb(
        [
            {
                "code": "monitor",
                "value": {
                    "xtdata": {
                        "mode": "clx_15_30",
                        "max_symbols": 88,
                        "prewarm": {"max_bars": 12345},
                    }
                },
            }
        ]
    )
    monkeypatch.setattr(params, "DBfreshquant", fake_db)
    monkeypatch.setattr(params, "mask", lambda value, show_chars=0: value)

    params.init_param_dict(quiet=True)

    monitor_doc = fake_db.params.docs["monitor"]
    assert monitor_doc["value"]["xtdata"]["mode"] == "clx_15_30"
    assert monitor_doc["value"]["xtdata"]["max_symbols"] == 88
    assert monitor_doc["value"]["xtdata"]["prewarm"]["max_bars"] == 12345

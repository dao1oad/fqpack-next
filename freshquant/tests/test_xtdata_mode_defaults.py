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

        for key in (update.get("$unset") or {}).keys():
            _unset_nested_value(doc, key)


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


def _unset_nested_value(doc: dict, key: str):
    parts = str(key).split(".")
    cur = doc
    for part in parts[:-1]:
        next_value = cur.get(part)
        if not isinstance(next_value, dict):
            return
        cur = next_value
    cur.pop(parts[-1], None)


def test_migrate_xtdata_mode_maps_legacy_modes_to_dual_booleans():
    assert pools.migrate_xtdata_mode(None) == (True, False)
    assert pools.migrate_xtdata_mode("") == (True, False)
    assert pools.migrate_xtdata_mode("guardian_1m") == (True, False)
    assert pools.migrate_xtdata_mode("guardian_and_clx_15_30") == (True, True)
    assert pools.migrate_xtdata_mode("clx_15_30") == (True, True)
    assert pools.migrate_xtdata_mode("clx_15_30_only") == (False, True)
    assert pools.migrate_xtdata_mode("unknown_mode") == (True, False)


def test_lines_for_modes_keeps_priority_order():
    assert pools.lines_for_modes(trading_mode=True, screening_mode=False) == (
        pools.LINE_1M_T,
        pools.LINE_5M_NEW_OPEN,
    )
    assert pools.lines_for_modes(trading_mode=False, screening_mode=True) == (
        pools.LINE_15_30_CLX,
    )
    assert pools.lines_for_modes(trading_mode=True, screening_mode=True) == (
        pools.LINE_1M_T,
        pools.LINE_5M_NEW_OPEN,
        pools.LINE_15_30_CLX,
    )
    assert pools.lines_for_modes(trading_mode=False, screening_mode=False) == ()


def test_load_monitor_codes_trading_only_uses_holding_and_must_pool(monkeypatch):
    calls: list[tuple[str, int]] = []

    monkeypatch.setattr(
        pools,
        "_load_holding_codes",
        lambda limit: calls.append(("holding", limit)) or ["sz000001"],
    )
    monkeypatch.setattr(
        pools,
        "_load_must_pool_codes",
        lambda limit: calls.append(("must_pool", limit)) or ["sz000002"],
    )
    monkeypatch.setattr(
        pools,
        "_load_clx_codes",
        lambda limit: calls.append(("clx", limit)) or ["sh600000"],
    )

    assert pools.load_monitor_codes(
        trading_mode=True,
        screening_mode=False,
        max_symbols=12,
    ) == ["sz000001", "sz000002"]
    assert calls == [("holding", 12), ("must_pool", 12)]


def test_load_monitor_codes_screening_only_uses_stock_pools(monkeypatch):
    calls: list[tuple[str, int]] = []

    monkeypatch.setattr(
        pools,
        "_load_holding_codes",
        lambda limit: calls.append(("holding", limit)) or ["sz000001"],
    )
    monkeypatch.setattr(
        pools,
        "_load_must_pool_codes",
        lambda limit: calls.append(("must_pool", limit)) or ["sz000002"],
    )
    monkeypatch.setattr(
        pools,
        "_load_clx_codes",
        lambda limit: calls.append(("clx", limit)) or ["sh600000"],
    )

    assert pools.load_monitor_codes(
        trading_mode=False,
        screening_mode=True,
        max_symbols=12,
    ) == ["sh600000"]
    assert calls == [("clx", 12)]


def test_load_monitor_codes_truncates_low_priority_line_without_silence(
    monkeypatch,
):
    emitted = []
    monkeypatch.setattr(
        pools,
        "_load_holding_codes",
        lambda limit: ["sh600000", "sz000001", "sz000002"][:limit],
    )
    monkeypatch.setattr(
        pools,
        "_load_must_pool_codes",
        lambda limit: ["sz000003", "sz000004"][:limit],
    )
    monkeypatch.setattr(
        pools,
        "_load_clx_codes",
        lambda limit: ["sz300001", "sh600010"][:limit],
    )
    monkeypatch.setattr(
        pools,
        "_emit_truncation_event",
        lambda truncated_lines, limit: emitted.append((list(truncated_lines), limit)),
    )

    result = pools.load_monitor_codes(
        trading_mode=True,
        screening_mode=True,
        max_symbols=3,
    )

    assert result == ["sh600000", "sz000001", "sz000002"]
    assert len(emitted) == 1
    truncated = emitted[0][0]
    assert {item["line"] for item in truncated} == {
        pools.LINE_5M_NEW_OPEN,
        pools.LINE_15_30_CLX,
    }


def test_load_line_codes_unknown_line_returns_empty(monkeypatch):
    assert pools.load_line_codes(line="unknown_line", max_symbols=10) == []


def test_holding_exclusion_is_not_truncated_by_max_symbols(monkeypatch):
    class FakeCollection:
        def __init__(self, docs):
            self.docs = list(docs)

        def find(self, query=None, projection=None):
            return list(self.docs)

    # 20 个持仓（sz000001..sz000020），超过 max_symbols=10；
    # 若持仓排除集被截断到 10 个，000011..000020 会漏入 must/stock 目标。
    holdings = [{"symbol": f"sz0000{i:02d}"} for i in range(1, 21)] + [
        {"symbol": f"sh6000{i:02d}"} for i in range(1, 21)
    ]
    fake_db = {
        "xt_positions": FakeCollection(holdings),
        "must_pool": FakeCollection(
            [
                {
                    "code": f"0000{i:02d}",
                    "instrument_type": "stock_cn",
                    "disabled": False,
                }
                for i in range(1, 31)
            ]
        ),
        "stock_pools": FakeCollection([{"code": f"6000{i:02d}"} for i in range(1, 31)]),
    }
    monkeypatch.setattr(pools, "DBfreshquant", fake_db)

    # must_pool 排除集必须覆盖全部持仓（含超出 max_symbols 的部分），
    # 只对最终订阅列表应用 limit。
    must_codes = pools._load_must_pool_codes(10)
    assert len(must_codes) == 10
    # 000001..000020 全部在持仓中，必须被排除；剩余 000021..000030 取前 10 个
    assert must_codes == [f"sz0000{i:02d}" for i in range(21, 31)]

    clx_codes = pools._load_clx_codes(10)
    assert len(clx_codes) == 10
    # 600001..600020 全部在持仓中，必须被排除；剩余 600021..600030 取前 10 个
    assert clx_codes == [f"sh6000{i:02d}" for i in range(21, 31)]


def test_init_param_dict_persists_dual_boolean_defaults_when_mode_missing(
    monkeypatch,
):
    fake_db = FakeDb()
    monkeypatch.setattr(params, "DBfreshquant", fake_db)
    monkeypatch.setattr(params, "mask", lambda value, show_chars=0: value)

    params.init_param_dict(quiet=True)

    monitor_doc = fake_db.params.docs["monitor"]
    assert monitor_doc["value"]["xtdata"]["trading_mode"] is True
    assert monitor_doc["value"]["xtdata"]["screening_mode"] is False
    assert "mode" not in monitor_doc["value"]["xtdata"]


def test_init_param_dict_migrates_legacy_clx_mode(monkeypatch):
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
    assert monitor_doc["value"]["xtdata"]["trading_mode"] is True
    assert monitor_doc["value"]["xtdata"]["screening_mode"] is True
    assert monitor_doc["value"]["xtdata"]["max_symbols"] == 88
    assert monitor_doc["value"]["xtdata"]["prewarm"]["max_bars"] == 12345
    assert "mode" not in monitor_doc["value"]["xtdata"]


def test_init_param_dict_migrates_legacy_clx_only_mode(monkeypatch):
    fake_db = FakeDb(
        [
            {
                "code": "monitor",
                "value": {
                    "xtdata": {
                        "mode": "clx_15_30_only",
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
    assert monitor_doc["value"]["xtdata"]["trading_mode"] is False
    assert monitor_doc["value"]["xtdata"]["screening_mode"] is True
    assert monitor_doc["value"]["xtdata"]["max_symbols"] == 88
    assert "mode" not in monitor_doc["value"]["xtdata"]


def test_init_param_dict_does_not_persist_removed_guardian_and_monitor_fields(
    monkeypatch,
):
    fake_db = FakeDb()
    monkeypatch.setattr(params, "DBfreshquant", fake_db)
    monkeypatch.setattr(params, "mask", lambda value, show_chars=0: value)

    params.init_param_dict(quiet=True)

    monitor_doc = fake_db.params.docs["monitor"]
    guardian_doc = fake_db.params.docs["guardian"]

    assert monitor_doc["value"].get("stock", {}) == {}
    assert "position_pct" not in guardian_doc["value"]["stock"]
    assert "auto_open" not in guardian_doc["value"]["stock"]
    assert "min_amount" not in guardian_doc["value"]["stock"]


def test_init_param_dict_unsets_removed_guardian_and_monitor_fields_from_existing_docs(
    monkeypatch,
):
    fake_db = FakeDb(
        [
            {
                "code": "monitor",
                "value": {
                    "stock": {
                        "periods": ["1m", "5m"],
                    }
                },
            },
            {
                "code": "guardian",
                "value": {
                    "stock": {
                        "position_pct": 30.0,
                        "auto_open": True,
                        "lot_amount": 50000.0,
                        "min_amount": 1000.0,
                    }
                },
            },
        ]
    )
    monkeypatch.setattr(params, "DBfreshquant", fake_db)
    monkeypatch.setattr(params, "mask", lambda value, show_chars=0: value)

    params.init_param_dict(quiet=True)

    monitor_doc = fake_db.params.docs["monitor"]
    guardian_doc = fake_db.params.docs["guardian"]

    assert "periods" not in monitor_doc["value"].get("stock", {})
    assert guardian_doc["value"]["stock"]["lot_amount"] == 50000.0
    assert "position_pct" not in guardian_doc["value"]["stock"]
    assert "auto_open" not in guardian_doc["value"]["stock"]
    assert "min_amount" not in guardian_doc["value"]["stock"]

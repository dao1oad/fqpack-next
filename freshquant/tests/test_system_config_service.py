from __future__ import annotations

from copy import deepcopy

from bson import ObjectId


class FakeUpdateResult:
    def __init__(self, upserted_id=None):
        self.upserted_id = upserted_id


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = [deepcopy(item) for item in (documents or [])]

    def find_one(self, query=None, sort=None):
        query = query or {}
        matched = [doc for doc in self.documents if self._matches(doc, query)]
        if not matched:
            return None
        if sort:
            field, direction = sort[0]
            matched.sort(
                key=lambda item: item.get(field, 0),
                reverse=int(direction) < 0,
            )
        return deepcopy(matched[0])

    def find(self, query=None):
        query = query or {}
        return [deepcopy(doc) for doc in self.documents if self._matches(doc, query)]

    def update_one(self, query, update, upsert=False):
        for index, document in enumerate(self.documents):
            if self._matches(document, query):
                updated = deepcopy(document)
                for key, value in update.get("$set", {}).items():
                    self._assign(updated, key, deepcopy(value))
                for key, value in update.get("$setOnInsert", {}).items():
                    updated.setdefault(key, deepcopy(value))
                self.documents[index] = updated
                return FakeUpdateResult()
        if not upsert:
            return FakeUpdateResult()
        document = deepcopy(query)
        document.setdefault("_id", ObjectId())
        for key, value in update.get("$setOnInsert", {}).items():
            document[key] = deepcopy(value)
        for key, value in update.get("$set", {}).items():
            self._assign(document, key, deepcopy(value))
        self.documents.append(document)
        return FakeUpdateResult(upserted_id=document["_id"])

    @staticmethod
    def _matches(document, query):
        for key, value in query.items():
            if document.get(key) != value:
                return False
        return True

    @staticmethod
    def _assign(document, dotted_key, value):
        if "." not in dotted_key:
            document[dotted_key] = value
            return
        current = document
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value


class FakeDatabase:
    def __init__(self, collections):
        self.collections = {
            name: FakeCollection(documents) for name, documents in collections.items()
        }

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())


def _write_bootstrap_file(path):
    path.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 127.0.0.1",
                "  port: 27027",
                "  db: freshquant",
                "  gantt_db: freshquant_gantt",
                "  screening_db: fqscreening",
                "redis:",
                "  host: 127.0.0.1",
                "  port: 6380",
                "  db: 1",
                "order_management:",
                "  mongo_database: freshquant_order_management",
                "  projection_database: freshquant",
                "position_management:",
                "  mongo_database: freshquant_position_management",
                "memory:",
                "  mongodb:",
                "    host: 127.0.0.1",
                "    port: 27027",
                "    db: fq_memory",
                "  cold_root: D:/fqpack/runtime/memory",
                "  artifact_root: D:/fqpack/runtime/memory/artifacts",
                "  reference_ref: origin/main",
                "tdx:",
                "  home: D:/tdx_biduan",
                "  hq:",
                "    endpoint: http://127.0.0.1:15001",
                "api:",
                "  base_url: http://127.0.0.1:15000",
                "xtdata:",
                "  port: 58610",
                "runtime:",
                "  log_dir: D:/fqpack/log/runtime",
            ]
        ),
        encoding="utf-8",
    )


def _build_database():
    return FakeDatabase(
        {
            "params": [
                {
                    "code": "notification",
                    "value": {
                        "webhook": {
                            "dingtalk": {
                                "private": "https://private.example",
                                "public": "https://public.example",
                            }
                        }
                    },
                },
                {
                    "code": "monitor",
                    "value": {
                        "xtdata": {
                            "mode": "guardian_1m",
                            "max_symbols": 50,
                            "queue_backlog_threshold": 120,
                            "prewarm": {"max_bars": 300},
                        },
                    },
                },
                {
                    "code": "xtquant",
                    "value": {
                        "path": "D:/xtquant/userdata_mini",
                        "account": "068000076370",
                        "account_type": "CREDIT",
                        "broker_submit_mode": "observe_only",
                        "auto_repay": {
                            "enabled": True,
                            "reserve_cash": 6500,
                        },
                    },
                },
                {
                    "code": "guardian",
                    "value": {
                        "stock": {
                            "lot_amount": 1800,
                            "threshold": {
                                "mode": "atr",
                                "atr": {"period": 14, "multiplier": 1.5},
                            },
                            "grid_interval": {"mode": "percent", "percent": 3},
                        }
                    },
                },
            ],
            "pm_configs": [
                {
                    "code": "default",
                    "enabled": True,
                    "thresholds": {
                        "allow_open_min_bail": 910000.0,
                        "holding_only_min_bail": 210000.0,
                        "single_symbol_position_limit": 880000.0,
                    },
                }
            ],
            "strategies": [
                {
                    "_id": ObjectId("65f000000000000000000001"),
                    "code": "Guardian",
                    "name": "守护者策略",
                    "desc": "这是一个高抛低吸的超级网格策略",
                    "b62_uid": "g8txDZY5cclM7zbo",
                },
                {
                    "_id": ObjectId("65f000000000000000000002"),
                    "code": "Manual",
                    "name": "手动策略",
                    "desc": "这是手动挡交易策略",
                    "b62_uid": "manual123",
                },
            ],
            "instrument_strategy": [
                {
                    "instrument_code": "002594.SZ",
                    "instrument_type": "stock",
                    "strategy_name": "g8txDZY5cclM7zbo",
                    "lot_amount": 1800,
                }
            ],
        }
    )


def test_system_config_service_dashboard_reads_bootstrap_and_mongo_settings(
    tmp_path, monkeypatch
):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    _write_bootstrap_file(bootstrap_file)
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    from freshquant import bootstrap_config as bootstrap_module
    from freshquant.system_config_service import SystemConfigService
    from freshquant.system_settings import SystemSettings

    bootstrap_module.reload_bootstrap_config()
    database = _build_database()
    service = SystemConfigService(
        database=database,
        bootstrap_loader=bootstrap_module.load_bootstrap_config,
        bootstrap_reloader=bootstrap_module.reload_bootstrap_config,
        settings=SystemSettings(database=database),
    )

    dashboard = service.get_dashboard()

    assert dashboard["bootstrap"]["file_path"] == str(bootstrap_file)
    assert dashboard["bootstrap"]["values"]["mongodb"]["host"] == "127.0.0.1"
    assert dashboard["bootstrap"]["values"]["mongodb"]["screening_db"] == "fqscreening"
    assert dashboard["bootstrap"]["values"]["memory"]["reference_ref"] == "origin/main"
    assert dashboard["bootstrap"]["sections"][0]["key"] == "mongodb"
    assert (
        dashboard["settings"]["values"]["guardian"]["stock"]["threshold"]["mode"]
        == "atr"
    )
    assert (
        dashboard["settings"]["values"]["position_management"][
            "single_symbol_position_limit"
        ]
        == 880000.0
    )
    assert dashboard["settings"]["values"]["xtquant"]["auto_repay"] == {
        "enabled": True,
        "reserve_cash": 6500.0,
    }
    limit_item = next(
        item
        for section in dashboard["settings"]["sections"]
        for item in section["items"]
        if item["key"] == "position_management.single_symbol_position_limit"
    )
    guardian_initial_item = next(
        item
        for section in dashboard["settings"]["sections"]
        for item in section["items"]
        if item["key"] == "guardian.stock.initial_lot_amount_default"
    )
    guardian_lot_item = next(
        item
        for section in dashboard["settings"]["sections"]
        for item in section["items"]
        if item["key"] == "guardian.stock.lot_amount"
    )
    auto_repay_enabled_item = next(
        item
        for section in dashboard["settings"]["sections"]
        for item in section["items"]
        if item["key"] == "xtquant.auto_repay.enabled"
    )
    auto_repay_reserve_item = next(
        item
        for section in dashboard["settings"]["sections"]
        for item in section["items"]
        if item["key"] == "xtquant.auto_repay.reserve_cash"
    )
    assert dashboard["settings"]["sections"][0]["key"] == "notification"
    assert dashboard["settings"]["sections"][-1]["key"] == "position_management"
    assert limit_item["key"] == "position_management.single_symbol_position_limit"
    assert (limit_item["label"], limit_item["value"]) == (
        "单标的默认持仓上限",
        880000.0,
    )
    assert (guardian_initial_item["label"], guardian_initial_item["value"]) == (
        "首笔买入金额",
        100000,
    )
    assert guardian_initial_item["editable"] is False
    assert (guardian_lot_item["label"], guardian_lot_item["value"]) == (
        "默认买入金额",
        1800,
    )
    assert guardian_lot_item["editable"] is True
    assert (auto_repay_enabled_item["label"], auto_repay_enabled_item["value"]) == (
        "自动还款",
        True,
    )
    assert (auto_repay_reserve_item["label"], auto_repay_reserve_item["value"]) == (
        "留底现金",
        6500.0,
    )
    assert dashboard["settings"]["strategies"][0]["code"] == "Guardian"


def test_system_config_service_update_bootstrap_persists_yaml_and_reloads(
    tmp_path, monkeypatch
):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    _write_bootstrap_file(bootstrap_file)
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    from freshquant import bootstrap_config as bootstrap_module
    from freshquant.system_config_service import SystemConfigService
    from freshquant.system_settings import SystemSettings

    bootstrap_module.reload_bootstrap_config()
    database = _build_database()
    service = SystemConfigService(
        database=database,
        bootstrap_loader=bootstrap_module.load_bootstrap_config,
        bootstrap_reloader=bootstrap_module.reload_bootstrap_config,
        settings=SystemSettings(database=database),
    )

    payload = {
        "mongodb": {
            "host": "10.0.0.8",
            "port": 27028,
            "db": "freshquant_test",
            "screening_db": "fqscreening_runtime",
        },
        "memory": {"reference_ref": "upstream/release-main"},
        "xtdata": {"port": 58611},
        "runtime": {"log_dir": "D:/fqpack/runtime/new-logs"},
    }

    result = service.update_bootstrap(payload)

    assert result["values"]["mongodb"]["host"] == "10.0.0.8"
    assert bootstrap_module.bootstrap_config.mongodb.host == "10.0.0.8"
    assert (
        bootstrap_module.bootstrap_config.mongodb.screening_db == "fqscreening_runtime"
    )
    assert (
        bootstrap_module.bootstrap_config.memory.reference_ref
        == "upstream/release-main"
    )
    assert bootstrap_module.bootstrap_config.xtdata.port == 58611
    content = bootstrap_file.read_text(encoding="utf-8")
    assert "10.0.0.8" in content
    assert "fqscreening_runtime" in content
    assert "upstream/release-main" in content
    assert "58611" in content
    assert "D:/fqpack/runtime/new-logs" in content


def test_system_config_service_update_settings_persists_params_and_pm_config(
    tmp_path, monkeypatch
):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    _write_bootstrap_file(bootstrap_file)
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    from freshquant import bootstrap_config as bootstrap_module
    from freshquant.system_config_service import SystemConfigService
    from freshquant.system_settings import SystemSettings

    bootstrap_module.reload_bootstrap_config()
    database = _build_database()
    settings = SystemSettings(database=database)
    service = SystemConfigService(
        database=database,
        bootstrap_loader=bootstrap_module.load_bootstrap_config,
        bootstrap_reloader=bootstrap_module.reload_bootstrap_config,
        settings=settings,
    )

    payload = {
        "notification": {
            "webhook": {
                "dingtalk": {
                    "private": "https://next-private.example",
                    "public": "https://next-public.example",
                }
            }
        },
        "monitor": {
            "xtdata": {
                "mode": "clx_15_30",
                "max_symbols": 88,
                "queue_backlog_threshold": 320,
                "prewarm": {"max_bars": 480},
            },
        },
        "xtquant": {
            "path": "D:/mini_qmt/userdata_mini",
            "account": "123456",
            "account_type": "CREDIT",
            "broker_submit_mode": "observe_only",
            "auto_repay": {
                "enabled": False,
                "reserve_cash": 12000,
            },
        },
        "guardian": {
            "stock": {
                "lot_amount": 50000,
                "threshold": {"mode": "percent", "percent": 1.2},
                "grid_interval": {
                    "mode": "atr",
                    "atr": {"period": 21, "multiplier": 2},
                },
            }
        },
        "position_management": {
            "allow_open_min_bail": 950000,
            "holding_only_min_bail": 150000,
            "single_symbol_position_limit": 780000,
        },
    }

    result = service.update_settings(payload)

    assert result["values"]["xtquant"]["account"] == "123456"
    assert result["values"]["monitor"]["xtdata"]["mode"] == "guardian_and_clx_15_30"
    assert (
        database["params"].find_one({"code": "xtquant"})["value"]["path"]
        == "D:/mini_qmt/userdata_mini"
    )
    assert database["params"].find_one({"code": "xtquant"})["value"]["auto_repay"] == {
        "enabled": False,
        "reserve_cash": 12000.0,
    }
    assert (
        database["params"].find_one({"code": "monitor"})["value"]["xtdata"]["mode"]
        == "guardian_and_clx_15_30"
    )
    assert (
        database["params"].find_one({"code": "guardian"})["value"]["stock"][
            "grid_interval"
        ]["mode"]
        == "atr"
    )
    assert (
        database["pm_configs"].find_one({"code": "default"})["thresholds"][
            "allow_open_min_bail"
        ]
        == 950000
    )
    assert (
        database["pm_configs"].find_one({"code": "default"})["thresholds"][
            "single_symbol_position_limit"
        ]
        == 780000
    )
    assert settings.xtquant.account == "123456"
    assert settings.xtquant.auto_repay_enabled is False
    assert settings.xtquant.auto_repay_reserve_cash == 12000.0
    assert settings.position_management.holding_only_min_bail == 150000
    assert settings.position_management.single_symbol_position_limit == 780000

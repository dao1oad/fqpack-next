from __future__ import annotations

import math
from copy import deepcopy

import yaml  # type: ignore[import-untyped]

from freshquant.bootstrap_config import (
    bootstrap_config,
    load_bootstrap_config,
    reload_bootstrap_config,
    resolve_bootstrap_file_path,
)
from freshquant.market_data.xtdata.pools import normalize_xtdata_mode
from freshquant.system_settings import system_settings

BOOTSTRAP_SECTION_META = {
    "mongodb": {
        "title": "MongoDB",
        "description": "主业务库与只读模型依赖的 Mongo 启动配置。",
        "source": "bootstrap_file",
        "restart_required": True,
        "items": [
            ("host", "主机"),
            ("port", "端口"),
            ("db", "主库"),
            ("gantt_db", "Gantt 库"),
        ],
    },
    "redis": {
        "title": "Redis",
        "description": "运行队列与实时缓存依赖的 Redis 启动配置。",
        "source": "bootstrap_file",
        "restart_required": True,
        "items": [
            ("host", "主机"),
            ("port", "端口"),
            ("db", "DB"),
            ("password", "密码"),
        ],
    },
    "order_management": {
        "title": "订单管理",
        "description": "订单管理写库与 projection 库配置。",
        "source": "bootstrap_file",
        "restart_required": True,
        "items": [
            ("mongo_database", "Mongo 库"),
            ("projection_database", "Projection 库"),
        ],
    },
    "position_management": {
        "title": "仓位管理库",
        "description": "仓位管理单独 Mongo 库配置。",
        "source": "bootstrap_file",
        "restart_required": True,
        "items": [("mongo_database", "Mongo 库")],
    },
    "memory": {
        "title": "Memory",
        "description": "Memory 服务冷数据和 artifact 根路径。",
        "source": "bootstrap_file",
        "restart_required": True,
        "items": [
            ("mongodb.host", "Mongo 主机"),
            ("mongodb.port", "Mongo 端口"),
            ("mongodb.db", "Mongo 库"),
            ("cold_root", "冷目录"),
            ("artifact_root", "Artifact 根目录"),
        ],
    },
    "tdx": {
        "title": "TDX",
        "description": "通达信主目录和行情接口。",
        "source": "bootstrap_file",
        "restart_required": True,
        "items": [("home", "主目录"), ("hq.endpoint", "行情接口")],
    },
    "api": {
        "title": "API",
        "description": "前后端内部 API 基础地址。",
        "source": "bootstrap_file",
        "restart_required": True,
        "items": [("base_url", "基础地址")],
    },
    "xtdata": {
        "title": "XTData",
        "description": "XTData 端口配置。",
        "source": "bootstrap_file",
        "restart_required": True,
        "items": [("port", "端口")],
    },
    "runtime": {
        "title": "Runtime",
        "description": "运行期日志目录。",
        "source": "bootstrap_file",
        "restart_required": True,
        "items": [("log_dir", "日志目录")],
    },
}

SETTINGS_SECTION_META = {
    "notification": {
        "title": "通知",
        "description": "运行中的通知渠道真值，保存在 Mongo params。",
        "source": "params.notification",
        "restart_required": False,
        "items": [
            ("webhook.dingtalk.private", "私人钉钉机器人"),
            ("webhook.dingtalk.public", "公共钉钉机器人"),
        ],
    },
    "monitor": {
        "title": "监控",
        "description": "XTData 订阅模式、预热和消费节流配置。",
        "source": "params.monitor",
        "restart_required": False,
        "items": [
            ("xtdata.mode", "XTData 模式"),
            ("xtdata.max_symbols", "最大订阅数"),
            ("xtdata.queue_backlog_threshold", "队列背压阈值"),
            ("xtdata.prewarm.max_bars", "预热 bars"),
        ],
    },
    "xtquant": {
        "title": "XTQuant",
        "description": "交易连接、账户和 broker submit mode。",
        "source": "params.xtquant",
        "restart_required": False,
        "items": [
            ("path", "MiniQMT 路径"),
            ("account", "账户"),
            ("account_type", "账户类型"),
            ("broker_submit_mode", "Broker Submit Mode"),
        ],
    },
    "guardian": {
        "title": "Guardian",
        "description": "Guardian 股票阈值、网格间距和下单金额配置。",
        "source": "params.guardian",
        "restart_required": False,
        "items": [
            ("stock.lot_amount", "单次买入金额"),
            ("stock.threshold.mode", "阈值模式"),
            ("stock.threshold.percent", "阈值百分比"),
            ("stock.threshold.atr.period", "阈值 ATR 周期"),
            ("stock.threshold.atr.multiplier", "阈值 ATR 倍数"),
            ("stock.grid_interval.mode", "网格模式"),
            ("stock.grid_interval.percent", "网格百分比"),
            ("stock.grid_interval.atr.period", "网格 ATR 周期"),
            ("stock.grid_interval.atr.multiplier", "网格 ATR 倍数"),
        ],
    },
    "position_management": {
        "title": "仓位门禁",
        "description": "仓位管理阈值真值，保存在 pm_configs。",
        "source": "pm_configs.thresholds",
        "restart_required": False,
        "items": [
            ("allow_open_min_bail", "允许开新仓最低保证金"),
            ("holding_only_min_bail", "仅允许持仓内买入最低保证金"),
            ("single_symbol_position_limit", "单标的默认持仓上限"),
        ],
    },
}


class SystemConfigService:
    def __init__(
        self,
        *,
        database=None,
        settings=None,
        bootstrap_loader=load_bootstrap_config,
        bootstrap_reloader=reload_bootstrap_config,
        bootstrap_path_resolver=resolve_bootstrap_file_path,
    ):
        self.settings = settings or system_settings
        self.database = database or self.settings.database
        self.bootstrap_loader = bootstrap_loader
        self.bootstrap_reloader = bootstrap_reloader
        self.bootstrap_path_resolver = bootstrap_path_resolver

    def get_dashboard(self):
        return {
            "bootstrap": self.get_bootstrap_view(),
            "settings": self.get_settings_view(),
        }

    def get_bootstrap_view(self):
        values = self._bootstrap_values_from_config(self.bootstrap_loader())
        return {
            "file_path": str(self.bootstrap_path_resolver()),
            "values": values,
            "sections": self._build_sections(values, BOOTSTRAP_SECTION_META),
        }

    def get_settings_view(self):
        values = self._settings_values_from_provider(self.settings)
        return {
            "values": values,
            "sections": self._build_sections(values, SETTINGS_SECTION_META),
            "strategies": self._load_strategy_rows(),
        }

    def update_bootstrap(self, payload):
        current = self.get_bootstrap_view()["values"]
        merged = _deep_merge(current, payload or {})
        normalized = self._normalize_bootstrap_values(merged)
        path = self.bootstrap_path_resolver()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(normalized, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        self.bootstrap_reloader()
        return self.get_bootstrap_view()

    def update_settings(self, payload):
        current = self.get_settings_view()["values"]
        merged = _deep_merge(current, payload or {})
        normalized = self._normalize_settings_values(merged)

        self.database["params"].update_one(
            {"code": "notification"},
            {"$set": {"value": normalized["notification"]}},
            upsert=True,
        )
        self.database["params"].update_one(
            {"code": "monitor"},
            {"$set": {"value": normalized["monitor"]}},
            upsert=True,
        )
        self.database["params"].update_one(
            {"code": "xtquant"},
            {"$set": {"value": normalized["xtquant"]}},
            upsert=True,
        )
        self.database["params"].update_one(
            {"code": "guardian"},
            {"$set": {"value": normalized["guardian"]}},
            upsert=True,
        )
        self.database["pm_configs"].update_one(
            {"code": "default"},
            {
                "$set": {
                    "code": "default",
                    "enabled": True,
                    "thresholds": {
                        "allow_open_min_bail": normalized["position_management"][
                            "allow_open_min_bail"
                        ],
                        "holding_only_min_bail": normalized["position_management"][
                            "holding_only_min_bail"
                        ],
                        "single_symbol_position_limit": normalized[
                            "position_management"
                        ]["single_symbol_position_limit"],
                    },
                }
            },
            upsert=True,
        )
        self.settings.ensure_default_documents()
        self.settings.reload()
        return self.get_settings_view()

    def _load_strategy_rows(self):
        rows = []
        for document in self.database["strategies"].find({}):
            rows.append(
                {
                    "code": str(document.get("code") or ""),
                    "name": str(document.get("name") or ""),
                    "desc": str(document.get("desc") or ""),
                    "b62_uid": str(document.get("b62_uid") or ""),
                }
            )
        rows.sort(key=lambda item: item["code"])
        return rows

    @staticmethod
    def _bootstrap_values_from_config(config):
        return {
            "mongodb": {
                "host": config.mongodb.host,
                "port": config.mongodb.port,
                "db": config.mongodb.db,
                "gantt_db": config.mongodb.gantt_db,
            },
            "redis": {
                "host": config.redis.host,
                "port": config.redis.port,
                "db": config.redis.db,
                "password": config.redis.password,
            },
            "order_management": {
                "mongo_database": config.order_management.mongo_database,
                "projection_database": config.order_management.projection_database,
            },
            "position_management": {
                "mongo_database": config.position_management.mongo_database,
            },
            "memory": {
                "mongodb": {
                    "host": config.memory.mongodb.host,
                    "port": config.memory.mongodb.port,
                    "db": config.memory.mongodb.db,
                },
                "cold_root": config.memory.cold_root,
                "artifact_root": config.memory.artifact_root,
            },
            "tdx": {
                "home": config.tdx.home,
                "hq": {"endpoint": config.tdx.hq_endpoint},
            },
            "api": {
                "base_url": config.api.base_url,
            },
            "xtdata": {
                "port": config.xtdata.port,
            },
            "runtime": {
                "log_dir": config.runtime.log_dir,
            },
        }

    @staticmethod
    def _settings_values_from_provider(provider):
        return {
            "notification": {
                "webhook": {
                    "dingtalk": {
                        "private": provider.notification.dingtalk_private_webhook,
                        "public": provider.notification.dingtalk_public_webhook,
                    }
                }
            },
            "monitor": {
                "xtdata": {
                    "mode": normalize_xtdata_mode(provider.monitor.xtdata_mode),
                    "max_symbols": provider.monitor.xtdata_max_symbols,
                    "queue_backlog_threshold": provider.monitor.xtdata_queue_backlog_threshold,
                    "prewarm": {
                        "max_bars": provider.monitor.xtdata_prewarm_max_bars,
                    },
                },
            },
            "xtquant": {
                "path": provider.xtquant.path,
                "account": provider.xtquant.account,
                "account_type": provider.xtquant.account_type,
                "broker_submit_mode": provider.xtquant.broker_submit_mode,
            },
            "guardian": {
                "stock": {
                    "lot_amount": provider.guardian.stock_lot_amount,
                    "threshold": deepcopy(provider.guardian.stock_threshold),
                    "grid_interval": deepcopy(provider.guardian.stock_grid_interval),
                }
            },
            "position_management": {
                "allow_open_min_bail": provider.position_management.allow_open_min_bail,
                "holding_only_min_bail": provider.position_management.holding_only_min_bail,
                "single_symbol_position_limit": provider.position_management.single_symbol_position_limit,
            },
        }

    def _build_sections(self, values, meta):
        sections = []
        for key, section_meta in meta.items():
            items = []
            for field_key, label in section_meta["items"]:
                value = _deep_get(values.get(key, {}), field_key)
                items.append(
                    {
                        "key": f"{key}.{field_key}",
                        "field": field_key,
                        "label": label,
                        "value": value,
                        "editable": True,
                        "source": section_meta["source"],
                        "restart_required": section_meta["restart_required"],
                    }
                )
            sections.append(
                {
                    "key": key,
                    "title": section_meta["title"],
                    "description": section_meta["description"],
                    "source": section_meta["source"],
                    "restart_required": section_meta["restart_required"],
                    "items": items,
                }
            )
        return sections

    @staticmethod
    def _normalize_bootstrap_values(values):
        mongodb = values.get("mongodb") or {}
        redis = values.get("redis") or {}
        order_management = values.get("order_management") or {}
        position_management = values.get("position_management") or {}
        memory = values.get("memory") or {}
        memory_mongodb = memory.get("mongodb") or {}
        tdx = values.get("tdx") or {}
        tdx_hq = tdx.get("hq") or {}
        api = values.get("api") or {}
        xtdata = values.get("xtdata") or {}
        runtime = values.get("runtime") or {}
        return {
            "mongodb": {
                "host": _require_text(mongodb.get("host"), field_name="mongodb.host"),
                "port": _require_int(mongodb.get("port"), field_name="mongodb.port"),
                "db": _require_text(mongodb.get("db"), field_name="mongodb.db"),
                "gantt_db": _require_text(
                    mongodb.get("gantt_db"), field_name="mongodb.gantt_db"
                ),
            },
            "redis": {
                "host": _require_text(redis.get("host"), field_name="redis.host"),
                "port": _require_int(redis.get("port"), field_name="redis.port"),
                "db": _require_int(redis.get("db"), field_name="redis.db"),
                "password": str(redis.get("password") or ""),
            },
            "order_management": {
                "mongo_database": _require_text(
                    order_management.get("mongo_database"),
                    field_name="order_management.mongo_database",
                ),
                "projection_database": _require_text(
                    order_management.get("projection_database"),
                    field_name="order_management.projection_database",
                ),
            },
            "position_management": {
                "mongo_database": _require_text(
                    position_management.get("mongo_database"),
                    field_name="position_management.mongo_database",
                )
            },
            "memory": {
                "mongodb": {
                    "host": _require_text(
                        memory_mongodb.get("host"),
                        field_name="memory.mongodb.host",
                    ),
                    "port": _require_int(
                        memory_mongodb.get("port"),
                        field_name="memory.mongodb.port",
                    ),
                    "db": _require_text(
                        memory_mongodb.get("db"),
                        field_name="memory.mongodb.db",
                    ),
                },
                "cold_root": _require_text(
                    memory.get("cold_root"), field_name="memory.cold_root"
                ),
                "artifact_root": _require_text(
                    memory.get("artifact_root"),
                    field_name="memory.artifact_root",
                ),
            },
            "tdx": {
                "home": str(tdx.get("home") or ""),
                "hq": {
                    "endpoint": _require_text(
                        tdx_hq.get("endpoint"), field_name="tdx.hq.endpoint"
                    )
                },
            },
            "api": {
                "base_url": _require_text(
                    api.get("base_url"), field_name="api.base_url"
                )
            },
            "xtdata": {
                "port": _require_int(xtdata.get("port"), field_name="xtdata.port")
            },
            "runtime": {
                "log_dir": _require_text(
                    runtime.get("log_dir"), field_name="runtime.log_dir"
                )
            },
        }

    @staticmethod
    def _normalize_settings_values(values):
        notification = values.get("notification") or {}
        monitor = values.get("monitor") or {}
        xtdata = monitor.get("xtdata") or {}
        xtquant = values.get("xtquant") or {}
        guardian = values.get("guardian") or {}
        guardian_stock = guardian.get("stock") or {}
        position_management = values.get("position_management") or {}
        return {
            "notification": {
                "webhook": {
                    "dingtalk": {
                        "private": str(
                            _deep_get(notification, "webhook.dingtalk.private") or ""
                        ),
                        "public": str(
                            _deep_get(notification, "webhook.dingtalk.public") or ""
                        ),
                    }
                }
            },
            "monitor": {
                "xtdata": {
                    "mode": normalize_xtdata_mode(
                        _require_text(
                            xtdata.get("mode"), field_name="monitor.xtdata.mode"
                        )
                    ),
                    "max_symbols": _require_int(
                        xtdata.get("max_symbols"),
                        field_name="monitor.xtdata.max_symbols",
                    ),
                    "queue_backlog_threshold": _require_int(
                        xtdata.get("queue_backlog_threshold"),
                        field_name="monitor.xtdata.queue_backlog_threshold",
                    ),
                    "prewarm": {
                        "max_bars": _require_int(
                            _deep_get(xtdata, "prewarm.max_bars"),
                            field_name="monitor.xtdata.prewarm.max_bars",
                        )
                    },
                },
            },
            "xtquant": {
                "path": str(xtquant.get("path") or ""),
                "account": str(xtquant.get("account") or ""),
                "account_type": _require_text(
                    xtquant.get("account_type"), field_name="xtquant.account_type"
                ).upper(),
                "broker_submit_mode": _require_text(
                    xtquant.get("broker_submit_mode"),
                    field_name="xtquant.broker_submit_mode",
                ).lower(),
            },
            "guardian": {
                "stock": {
                    "lot_amount": _require_int(
                        guardian_stock.get("lot_amount"),
                        field_name="guardian.stock.lot_amount",
                    ),
                    "threshold": deepcopy(guardian_stock.get("threshold") or {}),
                    "grid_interval": deepcopy(
                        guardian_stock.get("grid_interval") or {}
                    ),
                }
            },
            "position_management": {
                "allow_open_min_bail": _require_float(
                    position_management.get("allow_open_min_bail"),
                    field_name="position_management.allow_open_min_bail",
                ),
                "holding_only_min_bail": _require_float(
                    position_management.get("holding_only_min_bail"),
                    field_name="position_management.holding_only_min_bail",
                ),
                "single_symbol_position_limit": _require_float(
                    position_management.get("single_symbol_position_limit"),
                    field_name="position_management.single_symbol_position_limit",
                ),
            },
        }


def _deep_get(payload, dotted_key, default=None):
    current = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _deep_merge(base, patch):
    if not isinstance(base, dict):
        return deepcopy(patch)
    merged = deepcopy(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _require_text(value, *, field_name):
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _require_int(value, *, field_name):
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an integer") from error


def _require_float(value, *, field_name):
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be finite") from error
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number

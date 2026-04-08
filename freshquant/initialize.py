from __future__ import annotations

import argparse
from copy import deepcopy

from pymongo import UpdateOne

from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.market_data.xtdata.pools import load_guardian_monitor_codes
from freshquant.system_config_service import SystemConfigService
from freshquant.system_settings import system_settings
from freshquant.util.code import (
    fq_util_code_append_market_code_suffix,
    normalize_to_base_code,
)

BOOTSTRAP_PROMPTS = [
    ("mongodb.host", "MongoDB 主机", "text"),
    ("mongodb.port", "MongoDB 端口", "int"),
    ("mongodb.db", "MongoDB 主库", "text"),
    ("mongodb.gantt_db", "MongoDB Gantt 库", "text"),
    ("redis.host", "Redis 主机", "text"),
    ("redis.port", "Redis 端口", "int"),
    ("redis.db", "Redis DB", "int"),
    ("redis.password", "Redis 密码", "text"),
    ("order_management.mongo_database", "Order Management Mongo 库", "text"),
    ("order_management.projection_database", "Order Projection 库", "text"),
    ("position_management.mongo_database", "Position Management Mongo 库", "text"),
    ("memory.mongodb.host", "Memory Mongo 主机", "text"),
    ("memory.mongodb.port", "Memory Mongo 端口", "int"),
    ("memory.mongodb.db", "Memory Mongo 库", "text"),
    ("memory.cold_root", "Memory 冷目录", "text"),
    ("memory.artifact_root", "Memory Artifact 根目录", "text"),
    ("tdx.home", "TDX 主目录", "text"),
    ("tdx.hq.endpoint", "TDX 行情接口", "text"),
    ("api.base_url", "API Base URL", "text"),
    ("xtdata.port", "XTData 端口", "int"),
    ("runtime.log_dir", "Runtime 日志目录", "text"),
]

SETTINGS_PROMPTS = [
    ("notification.webhook.dingtalk.private", "私人钉钉机器人", "text"),
    ("notification.webhook.dingtalk.public", "公共钉钉机器人", "text"),
    ("monitor.xtdata.mode", "XTData 模式", "text"),
    ("monitor.xtdata.max_symbols", "XTData 最大订阅数", "int"),
    ("monitor.xtdata.queue_backlog_threshold", "XTData 背压阈值", "int"),
    ("monitor.xtdata.prewarm.max_bars", "XTData 预热 bars", "int"),
    ("xtquant.path", "MiniQMT 路径", "text"),
    ("xtquant.account", "XT 账户", "text"),
    ("xtquant.account_type", "XT 账户类型", "text"),
    ("xtquant.broker_submit_mode", "Broker Submit Mode", "text"),
    ("xtquant.auto_repay.enabled", "XT 自动还款开关", "text"),
    ("xtquant.auto_repay.reserve_cash", "XT 自动还款留底现金", "float"),
    ("guardian.stock.lot_amount", "Guardian 单次买入金额", "int"),
    ("guardian.stock.threshold.mode", "Guardian 阈值模式", "text"),
    ("guardian.stock.threshold.percent", "Guardian 阈值百分比", "float"),
    ("guardian.stock.threshold.atr.period", "Guardian 阈值 ATR 周期", "int"),
    ("guardian.stock.threshold.atr.multiplier", "Guardian 阈值 ATR 倍数", "float"),
    ("guardian.stock.grid_interval.mode", "Guardian 网格模式", "text"),
    ("guardian.stock.grid_interval.percent", "Guardian 网格百分比", "float"),
    ("guardian.stock.grid_interval.atr.period", "Guardian 网格 ATR 周期", "int"),
    ("guardian.stock.grid_interval.atr.multiplier", "Guardian 网格 ATR 倍数", "float"),
    (
        "position_management.allow_open_min_bail",
        "允许开新仓最低保证金",
        "float",
    ),
    (
        "position_management.holding_only_min_bail",
        "仅允许持仓内买入最低保证金",
        "float",
    ),
]

_SKIP_RUNTIME_BOOTSTRAP = object()
_INITIALIZE_REBUILD_RESULT_COLLECTIONS = (
    ("om_broker_orders", "broker_order_documents"),
    ("om_execution_fills", "execution_fill_documents"),
    ("om_position_entries", "position_entry_documents"),
    ("om_entry_slices", "entry_slice_documents"),
    ("om_exit_allocations", "exit_allocation_documents"),
    ("om_reconciliation_gaps", "reconciliation_gap_documents"),
    ("om_reconciliation_resolutions", "reconciliation_resolution_documents"),
    ("om_ingest_rejections", "ingest_rejection_documents"),
)
_INITIALIZE_REBUILD_SUMMARY_KEYS = (
    "broker_orders",
    "execution_fills",
    "position_entries",
    "entry_slices",
    "exit_allocations",
    "reconciliation_gaps",
    "reconciliation_resolutions",
    "auto_open_entries",
    "auto_close_allocations",
    "ingest_rejections",
)
_INITIALIZE_PURGE_COLLECTIONS = (
    "om_order_requests",
    "om_order_events",
    "om_orders",
    "om_broker_orders",
    "om_trade_facts",
    "om_execution_fills",
    "om_buy_lots",
    "om_position_entries",
    "om_lot_slices",
    "om_entry_slices",
    "om_sell_allocations",
    "om_exit_allocations",
    "om_external_candidates",
    "om_reconciliation_gaps",
    "om_reconciliation_resolutions",
    "om_stoploss_bindings",
    "om_entry_stoploss_bindings",
    "om_ingest_rejections",
)
_INITIALIZE_COMPAT_COLLECTIONS = ("stock_fills_compat",)


def main(
    argv=None,
    *,
    prompt_provider=None,
    input_fn=input,
    output_fn=print,
    service=None,
    runtime_bootstrap_runner=None,
):
    parser = argparse.ArgumentParser(description="FreshQuant 新系统交互式初始化")
    parser.add_argument(
        "--skip-runtime-bootstrap",
        action="store_true",
        help="仅写配置，不执行 XT/credit subject/instrument strategy bootstrap",
    )
    args = parser.parse_args(argv)

    result = run_initialize_wizard(
        service=service,
        prompt_provider=prompt_provider,
        input_fn=input_fn,
        output_fn=output_fn,
        runtime_bootstrap_runner=(
            _SKIP_RUNTIME_BOOTSTRAP
            if args.skip_runtime_bootstrap
            else runtime_bootstrap_runner
        ),
    )
    return 0 if result else 1


def run_initialize_wizard(
    *,
    service=None,
    prompt_provider=None,
    input_fn=input,
    output_fn=print,
    runtime_bootstrap_runner=None,
):
    service = service or SystemConfigService()
    dashboard = service.get_dashboard()
    bootstrap_values = deepcopy(dashboard["bootstrap"]["values"])
    settings_values = deepcopy(dashboard["settings"]["values"])
    prompt = prompt_provider or _make_interactive_prompt_provider(
        input_fn=input_fn,
        output_fn=output_fn,
    )

    output_fn("FreshQuant 新系统初始化向导")
    output_fn(f"Bootstrap 文件: {dashboard['bootstrap']['file_path']}")
    output_fn("")
    output_fn("[阶段 1/3] 交互式覆盖启动配置")
    _prompt_into_values(
        bootstrap_values,
        BOOTSTRAP_PROMPTS,
        scope="bootstrap",
        prompt_provider=prompt,
    )
    saved_bootstrap = service.update_bootstrap(bootstrap_values)

    output_fn("")
    output_fn("[阶段 2/3] 交互式覆盖 Mongo 系统设置")
    _prompt_into_values(
        settings_values,
        SETTINGS_PROMPTS,
        scope="settings",
        prompt_provider=prompt,
    )
    saved_settings = service.update_settings(settings_values)

    output_fn("")
    output_fn("[阶段 3/3] 运行态 bootstrap")
    if runtime_bootstrap_runner is _SKIP_RUNTIME_BOOTSTRAP:
        runtime_summary = {
            "xt": {"assets": 0, "positions": 0, "orders": 0, "trades": 0},
            "credit_subjects": {"count": 0},
            "instrument_strategy": {"count": 0, "strategy_id": ""},
            "skipped": True,
        }
        output_fn("运行态 bootstrap 已跳过")
    else:
        runtime_runner = runtime_bootstrap_runner or (
            lambda: run_runtime_bootstrap(settings_provider=service.settings)
        )
        runtime_summary = runtime_runner()
        output_fn("运行态 bootstrap 完成")

    output_fn(
        "XT 同步: 资产 {assets} / 持仓 {positions} / 委托 {orders} / 成交 {trades}".format(
            **(runtime_summary.get("xt") or {})
        )
    )
    rebuild_summary = (runtime_summary.get("xt") or {}).get("rebuild") or {}
    if rebuild_summary:
        if rebuild_summary.get("skipped"):
            output_fn(
                "Order ledger bootstrap rebuild: skipped ({reason})".format(
                    reason=rebuild_summary.get("reason") or "unknown"
                )
            )
        else:
            output_fn(
                "Order ledger bootstrap rebuild: entries {position_entries} / auto_open {auto_open_entries}".format(
                    position_entries=int(rebuild_summary.get("position_entries") or 0),
                    auto_open_entries=int(
                        rebuild_summary.get("auto_open_entries") or 0
                    ),
                )
            )
    output_fn(
        "instrument_strategy 补齐: {count}".format(
            count=(runtime_summary.get("instrument_strategy") or {}).get("count", 0)
        )
    )

    return {
        "bootstrap": saved_bootstrap["values"],
        "settings": saved_settings["values"],
        "runtime": runtime_summary,
    }


def run_runtime_bootstrap(
    *,
    settings_provider=system_settings,
    xt_runtime_sync_runner=None,
    credit_subject_sync_runner=None,
    monitor_code_loader=load_guardian_monitor_codes,
    instrument_strategy_writer=None,
    instrument_type_loader=None,
    instrument_code_loader=None,
):
    xt_runtime_sync_runner = xt_runtime_sync_runner or _default_xt_runtime_sync_runner
    credit_subject_sync_runner = (
        credit_subject_sync_runner or _default_credit_subject_sync_runner
    )
    instrument_strategy_writer = (
        instrument_strategy_writer or _default_instrument_strategy_writer
    )
    instrument_type_loader = instrument_type_loader or _default_instrument_type_loader
    instrument_code_loader = instrument_code_loader or _default_instrument_code_loader

    xt_summary = xt_runtime_sync_runner()
    credit_subject_summary = credit_subject_sync_runner()
    strategy_id = str(settings_provider.get_strategy_id("Guardian") or "")
    monitor_codes = monitor_code_loader(
        max_symbols=settings_provider.monitor.xtdata_max_symbols
    )

    count = 0
    for raw_code in monitor_codes or []:
        base_code = normalize_to_base_code(raw_code)
        if not base_code or len(base_code) != 6:
            continue
        instrument_code = instrument_code_loader(base_code)
        instrument_type = instrument_type_loader(base_code)
        instrument_kind = "etf" if instrument_type == InstrumentType.ETF_CN else "stock"
        instrument_strategy_writer(instrument_code, instrument_kind, strategy_id)
        count += 1

    return {
        "xt": xt_summary,
        "credit_subjects": credit_subject_summary,
        "instrument_strategy": {
            "count": count,
            "strategy_id": strategy_id,
        },
    }


def _default_xt_runtime_sync_runner():
    from fqxtrade.xtquant.fqtype import FqXtPosition

    xt_trader, acc, _ = _ensure_xt_runtime_connection()
    if xt_trader is None or acc is None:
        return {
            "assets": 0,
            "positions": 0,
            "orders": 0,
            "trades": 0,
            "rebuild": {
                "skipped": True,
                "reason": "xt_connection_unavailable",
            },
        }
    asset = xt_trader.query_stock_asset(acc)
    positions = list(xt_trader.query_stock_positions(acc) or [])
    account_id = str(getattr(acc, "account_id", "") or "").strip()
    position_documents = [FqXtPosition(position).to_dict() for position in positions]
    _persist_xt_runtime_truth(
        account_id=account_id,
        asset=asset,
        positions=position_documents,
        orders=[],
        trades=[],
    )
    rebuild_summary = _bootstrap_order_ledger_from_synced_truth(
        xt_positions=position_documents,
    )
    return {
        "assets": 1 if asset is not None else 0,
        "positions": len(position_documents),
        "orders": 0,
        "trades": 0,
        "rebuild": rebuild_summary,
    }


def _persist_xt_runtime_truth(*, account_id, asset, positions, orders, trades):
    from fqxtrade.database.mongodb import DBfreshquant

    from freshquant.xt_account_sync.persistence import persist_assets, persist_positions

    normalized_account_id = str(account_id or "").strip()
    if asset is not None:
        persist_assets([asset], collection=DBfreshquant["xt_assets"])
    if normalized_account_id:
        persist_positions(
            positions,
            account_id=normalized_account_id,
            collection=DBfreshquant["xt_positions"],
        )
    _upsert_xt_runtime_documents(
        collection=DBfreshquant["xt_orders"],
        documents=orders,
        identity_fields=("account_id", "order_id"),
        scope_query=(
            {"account_id": normalized_account_id} if normalized_account_id else None
        ),
    )
    _upsert_xt_runtime_documents(
        collection=DBfreshquant["xt_trades"],
        documents=trades,
        identity_fields=("account_id", "traded_id"),
        scope_query=(
            {"account_id": normalized_account_id} if normalized_account_id else None
        ),
    )
    return {
        "account_id": normalized_account_id,
        "assets": 1 if asset is not None else 0,
        "positions": len(list(positions or [])),
        "orders": len(list(orders or [])),
        "trades": len(list(trades or [])),
    }


def _upsert_xt_runtime_documents(
    *,
    collection,
    documents,
    identity_fields,
    scope_query=None,
):
    if scope_query:
        collection.delete_many(dict(scope_query))
    batch = []
    for document in list(documents or []):
        identity = {}
        skip_document = False
        for field in identity_fields:
            value = document.get(field)
            if value in {None, ""}:
                skip_document = True
                break
            identity[field] = value
        if skip_document:
            continue
        batch.append(UpdateOne(identity, {"$set": dict(document)}, upsert=True))
    if batch:
        collection.bulk_write(batch)
    return len(batch)


def _bootstrap_order_ledger_from_synced_truth(
    *,
    xt_positions,
    database=None,
    projection_database=None,
    rebuild_service=None,
    compat_view_rebuilder=None,
):
    from freshquant.order_management.db import get_order_management_db
    from freshquant.order_management.rebuild import OrderLedgerV2RebuildService

    database = database or get_order_management_db()
    rebuild_service = rebuild_service or OrderLedgerV2RebuildService()
    rebuild_result = rebuild_service.build_from_truth(
        xt_orders=[],
        xt_trades=[],
        xt_positions=xt_positions,
    )
    _purge_initialize_order_ledger(database=database)
    for collection_name, document_key in _INITIALIZE_REBUILD_RESULT_COLLECTIONS:
        documents = list(rebuild_result.get(document_key) or [])
        if documents:
            database[collection_name].insert_many(documents, ordered=False)

    compat_view_rebuilder = compat_view_rebuilder or _rebuild_initialize_compat_views
    compat_summary = compat_view_rebuilder(
        order_database=database,
        projection_database=projection_database,
    )

    summary = {"skipped": False}
    for key in _INITIALIZE_REBUILD_SUMMARY_KEYS:
        summary[key] = int(rebuild_result.get(key) or 0)
    summary["purged_collections"] = list(_INITIALIZE_PURGE_COLLECTIONS)
    summary["compat"] = compat_summary
    return summary


def _purge_initialize_order_ledger(*, database, collection_names=None):
    for collection_name in list(collection_names or _INITIALIZE_PURGE_COLLECTIONS):
        database[collection_name].delete_many({})
    return list(collection_names or _INITIALIZE_PURGE_COLLECTIONS)


def _rebuild_initialize_compat_views(*, order_database, projection_database=None):
    from freshquant.order_management.db import get_projection_db
    from freshquant.order_management.projection.stock_fills_compat import sync_symbols
    from freshquant.order_management.repository import OrderManagementRepository

    projection_database = projection_database or get_projection_db()
    repository = OrderManagementRepository(database=order_database)
    for collection_name in _INITIALIZE_COMPAT_COLLECTIONS:
        projection_database[collection_name].delete_many({})
    compat_summary = sync_symbols(
        repository=repository,
        database=projection_database,
    )
    compat_summary["rebuilt_collections"] = list(_INITIALIZE_COMPAT_COLLECTIONS)
    return compat_summary


def _ensure_xt_runtime_connection():
    from morningglory.fqxtrade.fqxtrade.xtquant.broker import connect, trading_manager

    xt_trader, acc, connected = trading_manager.get_connection()
    if xt_trader is not None and acc is not None and connected:
        return xt_trader, acc, connected

    xt_trader, acc, connected = connect()
    if xt_trader is not None and acc is not None and connected:
        trading_manager.update_connection(xt_trader, acc, connected)
    return xt_trader, acc, connected


def _default_credit_subject_sync_runner():
    from freshquant.order_management.credit_subjects.service import (
        sync_credit_subjects_once,
    )

    return sync_credit_subjects_once()


def _default_instrument_strategy_writer(
    instrument_code,
    instrument_type,
    strategy_name,
):
    from freshquant.trade.trade import saveInstrumentStrategy

    return saveInstrumentStrategy(instrument_code, instrument_type, strategy_name)


def _default_instrument_type_loader(code):
    from freshquant.instrument.general import query_instrument_type

    return query_instrument_type(code)


def _default_instrument_code_loader(code):
    return fq_util_code_append_market_code_suffix(
        code,
        upper_case=True,
    )


def _prompt_into_values(values, field_specs, *, scope, prompt_provider):
    for field_key, label, kind in field_specs:
        current_value = _deep_get(values, field_key)
        next_value = prompt_provider(f"{scope}.{field_key}", label, current_value, kind)
        _deep_set(values, field_key, next_value)
    return values


def _make_interactive_prompt_provider(*, input_fn=input, output_fn=print):
    def _prompt(field_key, label, default, kind):
        display_default = _format_default(default, kind)
        raw = input_fn(f"{label} [{display_default}]: ").strip()
        if raw == "":
            return default
        try:
            if kind == "int":
                return int(raw)
            if kind == "float":
                return float(raw)
            if kind == "bool":
                return raw.lower() in {"1", "true", "yes", "y", "是"}
            if kind == "list":
                return [item.strip() for item in raw.split(",") if item.strip()]
            return raw
        except ValueError:
            output_fn(f"{field_key} 输入无效，保留当前值。")
            return default

    return _prompt


def _format_default(value, kind):
    if kind == "list":
        return ", ".join(value or [])
    if kind == "bool":
        return "yes" if value else "no"
    return str(value)


def _deep_get(payload, dotted_key, default=None):
    current = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _deep_set(payload, dotted_key, value):
    current = payload
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


if __name__ == "__main__":
    raise SystemExit(main())

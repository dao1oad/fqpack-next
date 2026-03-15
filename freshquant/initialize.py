from __future__ import annotations

import argparse
from copy import deepcopy

from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.market_data.xtdata.pools import load_monitor_codes
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
    ("monitor.stock.periods", "监控股票周期（逗号分隔）", "list"),
    ("monitor.xtdata.mode", "XTData 模式", "text"),
    ("monitor.xtdata.max_symbols", "XTData 最大订阅数", "int"),
    ("monitor.xtdata.queue_backlog_threshold", "XTData 背压阈值", "int"),
    ("monitor.xtdata.prewarm.max_bars", "XTData 预热 bars", "int"),
    ("xtquant.path", "MiniQMT 路径", "text"),
    ("xtquant.account", "XT 账户", "text"),
    ("xtquant.account_type", "XT 账户类型", "text"),
    ("xtquant.broker_submit_mode", "Broker Submit Mode", "text"),
    ("guardian.stock.position_pct", "Guardian 仓位百分比", "float"),
    ("guardian.stock.auto_open", "Guardian 自动开仓（yes/no）", "bool"),
    ("guardian.stock.lot_amount", "Guardian 单次买入金额", "int"),
    ("guardian.stock.min_amount", "Guardian 最小买入金额", "int"),
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
    monitor_code_loader=load_monitor_codes,
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
        mode=settings_provider.monitor.xtdata_mode,
        max_symbols=settings_provider.monitor.xtdata_max_symbols,
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
    from morningglory.fqxtrade.fqxtrade.xtquant.puppet import (
        sync_orders,
        sync_positions,
        sync_summary,
        sync_trades,
    )

    asset = sync_summary()
    positions = sync_positions() or []
    orders = sync_orders() or []
    trades = sync_trades() or []
    return {
        "assets": 1 if asset else 0,
        "positions": len(positions),
        "orders": len(orders),
        "trades": len(trades),
    }


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

# -*- coding: utf-8 -*-

"""持仓同步后的价位配置收敛：所有未持仓标的的止盈/买入三档配置一律关闭。

判据唯一：``xt_positions`` 中 ``volume>0`` 即持仓；其余（从未持仓、已清仓、
volume=0、已驱逐）均视为未持仓。收敛只对「启用配置 ∩ 未持仓」差集写库，
天然幂等；任一步失败仅 warning，不阻塞持仓同步主链。
"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from freshquant.util.code import normalize_to_base_code


def _normalize_code6(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    code = str(normalize_to_base_code(raw) or "")
    if len(code) == 6 and code.isdigit():
        return code
    return None


def _load_holding_codes(positions_collection) -> set[str] | None:
    codes: set[str] = set()
    try:
        cursor = positions_collection.find(
            {"volume": {"$gt": 0}},
            {"stock_code": 1, "code": 1, "symbol": 1},
        )
    except Exception:
        # 持仓查询失败（上游空快照守卫已拦截正常空快照）：返回 None 表示
        # 数据不可用，整体跳过收敛，绝不按“空持仓”全量关闭。
        logger.warning("position cleanup: positions query failed, skip convergence")
        return None
    for doc in cursor or []:
        for field in ("symbol", "stock_code", "code"):
            code = _normalize_code6(doc.get(field))
            if code:
                codes.add(code)
                break
    return codes


def _iter_enabled_buy_configs(config_collection):
    try:
        cursor = config_collection.find(
            {
                "$or": [
                    {"enabled": True},
                    {"buy_enabled.0": True},
                    {"buy_enabled.1": True},
                    {"buy_enabled.2": True},
                ]
            },
            {"code": 1},
        )
    except Exception as exc:
        logger.warning("position cleanup: list buy configs failed: %s", exc)
        return
    for doc in cursor or []:
        yield doc


def _iter_enabled_takeprofit_profiles(profile_collection):
    try:
        cursor = profile_collection.find(
            {
                "$or": [
                    {"tiers.0.manual_enabled": True},
                    {"tiers.1.manual_enabled": True},
                    {"tiers.2.manual_enabled": True},
                ]
            },
            {"symbol": 1, "tiers": 1},
        )
    except Exception as exc:
        logger.warning("position cleanup: list takeprofit profiles failed: %s", exc)
        return
    for doc in cursor or []:
        yield doc


def converge_position_configs(
    *,
    positions_collection,
    buy_grid_service=None,
    takeprofit_service=None,
    buy_config_collection=None,
    takeprofit_profile_collection=None,
    event_emitter: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    """对「启用配置 ∩ 未持仓」差集执行关闭（止盈逐档 + 买入三档）。

    参数均可注入以便测试；默认使用正式服务与集合。
    """
    from freshquant.strategy.guardian_buy_grid import (
        get_guardian_buy_grid_service,
    )
    from freshquant.tpsl.takeprofit_service import TakeprofitService

    buy_grid_service = buy_grid_service or get_guardian_buy_grid_service()
    takeprofit_service = takeprofit_service or TakeprofitService()
    buy_config_collection = (
        buy_config_collection or buy_grid_service._config_collection()
    )
    takeprofit_profile_collection = (
        takeprofit_profile_collection
        or takeprofit_service.repository.takeprofit_profiles
    )

    holding_codes = _load_holding_codes(positions_collection)
    if holding_codes is None:
        return {
            "skipped": True,
            "reason": "positions_unavailable",
            "holding_count": 0,
            "buy_configs_disabled": [],
            "takeprofit_profiles_disabled": [],
            "disabled_total": 0,
        }

    disabled_buy_codes: list[str] = []
    for doc in _iter_enabled_buy_configs(buy_config_collection):
        code = _normalize_code6(doc.get("code"))
        if not code or code in holding_codes:
            continue
        try:
            buy_grid_service.disable_grid(code, updated_by="xt_account_sync")
            disabled_buy_codes.append(code)
        except Exception as exc:
            logger.warning(
                "position cleanup: disable buy grid failed for %s: %s", code, exc
            )

    disabled_tp_symbols: list[str] = []
    for profile in _iter_enabled_takeprofit_profiles(takeprofit_profile_collection):
        symbol = _normalize_code6(profile.get("symbol"))
        if not symbol or symbol in holding_codes:
            continue
        try:
            enabled_levels = [
                int(tier.get("level"))
                for tier in (profile.get("tiers") or [])
                if tier.get("manual_enabled")
            ]
            for level in enabled_levels:
                takeprofit_service.set_tier_manual_enabled(
                    symbol,
                    level=level,
                    enabled=False,
                    updated_by="xt_account_sync",
                )
            disabled_tp_symbols.append(symbol)
        except Exception as exc:
            logger.warning(
                "position cleanup: disable takeprofit failed for %s: %s",
                symbol,
                exc,
            )

    result: dict[str, Any] = {
        "holding_count": len(holding_codes),
        "buy_configs_disabled": disabled_buy_codes,
        "takeprofit_profiles_disabled": disabled_tp_symbols,
        "disabled_total": len(disabled_buy_codes) + len(disabled_tp_symbols),
    }
    if event_emitter is not None and result["disabled_total"] > 0:
        try:
            event_emitter(
                {
                    "node": "position_cleanup_disabled",
                    "reason_code": "non_holding_config_disabled",
                    **result,
                }
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("position cleanup: emit runtime event failed: %s", exc)
    return result

# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from loguru import logger

_runtime_logger = None


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        from freshquant.runtime_observability.logger import RuntimeEventLogger

        _runtime_logger = RuntimeEventLogger("guardian_event")
    return _runtime_logger


def _emit_signal_calc_event(*, node, reason_code, symbol="", payload=None):
    """信号计算链失败/降级的显式运行事件（根②：读不到 = 不交易 + 告警）。"""

    try:
        return bool(
            _get_runtime_logger().emit(
                {
                    "component": "guardian_event",
                    "node": node,
                    "status": "error",
                    "reason_code": reason_code,
                    "symbol": symbol,
                    "payload": dict(payload or {}),
                }
            )
        )
    except Exception:  # pragma: no cover - 观测路径失败不影响主链
        return False


@dataclass(frozen=True)
class GuardianSignal:
    signal_type: str
    fire_time: datetime
    price: float
    stop_lose_price: float
    tags: list[str]


def _stop_lose_from_bi(
    *,
    bi_list: list[int],
    idx: int,
    is_buy: bool,
    high_list: list[float],
    low_list: list[float],
    close_list: list[float],
) -> float:
    if idx < 0:
        return 0.0
    if is_buy:
        for j in range(idx, -1, -1):
            if int(bi_list[j]) == -1:
                return float(low_list[j])
        return float(close_list[idx]) * 0.95
    for j in range(idx, -1, -1):
        if int(bi_list[j]) == 1:
            return float(high_list[j])
    return float(close_list[idx]) * 1.05


def _clxs_last_signal(
    *,
    open_list: list[float],
    high_list: list[float],
    low_list: list[float],
    close_list: list[float],
    model_opt: int,
    trend_opt: int,
) -> int:
    try:
        from fqcopilot import fq_clxs  # type: ignore
    except Exception as e:  # pragma: no cover
        logger.warning(f"fqcopilot not available; skip signal calc: {e}")
        _emit_signal_calc_event(
            node="clxs_signal",
            reason_code="signal_calc_unavailable",
            payload={"model_opt": model_opt, "detail": "fqcopilot_unavailable"},
        )
        return 0

    length = len(close_list)
    if length <= 0:
        return 0
    vol = [1.0] * length
    try:
        sigs = fq_clxs(
            length,
            high_list,
            low_list,
            open_list,
            close_list,
            vol,
            wave_opt=1560,
            stretch_opt=0,
            trend_opt=int(trend_opt),
            model_opt=int(model_opt),
        )
    except Exception as e:
        logger.debug(f"fq_clxs failed model_opt={model_opt}: {e}")
        _emit_signal_calc_event(
            node="clxs_signal",
            reason_code="signal_calc_unavailable",
            payload={"model_opt": model_opt, "detail": str(e)[:200]},
        )
        return 0

    try:
        return int(sigs[-1])
    except Exception as e:
        _emit_signal_calc_event(
            node="clxs_signal",
            reason_code="signal_calc_unavailable",
            payload={"model_opt": model_opt, "detail": str(e)[:200]},
        )
        return 0


def _ensure_bi_list(
    data: dict[str, Any],
    *,
    high_list: list[float],
    low_list: list[float],
    close_list: list[float],
) -> list[int] | None:
    """解析/计算 bi 列表；读不到返回 None（fail-closed），合法全零列表原样返回。"""

    bi = data.get("_bi_signal_list")
    if isinstance(bi, list) and len(bi) == len(high_list):
        try:
            return [int(x) for x in bi]
        except Exception as e:
            _emit_signal_calc_event(
                node="bi_list",
                reason_code="bi_list_unavailable",
                payload={"detail": str(e)[:200]},
            )
            return None

    try:
        from fqchan04 import fq_recognise_bi  # type: ignore
    except Exception as e:  # pragma: no cover
        logger.warning(f"fqchan04 not available; bi_list missing: {e}")
        _emit_signal_calc_event(
            node="bi_list",
            reason_code="bi_list_unavailable",
            payload={"detail": "fqchan04_unavailable"},
        )
        return None

    try:
        return [
            int(x)
            for x in fq_recognise_bi(len(high_list), high_list, low_list, close_list)
        ]
    except Exception as e:
        _emit_signal_calc_event(
            node="bi_list",
            reason_code="bi_list_unavailable",
            payload={"detail": str(e)[:200]},
        )
        return None


def calculate_guardian_signals_latest(
    *,
    data: dict[str, Any],
    fire_time: datetime,
    min_zhongshu_count: int = 2,
) -> list[GuardianSignal]:
    """
    仅计算“最新一根 bar”是否触发 Guardian 的 6 类信号：
    - buy/sell_zs_huila
    - buy/sell_v_reverse
    - macd_bullish/bearish_divergence
    """
    if not isinstance(data, dict):
        return []

    try:
        open_list = [float(x) for x in (data.get("open") or [])]
        high_list = [float(x) for x in (data.get("high") or [])]
        low_list = [float(x) for x in (data.get("low") or [])]
        close_list = [float(x) for x in (data.get("close") or [])]
    except Exception as e:
        _emit_signal_calc_event(
            node="signals_latest",
            reason_code="signal_calc_unavailable",
            payload={"detail": str(e)[:200]},
        )
        return []

    n = len(close_list)
    if n <= 0 or not (
        len(open_list) == n and len(high_list) == n and len(low_list) == n
    ):
        return []

    idx = n - 1
    bi_list = _ensure_bi_list(
        data,
        high_list=high_list,
        low_list=low_list,
        close_list=close_list,
    )
    if bi_list is None:
        # bi 列表是止损价与信号质量的必需输入；读不到 = 不交易（fail-closed）。
        return []

    out: list[GuardianSignal] = []

    # Pullback (model_opt=9)
    sig = _clxs_last_signal(
        open_list=open_list,
        high_list=high_list,
        low_list=low_list,
        close_list=close_list,
        model_opt=9,
        trend_opt=0,
    )
    if sig > 0:
        out.append(
            GuardianSignal(
                signal_type="buy_zs_huila",
                fire_time=fire_time,
                price=float(close_list[idx]),
                stop_lose_price=_stop_lose_from_bi(
                    bi_list=bi_list,
                    idx=idx,
                    is_buy=True,
                    high_list=high_list,
                    low_list=low_list,
                    close_list=close_list,
                ),
                tags=[],
            )
        )
    elif sig < 0:
        out.append(
            GuardianSignal(
                signal_type="sell_zs_huila",
                fire_time=fire_time,
                price=float(close_list[idx]),
                stop_lose_price=_stop_lose_from_bi(
                    bi_list=bi_list,
                    idx=idx,
                    is_buy=False,
                    high_list=high_list,
                    low_list=low_list,
                    close_list=close_list,
                ),
                tags=[],
            )
        )

    # V reversal (model_opt=12)
    sig = _clxs_last_signal(
        open_list=open_list,
        high_list=high_list,
        low_list=low_list,
        close_list=close_list,
        model_opt=12,
        trend_opt=0,
    )
    if sig > 0:
        out.append(
            GuardianSignal(
                signal_type="buy_v_reverse",
                fire_time=fire_time,
                price=float(close_list[idx]),
                stop_lose_price=_stop_lose_from_bi(
                    bi_list=bi_list,
                    idx=idx,
                    is_buy=True,
                    high_list=high_list,
                    low_list=low_list,
                    close_list=close_list,
                ),
                tags=[],
            )
        )
    elif sig < 0:
        out.append(
            GuardianSignal(
                signal_type="sell_v_reverse",
                fire_time=fire_time,
                price=float(close_list[idx]),
                stop_lose_price=_stop_lose_from_bi(
                    bi_list=bi_list,
                    idx=idx,
                    is_buy=False,
                    high_list=high_list,
                    low_list=low_list,
                    close_list=close_list,
                ),
                tags=[],
            )
        )

    # MACD divergence (model_opt=8, trend_opt=1)
    sig = _clxs_last_signal(
        open_list=open_list,
        high_list=high_list,
        low_list=low_list,
        close_list=close_list,
        model_opt=8,
        trend_opt=1,
    )
    if sig != 0:
        zhongshu_count = abs(int(sig)) // 100
        if int(zhongshu_count) >= int(min_zhongshu_count):
            if sig > 0:
                out.append(
                    GuardianSignal(
                        signal_type="macd_bullish_divergence",
                        fire_time=fire_time,
                        price=float(close_list[idx]),
                        stop_lose_price=_stop_lose_from_bi(
                            bi_list=bi_list,
                            idx=idx,
                            is_buy=True,
                            high_list=high_list,
                            low_list=low_list,
                            close_list=close_list,
                        ),
                        tags=[],
                    )
                )
            else:
                out.append(
                    GuardianSignal(
                        signal_type="macd_bearish_divergence",
                        fire_time=fire_time,
                        price=float(close_list[idx]),
                        stop_lose_price=_stop_lose_from_bi(
                            bi_list=bi_list,
                            idx=idx,
                            is_buy=False,
                            high_list=high_list,
                            low_list=low_list,
                            close_list=close_list,
                        ),
                        tags=[],
                    )
                )

    return out

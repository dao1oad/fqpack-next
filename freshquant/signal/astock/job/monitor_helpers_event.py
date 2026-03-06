# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from loguru import logger


@dataclass(frozen=True)
class GuardianSignal:
    signal_type: str
    fire_time: datetime
    price: float
    stop_lose_price: float
    tags: list[str]


def _stop_loss_from_bi(
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
        return 0

    try:
        return int(sigs[-1])
    except Exception:
        return 0


def _ensure_bi_list(
    data: dict[str, Any], *, high_list: list[float], low_list: list[float]
) -> list[int]:
    bi = data.get("_bi_signal_list")
    if isinstance(bi, list) and len(bi) == len(high_list):
        try:
            return [int(x) for x in bi]
        except Exception:
            pass

    try:
        from fqchan04 import fq_recognise_bi  # type: ignore
    except Exception as e:  # pragma: no cover
        logger.warning(f"fqchan04 not available; bi_list missing: {e}")
        return [0] * len(high_list)

    try:
        return [int(x) for x in fq_recognise_bi(len(high_list), high_list, low_list)]
    except Exception:
        return [0] * len(high_list)


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
    except Exception:
        return []

    n = len(close_list)
    if n <= 0 or not (
        len(open_list) == n and len(high_list) == n and len(low_list) == n
    ):
        return []

    idx = n - 1
    bi_list = _ensure_bi_list(data, high_list=high_list, low_list=low_list)

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
                stop_lose_price=_stop_loss_from_bi(
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
                stop_lose_price=_stop_loss_from_bi(
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
                stop_lose_price=_stop_loss_from_bi(
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
                stop_lose_price=_stop_loss_from_bi(
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
                        stop_lose_price=_stop_loss_from_bi(
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
                        stop_lose_price=_stop_loss_from_bi(
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

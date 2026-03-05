# -*- coding: utf-8 -*-

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from freshquant.basic.util import get_zhong_shu_data, str_from_timestamp
from freshquant.config import cfg
from freshquant.instrument.general import query_instrument_info
from freshquant.util.period import to_frontend_period, to_backend_period


def _safe_local_timestamp(dt_obj: Any) -> int:
    try:
        if dt_obj is None:
            return 0
        if hasattr(dt_obj, "to_pydatetime"):
            dt_obj = dt_obj.to_pydatetime()
        if getattr(dt_obj, "tzinfo", None) is not None:
            dt_obj = dt_obj.replace(tzinfo=None)
        if hasattr(dt_obj, "timestamp"):
            return int(dt_obj.timestamp())
    except Exception:
        pass
    return 0


def _format_dt_ymdhm(dt_obj: Any) -> str:
    if dt_obj is None:
        return ""
    try:
        if hasattr(dt_obj, "to_pydatetime"):
            dt_obj = dt_obj.to_pydatetime()
        if getattr(dt_obj, "tzinfo", None) is None:
            dt_obj = cfg.TZ.localize(dt_obj)
        return dt_obj.strftime("%Y-%m-%d %H:%M")
    except Exception:
        try:
            return str(dt_obj)
        except Exception:
            return ""


@dataclass(frozen=True)
class ChanlunPayload:
    code: str
    period_backend: str
    data: dict[str, Any]


def build_chanlun_payload(
    *,
    code: str,
    period_backend: str,
    merged_df: pd.DataFrame,
    fc_res: dict[str, Any],
    bar_time_ts: int | None = None,
) -> ChanlunPayload:
    period_backend = to_backend_period(period_backend)
    period_front = to_frontend_period(period_backend)

    n = int(len(merged_df))
    bi_sig = fc_res.get("bi") or []
    duan_sig = fc_res.get("duan") or []
    duan_high_sig = fc_res.get("duan_high") or []
    pivots_raw = fc_res.get("pivots") or []
    pivots_high_raw = fc_res.get("pivots_high") or []

    def _signal_to_vertex(sig_list: list[int]):
        dt_list: list[int] = []
        data_list: list[float] = []
        for idx, val in enumerate(sig_list):
            if val == 1:
                dt_list.append(_safe_local_timestamp(merged_df["datetime"].iloc[idx]))
                data_list.append(float(merged_df["high"].iloc[idx]))
            elif val == -1:
                dt_list.append(_safe_local_timestamp(merged_df["datetime"].iloc[idx]))
                data_list.append(float(merged_df["low"].iloc[idx]))
        return {"dt": dt_list, "data": data_list}

    bi_data = _signal_to_vertex(bi_sig)
    duan_data = _signal_to_vertex(duan_sig)
    higher_duan_data = _signal_to_vertex(duan_high_sig)

    def _pivots_to_entanglements(pivots_input):
        class _Ent:
            __slots__ = (
                "start",
                "end",
                "startTime",
                "endTime",
                "zg",
                "zd",
                "gg",
                "dd",
                "direction",
                "top",
                "bottom",
            )

        ents = []
        for p in pivots_input or []:
            e = _Ent()
            e.start = int(p.get("start", -1))
            e.end = int(p.get("end", -1))
            e.startTime = (
                _safe_local_timestamp(merged_df["datetime"].iloc[e.start])
                if 0 <= e.start < n
                else 0
            )
            e.endTime = (
                _safe_local_timestamp(merged_df["datetime"].iloc[e.end])
                if 0 <= e.end < n
                else 0
            )
            e.zg = float(p.get("zg") or 0.0)
            e.zd = float(p.get("zd") or 0.0)
            e.gg = float(p.get("gg") or 0.0)
            e.dd = float(p.get("dd") or 0.0)
            e.direction = int(p.get("direction") or 0)
            e.top = e.zg
            e.bottom = e.zd
            ents.append(e)
        return ents

    zs_data, zs_flag = get_zhong_shu_data(_pivots_to_entanglements(pivots_raw))
    zs_data2, zs_flag2 = get_zhong_shu_data(_pivots_to_entanglements(pivots_high_raw))

    inst = None
    try:
        inst = query_instrument_info(code)
    except Exception:
        inst = None
    name = (inst or {}).get("name") or ""

    dates = [_format_dt_ymdhm(dt) for dt in merged_df["datetime"].tolist()]
    chanlun_data = {
        "symbol": code,
        "code": code,
        "name": name,
        "period": period_front,
        "date": dates,
        "open": merged_df["open"].tolist(),
        "high": merged_df["high"].tolist(),
        "low": merged_df["low"].tolist(),
        "close": merged_df["close"].tolist(),
        "volume": merged_df["volume"].tolist() if "volume" in merged_df.columns else [],
        "amount": merged_df["amount"].tolist() if "amount" in merged_df.columns else [],
        "bidata": {"date": [str_from_timestamp(x) for x in bi_data["dt"]], "data": bi_data["data"]},
        "duandata": {"date": [str_from_timestamp(x) for x in duan_data["dt"]], "data": duan_data["data"]},
        "higherDuanData": {"date": [str_from_timestamp(x) for x in higher_duan_data["dt"]], "data": higher_duan_data["data"]},
        "higherHigherDuanData": {"date": [], "data": []},
        "zsdata": zs_data,
        "zsflag": zs_flag,
        "duan_zsdata": zs_data2,
        "duan_zsflag": zs_flag2,
        "higher_duan_zsdata": [],
        "higher_duan_zsflag": [],
        "signal_points": [],
        "updated_at": time.time(),
        "_source": "fullcalc",
        "_bar_time": bar_time_ts,
        "_bi_signal_list": bi_sig,
    }

    return ChanlunPayload(code=code, period_backend=period_backend, data=chanlun_data)

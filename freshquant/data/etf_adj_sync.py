from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import pymongo
from loguru import logger
from pymongo.errors import (
    AutoReconnect,
    ConnectionFailure,
    OperationFailure,
    ServerSelectionTimeoutError,
)

from freshquant.data.etf_adj import compute_etf_qfq_adj
from freshquant.db import DBQuantAxis

_CATEGORY_MEANING = {
    1: "除权除息",
    2: "送配股上市",
    3: "非流通股上市",
    4: "未知股本变动",
    5: "股本变化",
    6: "增发新股",
    7: "股份回购",
    8: "增发新股上市",
    9: "转配股上市",
    10: "可转债上市",
    11: "扩缩股",
    12: "非流通股缩股",
    13: "送认购权证",
    14: "送认沽权证",
}


@dataclass(frozen=True)
class TdxHqHost:
    name: str
    ip: str
    port: int


def _import_pytdx():
    try:
        from pytdx.config.hosts import hq_hosts  # type: ignore
        from pytdx.hq import TdxHq_API  # type: ignore

        return TdxHq_API, hq_hosts
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parents[2]
        vendored = repo_root / "sunflower" / "pytdx"
        if vendored.exists():
            sys.path.insert(0, str(vendored))

        from pytdx.config.hosts import hq_hosts  # type: ignore
        from pytdx.hq import TdxHq_API  # type: ignore

        return TdxHq_API, hq_hosts


def _pick_hq_host(timeout: float = 0.7) -> TdxHqHost:
    TdxHq_API, hq_hosts = _import_pytdx()
    api = TdxHq_API()
    for name, ip, port in hq_hosts:
        try:
            conn = api.connect(ip, port, time_out=timeout)
            if conn:
                api.disconnect()
                return TdxHqHost(name=name, ip=ip, port=int(port))
        except Exception:
            continue
    raise RuntimeError("No reachable TDX HQ host found in pytdx.config.hosts.hq_hosts")


def _market_from_sse_or_code(*, sse: str | None, code: str) -> int:
    if sse:
        s = str(sse).lower()
        if s == "sh":
            return 1
        if s == "sz":
            return 0
    return 1 if str(code).zfill(6)[0] in {"5", "6", "9"} else 0


def _ensure_indexes(db) -> None:
    for name in ["etf_xdxr", "etf_adj"]:
        coll = getattr(db, name)
        try:
            coll.create_index(
                [("code", pymongo.ASCENDING), ("date", pymongo.ASCENDING)], unique=True
            )
        except (ServerSelectionTimeoutError, ConnectionFailure, AutoReconnect) as e:
            raise RuntimeError(
                f"ensure index failed for {name}: db not reachable: {e}"
            ) from e
        except OperationFailure as e:
            msg = str(e)
            # Only do destructive recovery for duplicate-key / index conflict cases.
            # Anything else should surface to avoid accidental data loss.
            if (
                "E11000" not in msg
                and "duplicate key" not in msg
                and "IndexOptionsConflict" not in msg
            ):
                raise

            logger.warning(
                f"ensure index failed for {name} due to duplicates/conflict, drop and recreate: {e}"
            )
            db.drop_collection(name)
            coll = getattr(db, name)
            coll.create_index(
                [("code", pymongo.ASCENDING), ("date", pymongo.ASCENDING)], unique=True
            )


def _normalize_code_list(codes: Optional[Iterable[str]]) -> list[str]:
    if not codes:
        return []
    return [str(c).strip().zfill(6) for c in codes if str(c).strip()]


def sync_etf_xdxr_all(
    *,
    db=DBQuantAxis,
    codes: Optional[Iterable[str]] = None,
    timeout: float = 0.7,
) -> dict:
    """
    同步 ETF 除权/拆分事件到 quantaxis.etf_xdxr。

    - 数据源：TDX/pytdx get_xdxr_info
    - 存储：按 code 全量覆盖（delete_many + insert_many）
    """
    _ensure_indexes(db)

    code_list = _normalize_code_list(codes)
    etf_map = {}
    if not code_list:
        cursor = db.etf_list.find({}, {"_id": 0, "code": 1, "sse": 1})
        for doc in cursor:
            c = str(doc.get("code", "")).zfill(6)
            if c and c.isdigit():
                etf_map[c] = doc.get("sse")
        code_list = sorted(etf_map.keys())
    else:
        for c in code_list:
            etf_map[c] = None

    TdxHq_API, _ = _import_pytdx()
    host = _pick_hq_host(timeout=timeout)
    logger.info(f"TDX HQ host selected: {host.name} {host.ip}:{host.port}")

    coll = db.etf_xdxr
    ok = 0
    failed = 0
    empty = 0

    api = TdxHq_API()
    with api.connect(host.ip, host.port, time_out=timeout):
        for i, code in enumerate(code_list, 1):
            market = _market_from_sse_or_code(sse=etf_map.get(code), code=code)
            try:
                raw = api.get_xdxr_info(market, code)
                df = api.to_df(raw) if raw else pd.DataFrame()
                if df is None or len(df) == 0:
                    coll.delete_many({"code": code})
                    empty += 1
                    continue

                for col in ["year", "month", "day", "category"]:
                    if col not in df.columns:
                        raise ValueError(f"TDX xdxr missing column: {col}")

                df["date"] = pd.to_datetime(
                    df[["year", "month", "day"]], errors="coerce"
                ).dt.strftime("%Y-%m-%d")
                df = df.drop(
                    columns=[c for c in ["year", "month", "day"] if c in df.columns]
                )
                df["code"] = code
                df["category_meaning"] = df["category"].map(
                    lambda x: _CATEGORY_MEANING.get(int(x))
                )
                if "name" in df.columns:
                    df["category_meaning"] = df["category_meaning"].fillna(df["name"])
                df["category_meaning"] = df["category_meaning"].fillna(
                    df["category"].astype(str)
                )
                df = df.rename(
                    columns={
                        "panhouliutong": "liquidity_after",
                        "panqianliutong": "liquidity_before",
                        "houzongguben": "shares_after",
                        "qianzongguben": "shares_before",
                    }
                )

                df = df.where(pd.notnull(df), None)
                docs = df.to_dict(orient="records")

                coll.delete_many({"code": code})
                if docs:
                    coll.insert_many(docs, ordered=False)
                ok += 1
            except Exception as e:
                failed += 1
                logger.warning(f"sync etf_xdxr failed: {code} market={market} err={e}")
                continue

            if i % 200 == 0:
                logger.info(
                    f"etf_xdxr progress: {i}/{len(code_list)} ok={ok} empty={empty} failed={failed}"
                )

    return {"total": len(code_list), "ok": ok, "empty": empty, "failed": failed}


def sync_etf_adj_all(
    *,
    db=DBQuantAxis,
    codes: Optional[Iterable[str]] = None,
) -> dict:
    """
    生成并同步 ETF 前复权(qfq)因子到 quantaxis.etf_adj。

    - 数据源：quantaxis.index_day（bfq） + quantaxis.etf_xdxr
    - 存储：按 code 全量覆盖（delete_many + insert_many）
    """
    _ensure_indexes(db)

    code_list = _normalize_code_list(codes)
    if not code_list:
        cursor = db.etf_list.find({}, {"_id": 0, "code": 1})
        code_list = sorted(
            {
                str(doc.get("code", "")).zfill(6)
                for doc in cursor
                if str(doc.get("code", "")).isdigit()
            }
        )

    coll_adj = db.etf_adj
    coll_day = db.index_day
    coll_xdxr = db.etf_xdxr

    ok = 0
    skipped = 0
    failed = 0

    for i, code in enumerate(code_list, 1):
        try:
            day_cursor = coll_day.find(
                {"code": code},
                {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1},
            ).sort("date", pymongo.ASCENDING)
            day = pd.DataFrame(list(day_cursor))
            if day is None or len(day) == 0:
                skipped += 1
                continue

            xdxr_cursor = coll_xdxr.find(
                {"code": code},
                {
                    "_id": 0,
                    "date": 1,
                    "category": 1,
                    "fenhong": 1,
                    "peigu": 1,
                    "peigujia": 1,
                    "songzhuangu": 1,
                    "suogu": 1,
                },
            )
            xdxr = pd.DataFrame(list(xdxr_cursor))
            adj = compute_etf_qfq_adj(day, xdxr if len(xdxr) > 0 else None)
            if adj is None or len(adj) == 0:
                skipped += 1
                continue

            out = adj.assign(code=code).loc[:, ["date", "code", "adj"]]
            out = out.where(pd.notnull(out), None)
            docs = out.to_dict(orient="records")
            coll_adj.delete_many({"code": code})
            if docs:
                coll_adj.insert_many(docs, ordered=False)
            ok += 1
        except Exception as e:
            failed += 1
            logger.warning(f"sync etf_adj failed: {code} err={e}")
            continue

        if i % 200 == 0:
            logger.info(
                f"etf_adj progress: {i}/{len(code_list)} ok={ok} skipped={skipped} failed={failed}"
            )

    return {"total": len(code_list), "ok": ok, "skipped": skipped, "failed": failed}

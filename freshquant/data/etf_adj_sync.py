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


def _pick_hq_host(
    timeout: float = 0.7,
    *,
    exclude_hosts: Optional[set[tuple[str, int]]] = None,
) -> TdxHqHost:
    TdxHq_API, hq_hosts = _import_pytdx()
    api = TdxHq_API()
    for name, ip, port in hq_hosts:
        if exclude_hosts and (ip, int(port)) in exclude_hosts:
            continue
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


def _fetch_xdxr_df(api, *, market: int, code: str) -> pd.DataFrame:
    raw = api.get_xdxr_info(market, code)
    df = api.to_df(raw) if raw else pd.DataFrame()
    if df is None:
        return pd.DataFrame()
    return df


def _fetch_xdxr_df_with_fresh_connection(
    tdx_api_cls,
    *,
    host: TdxHqHost,
    timeout: float,
    market: int,
    code: str,
) -> pd.DataFrame:
    api = tdx_api_cls()
    with api.connect(host.ip, host.port, time_out=timeout):
        return _fetch_xdxr_df(api, market=market, code=code)


def _normalize_xdxr_df_to_docs(df: pd.DataFrame, *, code: str) -> list[dict]:
    for col in ["year", "month", "day", "category"]:
        if col not in df.columns:
            raise ValueError(f"TDX xdxr missing column: {col}")

    normalized = df.copy()
    normalized["date"] = pd.to_datetime(
        normalized[["year", "month", "day"]], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    normalized = normalized.drop(
        columns=[c for c in ["year", "month", "day"] if c in normalized.columns]
    )
    normalized["code"] = code
    normalized["category_meaning"] = normalized["category"].map(
        lambda x: _CATEGORY_MEANING.get(int(x))
    )
    if "name" in normalized.columns:
        normalized["category_meaning"] = normalized["category_meaning"].fillna(
            normalized["name"]
        )
    normalized["category_meaning"] = normalized["category_meaning"].fillna(
        normalized["category"].astype(str)
    )
    normalized = normalized.rename(
        columns={
            "panhouliutong": "liquidity_after",
            "panqianliutong": "liquidity_before",
            "houzongguben": "shares_after",
            "qianzongguben": "shares_before",
        }
    )
    normalized = normalized.where(pd.notnull(normalized), None)
    return normalized.to_dict(orient="records")


def _normalize_xdxr_signature_value(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return str(value)


def _build_xdxr_signature_set(
    documents: Iterable[dict], *, cutoff_date: str, as_of_date: str
) -> set[tuple]:
    signatures = set()
    for document in documents or []:
        trade_date = str(document.get("date") or "")
        if not trade_date or trade_date < cutoff_date or trade_date > as_of_date:
            continue
        signatures.add(
            (
                trade_date,
                _normalize_xdxr_signature_value(document.get("category")),
                _normalize_xdxr_signature_value(document.get("fenhong")),
                _normalize_xdxr_signature_value(document.get("peigu")),
                _normalize_xdxr_signature_value(document.get("peigujia")),
                _normalize_xdxr_signature_value(document.get("songzhuangu")),
                _normalize_xdxr_signature_value(document.get("suogu")),
            )
        )
    return signatures


def sync_etf_xdxr_all(
    *,
    db=DBQuantAxis,
    codes: Optional[Iterable[str]] = None,
    timeout: float = 0.7,
    preserve_on_empty: bool = True,
    reconnect_every: int = 200,
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
    current_host = _pick_hq_host(timeout=timeout)
    logger.info(
        f"TDX HQ host selected: {current_host.name} {current_host.ip}:{current_host.port}"
    )

    coll = db.etf_xdxr
    ok = 0
    failed = 0
    empty = 0
    preserved = 0
    retried_empty = 0
    recovered_after_retry = 0
    retry_failed = 0
    empty_codes: list[str] = []
    preserved_codes: list[str] = []
    reconnect_every = max(int(reconnect_every), 1)

    for batch_start in range(0, len(code_list), reconnect_every):
        batch_codes = code_list[batch_start : batch_start + reconnect_every]
        if batch_start > 0:
            try:
                current_host = _pick_hq_host(
                    timeout=timeout,
                    exclude_hosts={(current_host.ip, current_host.port)},
                )
            except RuntimeError:
                pass
        api = TdxHq_API()
        with api.connect(current_host.ip, current_host.port, time_out=timeout):
            for batch_offset, code in enumerate(batch_codes, 1):
                i = batch_start + batch_offset
                market = _market_from_sse_or_code(sse=etf_map.get(code), code=code)
                try:
                    df = _fetch_xdxr_df(api, market=market, code=code)
                    if df is None or len(df) == 0:
                        retried_empty += 1
                        existing_docs = list(
                            coll.find(
                                {"code": code},
                                {"_id": 0, "code": 1, "date": 1},
                            ).sort("date", -1)
                        )
                        retry_df = pd.DataFrame()
                        retry_host = current_host
                        try:
                            retry_host = _pick_hq_host(
                                timeout=timeout,
                                exclude_hosts={(current_host.ip, current_host.port)},
                            )
                        except RuntimeError:
                            retry_host = current_host
                        try:
                            retry_df = _fetch_xdxr_df_with_fresh_connection(
                                TdxHq_API,
                                host=retry_host,
                                timeout=timeout,
                                market=market,
                                code=code,
                            )
                        except Exception as retry_error:
                            retry_failed += 1
                            logger.warning(
                                f"sync etf_xdxr retry failed: {code} market={market} "
                                f"host={retry_host.name} {retry_host.ip}:{retry_host.port} err={retry_error}"
                            )

                        if retry_df is not None and len(retry_df) > 0:
                            recovered_after_retry += 1
                            if existing_docs:
                                logger.warning(
                                    "sync etf_xdxr recovered after empty result via fresh connection: "
                                    f"{code} market={market} retry_host={retry_host.name} "
                                    f"latest_existing={existing_docs[0].get('date')}"
                                )
                            df = retry_df
                        elif existing_docs and preserve_on_empty:
                            preserved += 1
                            preserved_codes.append(code)
                            logger.warning(
                                "sync etf_xdxr empty after retry, preserving existing docs: "
                                f"{code} market={market} latest_existing={existing_docs[0].get('date')}"
                            )
                            continue
                        else:
                            coll.delete_many({"code": code})
                            empty += 1
                            empty_codes.append(code)
                            continue

                    docs = _normalize_xdxr_df_to_docs(df, code=code)

                    coll.delete_many({"code": code})
                    if docs:
                        coll.insert_many(docs, ordered=False)
                    ok += 1
                except Exception as e:
                    failed += 1
                    logger.warning(
                        f"sync etf_xdxr failed: {code} market={market} err={e}"
                    )
                    continue

                if i % 200 == 0:
                    logger.info(
                        "etf_xdxr progress: "
                        f"{i}/{len(code_list)} ok={ok} empty={empty} preserved={preserved} "
                        f"failed={failed} retried_empty={retried_empty} "
                        f"recovered_after_retry={recovered_after_retry} retry_failed={retry_failed}"
                    )

    return {
        "total": len(code_list),
        "ok": ok,
        "empty": empty,
        "preserved": preserved,
        "failed": failed,
        "retried_empty": retried_empty,
        "recovered_after_retry": recovered_after_retry,
        "retry_failed": retry_failed,
        "empty_codes": empty_codes,
        "preserved_codes": preserved_codes,
    }


def audit_recent_etf_xdxr_coverage(
    *,
    db=DBQuantAxis,
    codes: Optional[Iterable[str]] = None,
    timeout: float = 0.7,
    reconnect_every: int = 200,
    recent_days: int = 120,
    as_of_date: str | None = None,
) -> dict:
    """
    校验近期 ETF xdxr 事件是否已经从 TDX 同步到 quantaxis.etf_xdxr。

    只校验近窗口内源侧存在的事件是否落库，避免历史缺口导致的误报。
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

    window_days = max(int(recent_days), 1)
    as_of_ts = (
        pd.Timestamp(as_of_date).normalize()
        if as_of_date
        else pd.Timestamp.utcnow().normalize()
    )
    as_of_date_str = as_of_ts.strftime("%Y-%m-%d")
    cutoff_date = (as_of_ts - pd.Timedelta(days=window_days)).strftime("%Y-%m-%d")

    TdxHq_API, _ = _import_pytdx()
    current_host = _pick_hq_host(timeout=timeout)
    logger.info(
        f"TDX HQ host selected for ETF xdxr audit: {current_host.name} {current_host.ip}:{current_host.port}"
    )

    coll = db.etf_xdxr
    reconnect_every = max(int(reconnect_every), 1)
    checked = 0
    matching = 0
    mismatched = 0
    source_empty = 0
    failed = 0
    mismatch_codes: list[str] = []

    for batch_start in range(0, len(code_list), reconnect_every):
        batch_codes = code_list[batch_start : batch_start + reconnect_every]
        if batch_start > 0:
            try:
                current_host = _pick_hq_host(
                    timeout=timeout,
                    exclude_hosts={(current_host.ip, current_host.port)},
                )
            except RuntimeError:
                pass
        api = TdxHq_API()
        with api.connect(current_host.ip, current_host.port, time_out=timeout):
            for batch_offset, code in enumerate(batch_codes, 1):
                i = batch_start + batch_offset
                market = _market_from_sse_or_code(sse=etf_map.get(code), code=code)
                try:
                    df = _fetch_xdxr_df(api, market=market, code=code)
                    if df is None or len(df) == 0:
                        retry_host = current_host
                        try:
                            retry_host = _pick_hq_host(
                                timeout=timeout,
                                exclude_hosts={(current_host.ip, current_host.port)},
                            )
                        except RuntimeError:
                            retry_host = current_host
                        df = _fetch_xdxr_df_with_fresh_connection(
                            TdxHq_API,
                            host=retry_host,
                            timeout=timeout,
                            market=market,
                            code=code,
                        )

                    if df is None or len(df) == 0:
                        source_empty += 1
                        continue

                    source_docs = _normalize_xdxr_df_to_docs(df, code=code)
                    source_signatures = _build_xdxr_signature_set(
                        source_docs,
                        cutoff_date=cutoff_date,
                        as_of_date=as_of_date_str,
                    )
                    if not source_signatures:
                        source_empty += 1
                        continue

                    checked += 1
                    db_docs = list(
                        coll.find(
                            {
                                "code": code,
                                "date": {"$gte": cutoff_date, "$lte": as_of_date_str},
                            },
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
                    )
                    db_signatures = _build_xdxr_signature_set(
                        db_docs,
                        cutoff_date=cutoff_date,
                        as_of_date=as_of_date_str,
                    )
                    if source_signatures.issubset(db_signatures):
                        matching += 1
                    else:
                        mismatched += 1
                        mismatch_codes.append(code)
                        missing = sorted(source_signatures - db_signatures)
                        logger.warning(
                            "ETF xdxr recent audit mismatch: "
                            f"{code} missing_recent_signatures={missing[:3]} cutoff_date={cutoff_date}"
                        )
                except Exception as e:
                    failed += 1
                    logger.warning(
                        f"audit etf_xdxr failed: {code} market={market} err={e}"
                    )
                    continue

                if i % 200 == 0:
                    logger.info(
                        "etf_xdxr audit progress: "
                        f"{i}/{len(code_list)} checked={checked} matching={matching} "
                        f"mismatched={mismatched} source_empty={source_empty} failed={failed}"
                    )

    return {
        "total": len(code_list),
        "checked": checked,
        "matching": matching,
        "mismatched": mismatched,
        "source_empty": source_empty,
        "failed": failed,
        "cutoff_date": cutoff_date,
        "mismatch_codes": mismatch_codes,
    }


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

"""Market data assets using Dagster's asset-based approach.

This module replaces the traditional op/job pattern with assets that have clear dependencies.
Each data type (stock, future, etf, bond, index) has its own set of assets with proper dependencies.
"""

import os
import uuid
from pathlib import Path

import pendulum
from blinker import signal
from dagster import AssetExecutionContext, asset
from QUANTAXIS.QASU.main import (
    QA_SU_save_bond_day,
    QA_SU_save_bond_list,
    QA_SU_save_bond_min,
    QA_SU_save_etf_day,
    QA_SU_save_etf_list,
    QA_SU_save_etf_min,
    QA_SU_save_future_day_all,
    QA_SU_save_future_list,
    QA_SU_save_future_min_all,
    QA_SU_save_index_day,
    QA_SU_save_index_list,
    QA_SU_save_index_min,
    QA_SU_save_stock_day,
    QA_SU_save_stock_list,
    QA_SU_save_stock_min,
    QA_SU_save_stock_xdxr,
)
from QUANTAXIS.QAUtil import QA_util_to_json_from_pandas

from freshquant.data.etf_adj_sync import (
    audit_recent_etf_xdxr_coverage,
    sync_etf_adj_all,
    sync_etf_xdxr_all,
)
from freshquant.db import DBQuantAxis

from ..postclose_markers import (
    resolve_latest_completed_trade_date,
    upsert_postclose_marker,
)
from .postclose_ready import refresh_quality_stock_universe_snapshot

market_data_alert = signal("market_data_alert")
LOCAL_TDX_INFOHARBOR_SOURCE = "tdx_infoharbor"
STOCK_BLOCK_SOURCES = ("tdx", "tushare")
LOCAL_TDX_ROOT_CANDIDATES = (
    "/run/host-tdx",
    "/mnt/d/new_tdx",
    "/run/desktop/mnt/host/d/new_tdx",
    "/host_mnt/d/new_tdx",
    r"D:\new_tdx",
    r"D:\tdx_biduan",
    r"D:\tdx",
    r"C:\tdx",
    r"C:\new_tdx",
    r"D:\通达信",
    r"C:\通达信",
)


def _normalize_stock_block_docs(documents, source: str):
    normalized = []
    for item in documents or []:
        if not isinstance(item, dict):
            continue
        doc = dict(item)
        doc.setdefault("source", source)
        normalized.append(doc)
    return normalized


def _resolve_local_tdx_root():
    candidates = []
    for env_name in ("FRESHQUANT_TDX_ROOT", "TDX_HOME", "TDX_PATH"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    candidates.extend(LOCAL_TDX_ROOT_CANDIDATES)

    for candidate in candidates:
        root = Path(candidate).expanduser()
        if (root / "T0002" / "hq_cache").exists():
            return root
    return None


def _iter_tdx_infoharbor_codes(line: str):
    for raw_item in str(line or "").split(","):
        item = raw_item.strip()
        if "#" not in item:
            continue
        market, code = item.split("#", 1)
        digits = "".join(ch for ch in str(code) if ch.isdigit())
        if market not in {"0", "1"} or len(digits) != 6:
            continue
        yield digits


def _parse_tdx_infoharbor_block_text(
    text: str,
    *,
    source: str = LOCAL_TDX_INFOHARBOR_SOURCE,
):
    documents = []
    current_block_name = None
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            current_block_name = None
            header = line[1:]
            if "_" not in header:
                continue
            current_block_name = header.split("_", 1)[1].split(",", 1)[0].strip()
            continue
        if not current_block_name:
            continue
        for code in _iter_tdx_infoharbor_codes(line):
            documents.append(
                {
                    "code": code,
                    "blockname": current_block_name,
                    "source": source,
                }
            )
    return documents


def _load_local_tdx_infoharbor_docs(log):
    tdx_root = _resolve_local_tdx_root()
    if not tdx_root:
        if log:
            log.warning("local tdx root not found; skip infoharbor fallback")
        return []

    infoharbor_path = tdx_root / "T0002" / "hq_cache" / "infoharbor_block.dat"
    if not infoharbor_path.exists():
        if log:
            log.warning("infoharbor block file missing: %s", infoharbor_path)
        return []

    try:
        text = infoharbor_path.read_bytes().decode("gbk", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        if log:
            log.warning("read infoharbor block file failed: %s", exc)
        return []

    documents = _parse_tdx_infoharbor_block_text(text)
    if log and documents:
        log.info(
            "loaded local infoharbor block docs=%s path=%s",
            len(documents),
            infoharbor_path,
        )
    return documents


def _load_stock_block_docs_by_source(
    *,
    fetch_block_dataframe,
    to_json,
    log,
    sources=STOCK_BLOCK_SOURCES,
):
    docs_by_source = {}
    local_docs = _load_local_tdx_infoharbor_docs(log)
    if local_docs:
        docs_by_source[LOCAL_TDX_INFOHARBOR_SOURCE] = local_docs

    for source in sources:
        try:
            dataframe = fetch_block_dataframe(source)
        except Exception as exc:  # noqa: BLE001
            if log:
                log.warning("QA_fetch_get_stock_block(%s) failed: %s", source, exc)
            continue

        if dataframe is None or getattr(dataframe, "empty", False):
            if log:
                log.warning("QA_fetch_get_stock_block(%s) returned empty", source)
            continue

        try:
            documents = to_json(dataframe)
        except Exception as exc:  # noqa: BLE001
            if log:
                log.warning(
                    "QA_fetch_get_stock_block(%s) to json failed: %s", source, exc
                )
            continue

        normalized = _normalize_stock_block_docs(documents, source)
        if not normalized:
            if log:
                log.warning(
                    "QA_fetch_get_stock_block(%s) produced empty json list", source
                )
            continue

        docs_by_source[source] = normalized

    return docs_by_source


def _stock_block_staging_collection_name(collection_name: str) -> str:
    return f"{collection_name}__refresh__{uuid.uuid4().hex}"


def _insert_stock_block_documents(
    *,
    collection,
    documents,
    batch_size: int,
    log,
    source_label: str,
):
    inserted = 0
    for start in range(0, len(documents), batch_size):
        batch = documents[start : start + batch_size]
        if not batch:
            continue
        try:
            collection.insert_many(batch, ordered=False)
            inserted += len(batch)
        except Exception as exc:  # noqa: BLE001
            if log:
                log.warning(
                    "stock_block staging insert source=%s batch=%s failed: %s",
                    source_label,
                    len(batch),
                    exc,
                )
            return None
    return inserted


def _refresh_stock_block_collection(
    *,
    collection,
    fetch_block_dataframe,
    to_json,
    log,
    sources=STOCK_BLOCK_SOURCES,
    batch_size: int = 5000,
):
    docs_by_source = _load_stock_block_docs_by_source(
        fetch_block_dataframe=fetch_block_dataframe,
        to_json=to_json,
        log=log,
        sources=sources,
    )
    if not docs_by_source:
        if log:
            log.warning(
                "stock_block refresh skipped: all sources empty/failed; keeping existing collection unchanged"
            )
        return {"refreshed_sources": [], "total_docs": 0}

    refreshed_source_names = list(docs_by_source)
    preserved_query = {"source": {"$nin": refreshed_source_names}}
    preserved_docs = list(collection.find(preserved_query))
    staging_name = _stock_block_staging_collection_name(collection.name)
    collection.database.drop_collection(staging_name)
    staging_collection = collection.database[staging_name]
    staging_collection.create_index("code")

    preserved_inserted = _insert_stock_block_documents(
        collection=staging_collection,
        documents=preserved_docs,
        batch_size=batch_size,
        log=log,
        source_label="preserved",
    )
    if preserved_inserted is None:
        collection.database.drop_collection(staging_name)
        if log:
            log.warning(
                "stock_block refresh aborted: preserved docs staging failed; keeping existing collection unchanged"
            )
        return {"refreshed_sources": [], "total_docs": 0}

    refreshed_sources = []
    total_docs = 0
    for source, documents in docs_by_source.items():
        inserted = _insert_stock_block_documents(
            collection=staging_collection,
            documents=documents,
            batch_size=batch_size,
            log=log,
            source_label=source,
        )
        if inserted is None:
            collection.database.drop_collection(staging_name)
            if log:
                log.warning(
                    "stock_block refresh aborted: source=%s staging failed; keeping existing collection unchanged",
                    source,
                )
            return {"refreshed_sources": [], "total_docs": 0}
        refreshed_sources.append(source)
        total_docs += inserted
        if log:
            log.info("stock_block source=%s refreshed docs=%s", source, inserted)

    try:
        staging_collection.rename(collection.name, dropTarget=True)
    except Exception as exc:  # noqa: BLE001
        collection.database.drop_collection(staging_name)
        if log:
            log.warning(
                "stock_block rename staging=%s -> %s failed: %s; keeping existing collection unchanged",
                staging_name,
                collection.name,
                exc,
            )
        return {"refreshed_sources": [], "total_docs": 0}

    if log:
        log.info(
            "stock_block refresh done: sources=%s total_docs=%s preserved_docs=%s",
            refreshed_sources,
            total_docs,
            len(preserved_docs),
        )
    return {"refreshed_sources": refreshed_sources, "total_docs": total_docs}


def _save_stock_block_safe(context) -> dict:
    from QUANTAXIS.QAFetch import QA_fetch_get_stock_block

    return _refresh_stock_block_collection(
        collection=DBQuantAxis["stock_block"],
        fetch_block_dataframe=QA_fetch_get_stock_block,
        to_json=QA_util_to_json_from_pandas,
        log=context.log,
    )


# Stock Assets
@asset(group_name="stock_data")
def stock_list(context: AssetExecutionContext) -> str:
    """Download and save stock list data."""
    context.log.info("Saving stock list")
    QA_SU_save_stock_list("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "股票列表数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[stock_list], group_name="stock_data")
def stock_block(context: AssetExecutionContext, stock_list: str) -> str:
    """Download and save stock block data. Depends on stock_list."""
    context.log.info(
        f"Saving stock block data, triggered after stock_list at {stock_list}"
    )
    result = _save_stock_block_safe(context)
    context.log.info("stock block safe refresh result=%s", result)
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "股票板块数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[stock_list], group_name="stock_data")
def stock_day(context: AssetExecutionContext, stock_list: str) -> str:
    """Download and save stock daily data. Depends on stock_list."""
    context.log.info(
        f"Saving stock daily data, triggered after stock_list at {stock_list}"
    )
    QA_SU_save_stock_day("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "股票日线数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[stock_list], group_name="stock_data")
def stock_min(context: AssetExecutionContext, stock_list: str) -> str:
    """Download and save stock minute data. Depends on stock_list."""
    context.log.info(
        f"Saving stock minute data, triggered after stock_list at {stock_list}"
    )
    QA_SU_save_stock_min("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "股票分钟数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[stock_day], group_name="stock_data")
def stock_xdxr(context: AssetExecutionContext, stock_day: str) -> str:
    """Download and save stock dividend/adjustment data. Depends on stock_day."""
    context.log.info(
        f"Saving stock dividend data, triggered after stock_day at {stock_day}"
    )
    QA_SU_save_stock_xdxr("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "股票除权除息数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(group_name="stock_data")
def stock_postclose_ready_asset(
    context: AssetExecutionContext,
    refresh_quality_stock_universe_snapshot: dict,
) -> dict:
    trade_date = (
        str(refresh_quality_stock_universe_snapshot.get("trade_date") or "")
        or resolve_latest_completed_trade_date()
    )
    payload = {
        "count": int(refresh_quality_stock_universe_snapshot.get("count") or 0),
        "source_version": str(
            refresh_quality_stock_universe_snapshot.get("source_version") or ""
        ).strip(),
    }
    upsert_postclose_marker(
        "stock_postclose_ready",
        trade_date,
        run_id=getattr(context, "run_id", None),
        payload=payload,
    )
    return {
        "pipeline_key": "stock_postclose_ready",
        "trade_date": trade_date,
        "payload": payload,
    }


# Future Assets
@asset(group_name="future_data")
def future_list(context: AssetExecutionContext) -> str:
    """Download and save future list data."""
    context.log.info("Saving future list")
    QA_SU_save_future_list("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "期货列表数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[future_list], group_name="future_data")
def future_day(context: AssetExecutionContext, future_list: str) -> str:
    """Download and save future daily data. Depends on future_list."""
    context.log.info(
        f"Saving future daily data, triggered after future_list at {future_list}"
    )
    QA_SU_save_future_day_all("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "期货日线数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[future_list], group_name="future_data")
def future_min(context: AssetExecutionContext, future_list: str) -> str:
    """Download and save future minute data. Depends on future_list."""
    context.log.info(
        f"Saving future minute data, triggered after future_list at {future_list}"
    )
    QA_SU_save_future_min_all("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "期货分钟数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


# ETF Assets
@asset(group_name="etf_data")
def etf_list(context: AssetExecutionContext) -> str:
    """Download and save ETF list data."""
    context.log.info("Saving ETF list")
    QA_SU_save_etf_list("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "ETF列表数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[etf_list], group_name="etf_data")
def etf_day(context: AssetExecutionContext, etf_list: str) -> str:
    """Download and save ETF daily data. Depends on etf_list."""
    context.log.info(f"Saving ETF daily data, triggered after etf_list at {etf_list}")
    QA_SU_save_etf_day("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "ETF日线数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[etf_list], group_name="etf_data")
def etf_min(context: AssetExecutionContext, etf_list: str) -> str:
    """Download and save ETF minute data. Depends on etf_list."""
    context.log.info(f"Saving ETF minute data, triggered after etf_list at {etf_list}")
    QA_SU_save_etf_min("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "ETF分钟数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[etf_list], group_name="etf_data")
def etf_xdxr(context: AssetExecutionContext, etf_list: str) -> str:
    """Download and save ETF xdxr(adjustment events) data. Depends on etf_list."""
    context.log.info(f"Saving ETF xdxr data, triggered after etf_list at {etf_list}")
    stats = sync_etf_xdxr_all()
    context.log.info(f"ETF xdxr sync stats: {stats}")
    suspicious_codes = list(
        dict.fromkeys(
            [
                *list(stats.get("empty_codes") or []),
                *list(stats.get("preserved_codes") or []),
            ]
        )
    )
    if suspicious_codes:
        audit_stats = audit_recent_etf_xdxr_coverage(codes=suspicious_codes)
        context.log.info(f"ETF xdxr recent audit stats: {audit_stats}")
        if audit_stats.get("mismatched") or audit_stats.get("failed"):
            mismatch_codes = audit_stats.get("mismatch_codes") or []
            mismatch_suffix = (
                f" mismatch_codes={mismatch_codes[:10]}" if mismatch_codes else ""
            )
            raise RuntimeError(
                "ETF xdxr recent audit failed: "
                f"mismatched={audit_stats.get('mismatched', 0)} "
                f"failed={audit_stats.get('failed', 0)}"
                f"{mismatch_suffix}"
            )
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "ETF 除权除息/扩缩股(xdxr) 数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[etf_day, etf_xdxr], group_name="etf_data")
def etf_adj(context: AssetExecutionContext, etf_day: str, etf_xdxr: str) -> str:
    """Compute and save ETF qfq adjustment factors. Depends on etf_day + etf_xdxr."""
    context.log.info(
        f"Saving ETF adj(qfq) data, triggered after etf_day at {etf_day} and etf_xdxr at {etf_xdxr}"
    )
    stats = sync_etf_adj_all()
    context.log.info(f"ETF adj sync stats: {stats}")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "ETF 前复权因子(etf_adj) 数据已生成完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(group_name="etf_data")
def etf_postclose_ready_asset(context: AssetExecutionContext, etf_adj: str) -> dict:
    trade_date = resolve_latest_completed_trade_date()
    payload: dict[str, str] = {}
    upsert_postclose_marker(
        "etf_postclose_ready",
        trade_date,
        run_id=getattr(context, "run_id", None),
        payload=payload,
    )
    return {
        "pipeline_key": "etf_postclose_ready",
        "trade_date": trade_date,
        "payload": payload,
    }


# Bond Assets
@asset(group_name="bond_data")
def bond_list(context: AssetExecutionContext) -> str:
    """Download and save bond list data."""
    context.log.info("Saving bond list")
    QA_SU_save_bond_list("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "债券列表数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[bond_list], group_name="bond_data")
def bond_day(context: AssetExecutionContext, bond_list: str) -> str:
    """Download and save bond daily data. Depends on bond_list."""
    context.log.info(
        f"Saving bond daily data, triggered after bond_list at {bond_list}"
    )
    QA_SU_save_bond_day("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "债券日线数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[bond_list], group_name="bond_data")
def bond_min(context: AssetExecutionContext, bond_list: str) -> str:
    """Download and save bond minute data. Depends on bond_list."""
    context.log.info(
        f"Saving bond minute data, triggered after bond_list at {bond_list}"
    )
    QA_SU_save_bond_min("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "债券分钟数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


# Index Assets
@asset(group_name="index_data")
def index_list(context: AssetExecutionContext) -> str:
    """Download and save index list data."""
    context.log.info("Saving index list")
    QA_SU_save_index_list("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "指数列表数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[index_list], group_name="index_data")
def index_day(context: AssetExecutionContext, index_list: str) -> str:
    """Download and save index daily data. Depends on index_list."""
    context.log.info(
        f"Saving index daily data, triggered after index_list at {index_list}"
    )
    QA_SU_save_index_day("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "指数日线数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(deps=[index_list], group_name="index_data")
def index_min(context: AssetExecutionContext, index_list: str) -> str:
    """Download and save index minute data. Depends on index_list."""
    context.log.info(
        f"Saving index minute data, triggered after index_list at {index_list}"
    )
    QA_SU_save_index_min("tdx")
    market_data_alert.send(
        "dagster-asset",
        payload={
            "title": "事件通知-数据下载完成",
            "content": "指数分钟数据已下载完成。",
        },
    )
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")

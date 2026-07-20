"""行情落库后的数据新鲜度校验。

QUANTAXIS 的 ``QA_SU_save_stock_day`` / ``QA_SU_save_stock_min`` 会把逐票抓取
异常吞掉(只打印 ERROR CODE 列表), 上游 TDX 服务器故障时整个市场一条都
没写入, Dagster run 仍然显示 SUCCESS。这里在资产落库后直接对 Mongo 断言
"最新已收盘交易日已经覆盖", 不新鲜就抛错让 asset 失败。

校验策略:
- 样本股票取几乎不会停牌的大盘蓝筹, 要求全部样本同时落后才判定为
  系统性停更, 单只股票停牌不会误报;
- ``stock_day`` 另做当日文档数下限校验, 用于捕获"只写入了少量股票"的
  部分故障。
"""

from __future__ import annotations

from typing import Mapping, Sequence

# 大盘蓝筹样本: 平安银行 / 浦发银行 / 贵州茅台
FRESHNESS_SAMPLE_CODES: tuple[str, ...] = ("000001", "600000", "600519")
# 全市场约 5200 只, 正常交易日 stock_day 当日文档数约 5190(停牌股无 bar)
STOCK_DAY_MIN_DOCS = 3000


def resolve_expected_trade_date() -> str:
    """最近一个已收盘的交易日(15:05 后含当日), 格式 YYYY-MM-DD。"""
    from fqdagster.defs.postclose_markers import resolve_latest_completed_trade_date

    return resolve_latest_completed_trade_date()


def _default_collection(name: str):
    from freshquant.db import DBQuantAxis

    return DBQuantAxis[name]


def _sample_latest_dates(
    collection,
    sample_codes: Sequence[str],
    *,
    extra_filter: Mapping[str, object] | None = None,
    sort_field: str = "date_stamp",
    date_field: str = "date",
) -> dict[str, str]:
    latest: dict[str, str] = {}
    for code in sample_codes:
        query: dict[str, object] = {"code": str(code)}
        if extra_filter:
            query.update(extra_filter)
        doc = collection.find_one(query, sort=[(sort_field, -1)]) or {}
        latest[str(code)] = str(doc.get(date_field) or "")[:10]
    return latest


def assert_stock_day_fresh(
    collection=None,
    *,
    expected_trade_date: str | None = None,
    sample_codes: Sequence[str] = FRESHNESS_SAMPLE_CODES,
    min_docs: int = STOCK_DAY_MIN_DOCS,
) -> dict:
    """校验 quantaxis.stock_day 已覆盖最新交易日, 失败抛 RuntimeError。"""
    coll = collection if collection is not None else _default_collection("stock_day")
    expected = expected_trade_date or resolve_expected_trade_date()

    sample_latest = _sample_latest_dates(coll, sample_codes)
    if sample_latest and all(latest < expected for latest in sample_latest.values()):
        raise RuntimeError(
            "stock_day is stale: expected trade date "
            f"{expected}, sample latest={sample_latest}; "
            "upstream TDX daily fetch likely failed for the whole market"
        )

    day_docs = int(coll.count_documents({"date": expected}))
    if day_docs < min_docs:
        raise RuntimeError(
            f"stock_day incomplete for {expected}: only {day_docs} docs "
            f"(expected >= {min_docs}); upstream TDX daily fetch likely "
            "failed for most of the market"
        )

    return {
        "expected_trade_date": expected,
        "day_docs": day_docs,
        "sample_latest": sample_latest,
    }


def assert_stock_min_fresh(
    collection=None,
    *,
    expected_trade_date: str | None = None,
    sample_codes: Sequence[str] = FRESHNESS_SAMPLE_CODES,
    frequence: str = "1min",
) -> dict:
    """校验 quantaxis.stock_min 已覆盖最新交易日, 失败抛 RuntimeError。"""
    coll = collection if collection is not None else _default_collection("stock_min")
    expected = expected_trade_date or resolve_expected_trade_date()

    sample_latest = _sample_latest_dates(
        coll,
        sample_codes,
        extra_filter={"type": frequence},
        sort_field="time_stamp",
        date_field="datetime",
    )
    if sample_latest and all(latest < expected for latest in sample_latest.values()):
        raise RuntimeError(
            f"stock_min({frequence}) is stale: expected trade date {expected}, "
            f"sample latest={sample_latest}; "
            "upstream TDX minute fetch likely failed for the whole market"
        )

    return {
        "expected_trade_date": expected,
        "frequence": frequence,
        "sample_latest": sample_latest,
    }

"""行情落库后的数据新鲜度和完整性校验。

QUANTAXIS 的 ``QA_SU_save_stock_day`` / ``QA_SU_save_stock_min`` 会把逐票抓取
异常吞掉(只打印 ERROR CODE 列表), 上游 TDX 服务器故障时整个市场一条都
没写入, Dagster run 仍然显示 SUCCESS。这里在资产落库后直接对 Mongo 断言
"最新已收盘交易日已经覆盖", 不新鲜就抛错让 asset 失败。

校验策略:
- 样本股票取几乎不会停牌的大盘蓝筹, 要求全部样本同时落后才判定为
  系统性停更, 单只股票停牌不会误报;
- ``stock_day`` 另做当日文档数下限校验, 用于捕获"只写入了少量股票"的
  部分故障。
- ETF 日线按最新交易日文档数兜底; ETF 分钟线以当日真实日线为基准,
  逐代码校验 1/5/15/30/60 分钟五种周期和合理 bar 数。TDX 发行期占位
  日线没有分钟源, 会被识别并豁免, 不伪造行情。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

# 大盘蓝筹样本: 平安银行 / 浦发银行 / 贵州茅台
FRESHNESS_SAMPLE_CODES: tuple[str, ...] = ("000001", "600000", "600519")
# 全市场约 5200 只, 正常交易日 stock_day 当日文档数约 5190(停牌股无 bar)
STOCK_DAY_MIN_DOCS = 3000

# ETF 全市场约 1675 只, 正常交易日 index_day 当日文档数约 1650。
ETF_DAY_MIN_DOCS = 1000
ETF_UNIVERSE_MIN_CODES = 1000
ETF_MIN_REAL_CODES = 1000
ETF_MIN_FREQUENCES: tuple[str, ...] = (
    "1min",
    "5min",
    "15min",
    "30min",
    "60min",
)
ETF_MIN_EXPECTED_BAR_COUNTS: Mapping[str, frozenset[int]] = MappingProxyType(
    {
        "1min": frozenset({239, 240}),
        "5min": frozenset({47, 48}),
        "15min": frozenset({15, 16}),
        "30min": frozenset({7, 8}),
        "60min": frozenset({3, 4}),
    }
)
_CHINA_TZ = ZoneInfo("Asia/Shanghai")


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

    # QUANTAXIS 默认只有 (code, date_stamp) 复合索引, 按 date 计数会全表扫;
    # 这里确保 date 单列索引存在(幂等, MongoDB 4.2+ 建索引不阻塞读写)
    coll.create_index("date")
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


def _is_etf_placeholder_day(document: Mapping[str, object]) -> bool:
    """TDX 发行期 ETF 日线占位: OHLC=1 且成交量/额为浮点哨兵。"""
    try:
        ohlc_placeholder = all(
            abs(float(str(document.get(field, 0))) - 1.0) < 1e-9
            for field in ("open", "close", "high", "low")
        )
        no_turnover = all(
            abs(float(str(document.get(field, 0)))) < 1e-30
            for field in ("vol", "amount")
        )
    except (TypeError, ValueError):
        return False
    return ohlc_placeholder and no_turnover


def _trade_date_timestamp_bounds(trade_date: str) -> tuple[float, float]:
    start = datetime.strptime(trade_date, "%Y-%m-%d").replace(tzinfo=_CHINA_TZ)
    end = start + timedelta(days=1)
    return start.timestamp(), end.timestamp()


def _normalize_security_code(value: object) -> str:
    code = str(value or "").strip()
    return code.zfill(6) if code else ""


def _load_etf_universe_codes(
    collection=None,
    *,
    min_codes: int = ETF_UNIVERSE_MIN_CODES,
) -> tuple[str, ...]:
    coll = collection if collection is not None else _default_collection("etf_list")
    codes = tuple(
        sorted(
            {
                code
                for document in coll.find({}, {"_id": 0, "code": 1})
                if (code := _normalize_security_code(document.get("code")))
            }
        )
    )
    if len(codes) < min_codes:
        raise RuntimeError(
            f"etf_list incomplete: only {len(codes)} unique codes "
            f"(expected >= {min_codes})"
        )
    return codes


def assert_etf_day_fresh(
    collection=None,
    etf_list_collection=None,
    *,
    expected_trade_date: str | None = None,
    min_docs: int = ETF_DAY_MIN_DOCS,
    min_universe_codes: int = ETF_UNIVERSE_MIN_CODES,
) -> dict:
    """校验 quantaxis.index_day 的 ETF 日线已覆盖最新交易日。"""
    coll = collection if collection is not None else _default_collection("index_day")
    expected = expected_trade_date or resolve_expected_trade_date()
    etf_codes = _load_etf_universe_codes(
        etf_list_collection,
        min_codes=min_universe_codes,
    )
    etf_code_set = set(etf_codes)

    coll.create_index("date")
    day_codes = {
        code
        for document in coll.find(
            {"date": expected, "code": {"$in": list(etf_codes)}},
            {"_id": 0, "code": 1},
        )
        if (code := _normalize_security_code(document.get("code"))) in etf_code_set
    }
    day_docs = len(day_codes)
    if day_docs < min_docs:
        raise RuntimeError(
            f"etf_day incomplete for {expected}: only {day_docs} unique ETF docs "
            f"(expected >= {min_docs}); upstream TDX ETF daily fetch likely "
            "failed for most of the market"
        )

    return {
        "expected_trade_date": expected,
        "universe_codes": len(etf_codes),
        "day_docs": day_docs,
    }


def assert_etf_min_fresh(
    day_collection=None,
    min_collection=None,
    etf_list_collection=None,
    *,
    expected_trade_date: str | None = None,
    frequencies: Sequence[str] = ETF_MIN_FREQUENCES,
    expected_bar_counts: Mapping[str, frozenset[int]] = (ETF_MIN_EXPECTED_BAR_COUNTS),
    min_day_docs: int = ETF_DAY_MIN_DOCS,
    min_real_codes: int = ETF_MIN_REAL_CODES,
    min_universe_codes: int = ETF_UNIVERSE_MIN_CODES,
) -> dict:
    """校验真实 ETF 日线都有五种分钟周期且 bar 数合理。"""
    day_coll = (
        day_collection
        if day_collection is not None
        else _default_collection("index_day")
    )
    min_coll = (
        min_collection
        if min_collection is not None
        else _default_collection("index_min")
    )
    expected = expected_trade_date or resolve_expected_trade_date()
    etf_codes = _load_etf_universe_codes(
        etf_list_collection,
        min_codes=min_universe_codes,
    )
    etf_code_set = set(etf_codes)
    requested_frequencies = tuple(str(item) for item in frequencies)
    unknown_frequencies = [
        item for item in requested_frequencies if item not in expected_bar_counts
    ]
    if unknown_frequencies:
        raise ValueError(f"missing expected bar counts for {unknown_frequencies}")

    day_coll.create_index("date")
    day_documents_by_code: dict[str, Mapping[str, object]] = {}
    for document in day_coll.find(
        {"date": expected, "code": {"$in": list(etf_codes)}},
        {
            "_id": 0,
            "code": 1,
            "open": 1,
            "close": 1,
            "high": 1,
            "low": 1,
            "vol": 1,
            "amount": 1,
        },
    ):
        code = _normalize_security_code(document.get("code"))
        if code in etf_code_set:
            day_documents_by_code[code] = document
    day_documents = list(day_documents_by_code.values())
    if len(day_documents) < min_day_docs:
        raise RuntimeError(
            f"etf_min cannot validate {expected}: only {len(day_documents)} "
            f"unique ETF day docs (expected >= {min_day_docs})"
        )

    real_documents = [
        document for document in day_documents if not _is_etf_placeholder_day(document)
    ]
    placeholder_codes = sorted(
        str(document.get("code") or "")
        for document in day_documents
        if _is_etf_placeholder_day(document)
    )
    if len(real_documents) < min_real_codes:
        raise RuntimeError(
            f"etf_min cannot validate {expected}: only {len(real_documents)} "
            f"real ETF day docs (expected >= {min_real_codes})"
        )

    start_timestamp, end_timestamp = _trade_date_timestamp_bounds(expected)
    missing: list[tuple[str, str]] = []
    invalid_counts: list[tuple[str, str, int]] = []
    checked_groups = 0

    for document in real_documents:
        code = str(document.get("code") or "").zfill(6)
        counts = Counter(
            str(item.get("type") or "")
            for item in min_coll.find(
                {
                    "code": code,
                    "time_stamp": {
                        "$gte": start_timestamp,
                        "$lt": end_timestamp,
                    },
                    "type": {"$in": list(requested_frequencies)},
                },
                {"_id": 0, "type": 1},
            )
        )
        for frequence in requested_frequencies:
            bar_count = int(counts.get(frequence, 0))
            if bar_count == 0:
                missing.append((code, frequence))
            elif bar_count not in expected_bar_counts[frequence]:
                invalid_counts.append((code, frequence, bar_count))
            checked_groups += 1

    if missing or invalid_counts:
        raise RuntimeError(
            f"etf_min incomplete for {expected}: "
            f"missing_groups={len(missing)} invalid_bar_counts={len(invalid_counts)} "
            f"missing_sample={missing[:10]} "
            f"invalid_sample={invalid_counts[:10]}"
        )

    return {
        "expected_trade_date": expected,
        "universe_codes": len(etf_codes),
        "day_docs": len(day_documents),
        "real_codes": len(real_documents),
        "placeholder_codes": len(placeholder_codes),
        "placeholder_sample": placeholder_codes[:10],
        "frequencies": list(requested_frequencies),
        "checked_groups": checked_groups,
    }

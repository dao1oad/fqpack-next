# -*- coding: utf-8 -*-

from datetime import datetime
from typing import List

from freshquant.database.cache import in_memory_cache
from freshquant.db import DBfreshquant
from freshquant.runtime_constants import TZ
from freshquant.util.code import (
    fq_util_code_append_market_code,
    fq_util_code_append_market_code_suffix,
)


def _is_active_member(record, *, now: datetime | None = None) -> bool:
    """D1/S4（步骤 7）：must_pool 成员只有「非 disabled 且未过期」才可参与
    5m 首开。

    - disabled=true → 非 active；
    - forever=true → 永久 active；
    - 顶层 expire_at 已过 → 非 active；
    - memberships 中任一 expire_at 为空或未过 → active；全部过期 → 非 active；
    - 无 memberships（legacy 记录）→ active（兼容历史，无过期信号）。
    """

    now = now or datetime.now(TZ)
    now = _coerce_aware(now)
    if record.get("disabled") is True:
        return False
    if record.get("forever") is True:
        return True
    expire_at = _coerce_aware(record.get("expire_at"))
    if expire_at is not None and expire_at < now:
        return False
    memberships = record.get("memberships") or []
    if not memberships:
        return True
    for item in memberships:
        item_expire = _coerce_aware(item.get("expire_at"))
        if item_expire is None:
            return True
        if item_expire >= now:
            return True
    return False


def _coerce_aware(value, tz=TZ):
    """统一为 tz-aware datetime（Mongo tz_aware 客户端读出为 aware；
    naive 值按 Asia/Shanghai 归一；非 datetime 返回 None）。"""

    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def _active_records(instrument_types: List[str]) -> list[dict]:
    records = list(
        DBfreshquant["must_pool"].find({"instrument_type": {"$in": instrument_types}})
    )
    return [item for item in records if _is_active_member(item)]


@in_memory_cache.memoize(expiration=60)
def queryMustPoolCodes(
    instrumentTypes: List[str] = ["stock_cn", "etf_cn"]
) -> List[str]:
    records = _active_records(instrumentTypes)
    return [item["code"] for item in records]


@in_memory_cache.memoize(expiration=3600)
def queryMustPoolCodesWithMarketCodePrefix(
    instrumentTypes: List[str] = ["stock_cn", "etf_cn"]
) -> List[str]:
    records = _active_records(instrumentTypes)
    return [fq_util_code_append_market_code(item["code"]) for item in records]


@in_memory_cache.memoize(expiration=3600)
def queryMustPoolCodesWithMarketCodeSuffix(
    instrumentTypes: List[str] = ["stock_cn", "etf_cn"]
) -> List[str]:
    records = _active_records(instrumentTypes)
    return [fq_util_code_append_market_code_suffix(item["code"]) for item in records]


def cleanMustPool():
    positions = list(DBfreshquant["xt_positions"].find({}))
    codes = [item["stock_code"][:6] for item in positions]
    DBfreshquant["must_pool"].delete_many({"code": {"$in": codes}})


if __name__ == "__main__":
    cleanMustPool()

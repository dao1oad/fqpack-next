# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from typing import Any

from pymongo import UpdateOne

from freshquant.db import DBfreshquant


def upsert_realtime_bars(
    *,
    collection: str,
    code: str,
    frequence: str,
    records: list[dict[str, Any]],
) -> int:
    """
    Upsert realtime bars into DBfreshquant.<collection>.

    Required fields in each record:
    - datetime (datetime)
    - open/high/low/close (float)
    - volume/amount (float, optional)
    """
    if not records:
        return 0
    batch: list[UpdateOne] = []
    for r in records:
        dt = r.get("datetime")
        if not isinstance(dt, datetime):
            continue
        q = {"datetime": dt, "code": code, "frequence": frequence}
        batch.append(UpdateOne(q, {"$set": r}, upsert=True))
    if not batch:
        return 0
    res = DBfreshquant[collection].bulk_write(batch, ordered=False)
    return (
        int(res.upserted_count or 0)
        + int(res.modified_count or 0)
        + int(res.matched_count or 0)
    )

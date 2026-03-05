# -*- coding:utf-8 -*-

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

import pandas as pd
import pendulum
from pymongo import UpdateOne

from freshquant.db import DBfreshquant, DBQuantAxis
from freshquant.gateway import getTdxhqEndpoint
from freshquant.instrument.future import query_cn_future_product_table
from freshquant.util.convert import toDf


def fqFutureFetchInstrument(code: str) -> Optional[Dict[str, Any]]:
    return DBQuantAxis['future_list'].find_one({'code': code})


def fqFutureGetExtensionMarketList() -> pd.DataFrame:
    endpoint = getTdxhqEndpoint()
    req = urllib.request.Request(
        urllib.parse.urljoin(endpoint, '/ex/get_markets'), method='GET'
    )
    resp = urllib.request.urlopen(req, timeout=30)
    markets = json.loads(resp.read().decode('utf-8'))
    return toDf(markets)


def fqFutureGetExtensionInstrumentCount() -> int:
    endpoint = getTdxhqEndpoint()
    req = urllib.request.Request(
        urllib.parse.urljoin(endpoint, '/ex/get_instrument_count'), method='GET'
    )
    resp = urllib.request.urlopen(req, timeout=30)
    num = int(resp.read().decode('utf-8'))
    return num


def fqFutureGetExtensionInstrumentInfo(start: int, count: int = 500) -> pd.DataFrame:
    endpoint = getTdxhqEndpoint()
    query = urllib.parse.urlencode({'start': start, 'count': count})
    req = urllib.request.Request(
        urllib.parse.urljoin(endpoint, f'/ex/get_instrument_info?{query}'), method='GET'
    )
    resp = urllib.request.urlopen(req, timeout=30)
    info = json.loads(resp.read().decode('utf-8'))
    return toDf(info)


def fqFutureGetExtensionInstrumentList() -> pd.DataFrame:
    num = fqFutureGetExtensionInstrumentCount()
    return pd.concat(
        [
            fqFutureGetExtensionInstrumentInfo((int(num / 500) - i) * 500, 500)
            for i in range(int(num / 500) + 1)
        ],
        ignore_index=True,
    )


def fqFutureGetInstrumentBars(
    code: str, count: int = 700, frequence: str = '1min'
) -> Optional[pd.DataFrame]:
    endpoint = getTdxhqEndpoint()
    instrument = fqFutureFetchInstrument(code)
    if instrument is None:
        return None

    freq_value: int
    if str(frequence) in ['5', '5m', '5min', 'five']:
        freq_value = 0
    elif str(frequence) in ['1', '1m', '1min', 'one']:
        freq_value = 8
    elif str(frequence) in ['15', '15m', '15min', 'fifteen']:
        freq_value = 1
    elif str(frequence) in ['30', '30m', '30min', 'half']:
        freq_value = 2
    elif str(frequence) in ['60', '60m', '60min', '1h']:
        freq_value = 3
    else:
        freq_value = 8  # default to 1min

    pages = int(count / 700) + (1 if count % 700 > 0 else 0)
    df: Optional[pd.DataFrame] = None
    for i in range(1, pages + 1):
        query = urllib.parse.urlencode(
            {
                'category': freq_value,
                'market': instrument['market'],
                'code': code,
                'start': (pages - i) * 700,
                'count': count - (pages - i) * 700 if i == 1 else 700,
            }
        )
        req = urllib.request.Request(
            urllib.parse.urljoin(endpoint, f'/ex/get_instrument_bars?{query}'),
            method='GET',
        )
        resp = urllib.request.urlopen(req, timeout=30)
        text = resp.read().decode('utf-8')
        if df is None:
            df = toDf(json.loads(text))
        else:
            df = pd.concat([df, toDf(json.loads(text))], ignore_index=True)
    return df


def fqFutureSaveExMarkets(exMarkets: Optional[pd.DataFrame]) -> None:
    if exMarkets is None:
        return
    start = pendulum.now()
    batch: List[UpdateOne] = []
    for _, row in exMarkets.iterrows():
        now = pendulum.now()
        batch.append(
            UpdateOne(
                {"market": row["market"], "category": row["category"]},
                {
                    "$set": {
                        "name": row["name"],
                        "short_name": row["short_name"],
                        "update_time": now.int_timestamp,
                        "update_time_str": now.to_datetime_string(),
                    }
                },
                upsert=True,
            )
        )
        if len(batch) >= 1000:
            DBfreshquant["tdx_ex_markets"].bulk_write(batch)
            batch = []
    if len(batch) > 0:
        DBfreshquant["tdx_ex_markets"].bulk_write(batch)
    DBfreshquant["tdx_ex_markets"].delete_many(
        {"update_time": {"$lt": start.int_timestamp}}
    )


def fetchExMainContracts() -> List[str]:
    futureProductTable: pd.DataFrame = query_cn_future_product_table()
    monthCode = pendulum.now().format("YYYYMM")
    monthCodeLen4 = monthCode[2:]
    monthCodeLen3 = monthCode[3:]
    codes: List[str] = []
    for _, row in futureProductTable.iterrows():
        monthCodeLen = row["tdx_month_code_len"]
        monthCode = monthCodeLen4
        if monthCodeLen == 3:
            monthCode = monthCodeLen3
        productCode = row["tdx_product_code"]
        code = f'{productCode}{monthCode}'
        latestOne = DBQuantAxis["future_day"].find_one(
            {
                "$and": [
                    {"code": {"$gte": code}},
                    {
                        "code": {
                            "$regex": "^"
                            + productCode
                            + "\\d{"
                            + str(monthCodeLen)
                            + "}"
                        }
                    },
                ],
                "date": {"$gte": pendulum.now().subtract(weeks=1).format("YYYY-MM-DD")},
            },
            sort=[('date', -1)],
        )
        if latestOne is None:
            continue
        futures = list(
            DBQuantAxis["future_day"].find(
                {
                    "$and": [
                        {"code": {"$gte": code}},
                        {
                            "code": {
                                "$regex": "^"
                                + productCode
                                + "\\d{"
                                + str(monthCodeLen)
                                + "}"
                            }
                        },
                    ],
                    "date": latestOne["date"],
                },
                sort=[("position", -1)],
            )
        )
        if len(futures) == 0:
            continue
        for i, future in enumerate(futures):
            if i == 0:
                codes.append(future["code"])
            elif (
                future["position"] > futures[0]["position"] / 2
                and future["code"] > futures[0]["code"]
            ):
                codes.append(future["code"])
    return codes


def fqFutureSaveExMainContracts(mainContracts: Optional[List[str]]) -> None:
    if mainContracts is None:
        return
    start = pendulum.now()
    batch: List[UpdateOne] = []
    for mainContract in mainContracts:
        now = pendulum.now()
        batch.append(
            UpdateOne(
                {"code": mainContract},
                {
                    "$set": {
                        "code": mainContract,
                        "update_time": now.int_timestamp,
                        "update_time_str": now.to_datetime_string(),
                    }
                },
                upsert=True,
            )
        )
        if len(batch) >= 1000:
            DBfreshquant["tdx_ex_main_contracts"].bulk_write(batch)
            batch = []
    if len(batch) > 0:
        DBfreshquant["tdx_ex_main_contracts"].bulk_write(batch)
    DBfreshquant["tdx_ex_main_contracts"].delete_many(
        {"update_time": {"$lt": start.int_timestamp}}
    )


if __name__ == "__main__":
    # print(fqFutureGetInstrumentBars('RBL9', 800))
    print(fetchExMainContracts())

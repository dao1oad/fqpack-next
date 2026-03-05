# -*- coding: utf-8 -*-

from typing import Dict, List

import pandas as pd
import pendulum
import pymongo

from freshquant.carnation.param import queryParam
from freshquant.database.cache import in_memory_cache
from freshquant.database.mongodb import DBfreshquant
from freshquant.instrument.code import (
    convert_code_tdx_to_tq,
    convert_code_tq_to_tdx,
    extract_code_alpha_prefix,
)


def insertForCnFutureLongPosition(accLong: List, item: Dict):
    for i in range(len(accLong)):
        if accLong[i]["price"] < item["price"]:
            accLong.insert(i, item)
            break
    else:
        accLong.append(item)
    return accLong


def insertForCnFutureShortPosition(accShort: List, item: Dict):
    for i in range(len(accShort)):
        if accShort[i]["price"] > item["price"]:
            accShort.insert(i, item)
            break
    else:
        accShort.append(item)
    return accShort


def accCnFutureTrades(accLong: List, accShort: List, cur: Dict):
    if cur["offset"] == "OPEN":
        if cur["direction"] == "BUY":  # 开多单
            accLong = insertForCnFutureLongPosition(
                accLong,
                {
                    "direction": "LONG",
                    "pos": cur["volume"],
                    "price": cur["price"],
                    "trade_date_time": cur["trade_date_time"],
                },
            )
        else:  # 开空单
            accShort = insertForCnFutureShortPosition(
                accShort,
                {
                    "direction": "SHORT",
                    "pos": cur["volume"],
                    "price": cur["price"],
                    "trade_date_time": cur["trade_date_time"],
                },
            )
    elif cur["offset"] == "CLOSE":
        if cur["direction"] == "BUY":  # 平空单
            if len(accShort) > 0:
                if accShort[-1]["pos"] < cur["volume"]:
                    cur["volume"] = cur["volume"] - accShort[-1]["pos"]
                    accShort.pop()
                    accLong, accShort = accCnFutureTrades(accLong, accShort, cur)
                elif accShort[-1]["pos"] == cur["volume"]:
                    accShort.pop()
                else:
                    accShort[-1]["pos"] = accShort[-1]["pos"] - cur["volume"]
        else:  # 平多单
            if len(accLong) > 0:
                if accLong[-1]["pos"] < cur["volume"]:
                    cur["volume"] = cur["volume"] - accLong[-1]["pos"]
                    accLong.pop()
                    accLong, accShort = accCnFutureTrades(accLong, accShort, cur)
                elif accLong[-1]["pos"] == cur["volume"]:
                    accLong.pop()
                else:
                    accLong[-1]["pos"] = accLong[-1]["pos"] - cur["volume"]
    return accLong, accShort


def queryCnFuturePositions():
    records = (
        DBfreshquant["future_fills"]
        .find({"_dr": {"$ne": True}})
        .sort([("trade_date_time", pymongo.ASCENDING)])
    )
    df = pd.DataFrame(records)
    if not df.empty:
        positions = {}
        records = df.to_dict("records")
        for record in records:
            if positions.get(record["instrument_id"]) is None:
                positions[record["instrument_id"]] = {
                    "long": [],
                    "short": [],
                }
            accLong = positions[record["instrument_id"]]["long"]
            accShort = positions[record["instrument_id"]]["short"]
            record["trade_date_time"] = int(record["trade_date_time"])
            accLong, accShort = accCnFutureTrades(accLong, accShort, record)
        return positions
    else:
        return None


@in_memory_cache.memoize()
def queryCnFuturePositionCodes():
    codes = []
    records = queryCnFuturePositions()
    if records:
        for code in records:
            codes.append(convert_code_tq_to_tdx(code))
    return codes


def queryCnFutureFillList(symbol):
    symbol = convert_code_tdx_to_tq(symbol)
    records = (
        DBfreshquant["future_fills"]
        .find({"instrument_id": symbol, "_dr": {"$ne": True}})
        .sort([("trade_date_time", pymongo.ASCENDING)])
    )
    df = pd.DataFrame(records)
    if not df.empty:
        records = df.to_dict("records")
        accLong: List = []
        accShort: List = []
        for record in records:
            record["trade_date_time"] = int(record["trade_date_time"])
            accLong, accShort = accCnFutureTrades(accLong, accShort, record)
        return accLong, accShort
    else:
        return None, None


def accArrangedCnFutureTrades(
    accLong: List, accShort: List, cur: Dict, lotVolume: int, priceGap: int
):
    if cur["offset"] == "OPEN":
        if cur["direction"] == "BUY":  # 开多单
            if cur["volume"] > lotVolume:
                accLong = insertForCnFutureLongPosition(
                    accLong,
                    {
                        "direction": "LONG",
                        "pos": lotVolume,
                        "price": cur["price"],
                        "trade_date_time": cur["trade_date_time"],
                    },
                )
                cur["volume"] = cur["volume"] - lotVolume
                cur["price"] = cur["price"] + priceGap
                accLong, accShort = accArrangedCnFutureTrades(
                    accLong, accShort, cur, lotVolume, priceGap
                )
            else:
                accLong = insertForCnFutureLongPosition(
                    accLong,
                    {
                        "direction": "LONG",
                        "pos": cur["volume"],
                        "price": cur["price"],
                        "trade_date_time": cur["trade_date_time"],
                    },
                )
        else:  # 开空单
            if cur["volume"] > lotVolume:
                accShort = insertForCnFutureShortPosition(
                    accShort,
                    {
                        "direction": "SHORT",
                        "pos": lotVolume,
                        "price": cur["price"],
                        "trade_date_time": cur["trade_date_time"],
                    },
                )
                cur["volume"] = cur["volume"] - lotVolume
                cur["price"] = cur["price"] - priceGap
                accLong, accShort = accArrangedCnFutureTrades(
                    accLong, accShort, cur, lotVolume, priceGap
                )
            else:
                accShort = insertForCnFutureShortPosition(
                    accShort,
                    {
                        "direction": "SHORT",
                        "pos": cur["volume"],
                        "price": cur["price"],
                        "trade_date_time": cur["trade_date_time"],
                    },
                )
    elif cur["offset"] == "CLOSE":
        if cur["direction"] == "BUY":  # 平空单
            if len(accShort) > 0:
                if accShort[-1]["pos"] < cur["volume"]:
                    cur["volume"] = cur["volume"] - accShort[-1]["pos"]
                    accShort.pop()
                    accLong, accShort = accCnFutureTrades(accLong, accShort, cur)
                elif accShort[-1]["pos"] == cur["volume"]:
                    accShort.pop()
                else:
                    accShort[-1]["pos"] = accShort[-1]["pos"] - cur["volume"]
        else:  # 平多单
            if len(accLong) > 0:
                if accLong[-1]["pos"] < cur["volume"]:
                    cur["volume"] = cur["volume"] - accLong[-1]["pos"]
                    accLong.pop()
                    accLong, accShort = accCnFutureTrades(accLong, accShort, cur)
                elif accLong[-1]["pos"] == cur["volume"]:
                    accLong.pop()
                else:
                    accLong[-1]["pos"] = accLong[-1]["pos"] - cur["volume"]
    return accLong, accShort


def queryArrangedCnFutureFillList(symbol: str):
    symbol = convert_code_tdx_to_tq(symbol)
    # 取symbol的开头字母字符串
    productId = extract_code_alpha_prefix(symbol).upper()
    lotVolume = queryParam(f"guardian.future.{productId}.lot_volume", 1)
    priceGap = queryParam(f"guardian.future.{productId}.price_gap", 50)
    records = (
        DBfreshquant["future_fills"]
        .find({"instrument_id": symbol, "_dr": {"$ne": True}})
        .sort([("trade_date_time", pymongo.ASCENDING)])
    )
    df = pd.DataFrame(records)
    if not df.empty:
        records = df.to_dict("records")
        accLong: List = []
        accShort: List = []
        for record in records:
            record["trade_date_time"] = int(record["trade_date_time"])
            accLong, accShort = accArrangedCnFutureTrades(
                accLong, accShort, record, lotVolume, priceGap
            )
        return accLong, accShort
    else:
        return None, None


# def queryCnFuturePositions():
#     records = (
#         DBfreshquant["future_fills"]
#         .find({"_dr": {"$ne": True}})
#         .sort([("trade_date_time", pymongo.ASCENDING)])
#     )
#     df = pd.DataFrame(records)
#     if not df.empty:
#         positions = {}
#         records = df.to_dict("records")
#         for record in records:
#             if positions.get(record["instrument_id"]) is None:
#                 positions[record["instrument_id"]] = {
#                     "long": [],
#                     "short": [],
#                 }
#             accLong = positions[record["instrument_id"]]["long"]
#             accShort = positions[record["instrument_id"]]["short"]
#             record["trade_date_time"] = int(record["trade_date_time"])
#             accLong, accShort = accCnFutureTrades(accLong, accShort, record)
#         return positions
#     else:
#         return None


def cleanCnFutureXtTrades():
    DBfreshquant["future_fills"].delete_many(
        {
            "_dr": True,
            "trade_date_time": {
                "$lt": pendulum.now().subtract(years=1).int_timestamp
            },
        }
    )
    records = (
        DBfreshquant["future_fills"]
        .find({"_dr": {"$ne": True}})
        .sort([("trade_date_time", pymongo.ASCENDING)])
    )
    df = pd.DataFrame(records)
    if not df.empty:
        positions = {}
        records = df.to_dict("records")
        for record in records:
            if positions.get(record["instrument_id"]) is None:
                positions[record["instrument_id"]] = {
                    "long": [],
                    "short": [],
                    "longTrades": [],
                    "shortTrades": [],
                }
            accLong = positions[record["instrument_id"]]["long"]
            accShort = positions[record["instrument_id"]]["short"]
            longTrades = positions[record["instrument_id"]]["longTrades"]
            shortTrades = positions[record["instrument_id"]]["shortTrades"]
            record["trade_date_time"] = int(record["trade_date_time"])
            if (record["direction"] == "BUY" and record["offset"] == "OPEN") or (
                record["direction"] == "SELL" and record["offset"] == "CLOSE"
            ):
                longTrades.append(record)
            else:
                shortTrades.append(record)
            accLong, accShort = accCnFutureTrades(accLong, accShort, record)
            if len(accLong) == 0:
                ids = [trade["_id"] for trade in longTrades]
                DBfreshquant["future_fills"].update_many(
                    {"_id": {"$in": ids}}, {"$set": {"_dr": True}}
                )
                positions[record["instrument_id"]]["longTrades"] = []
            if len(accShort) == 0:
                ids = [trade["_id"] for trade in shortTrades]
                DBfreshquant["future_fills"].update_many(
                    {"_id": {"$in": ids}}, {"$set": {"_dr": True}}
                )
                positions[record["instrument_id"]]["shortTrades"] = []
        return positions
    else:
        return None


if __name__ == "__main__":
    print(queryCnFuturePositionCodes())

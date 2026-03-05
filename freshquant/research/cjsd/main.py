import concurrent.futures
import os
import traceback

import pendulum
import pydash
import pymongo
from datetime import datetime
from loguru import logger
from MyTT import MA, REF
from pytdx.reader import BlockReader
from talib import ATAN
from tqdm import tqdm
from freshquant.trading.dt import fq_trading_fetch_trade_dates
from freshquant.config import settings
from freshquant.data.index import fqDataIndexFetchDay
from freshquant.data.stock import fq_data_stock_fetch_day
from freshquant.database.cache import redis_cache
from freshquant.db import DBfreshquant, DBQuantAxis
from freshquant.signal.a_stock_common import save_a_stock_pre_pools
from freshquant.util.code import fq_util_code_append_market_code
from freshquant.util.encoding import detectEncoding

black_block_list = ["含H股", "含B股", "TDX", "昨日", "昨曾", "ST", "昨收", "活跃股", "不活跃股",
                    "近期复牌", "历史新高", "近期强势", "昨成交20"]

def prepare_cjsd_index():
    tdx_home = pydash.get(settings, "tdx.home") or os.getenv('TDX_HOME')
    index_list = []
    tdxzs_path = os.path.join(tdx_home, "T0002/hq_cache/tdxzs.cfg")
    if os.path.exists(tdxzs_path):
        encoding = detectEncoding(tdxzs_path)
        with open(tdxzs_path, "r", encoding=encoding) as f:
            for line in f:
                line = line.strip()
                if line:
                    cols = line.split("|")
                    if len(cols) > 5:  # Ensure we have enough columns
                        index_item = {
                            "code": cols[1],
                            "name": cols[0],
                            "category": cols[2],
                            "hy_code": cols[5]
                        }
                        # Filter based on category and name
                        if index_item["category"] in ("2", "4") and \
                           not any(black in index_item["name"] for black in black_block_list):
                            index_list.append(index_item)
    index_list = (
        pydash.chain(index_list)
        .map(
            lambda item: {
                "code": item["code"],
                "name": item["name"],
                "category": "行业板块"
                if item["category"] == "2"
                else "概念板块"
                if item["category"] == "4"
                else "",
                "hy_code": item["hy_code"],
                "updated": pendulum.now(),
            }
        )
        .value()
    )
    hy_list = []
    tdxhy_path = os.path.join(tdx_home, "T0002/hq_cache/tdxhy.cfg")
    if os.path.exists(tdxhy_path):
        encoding = detectEncoding(tdxhy_path)
        with open(tdxhy_path, "r", encoding=encoding) as f:
            for line in f:
                line = line.strip()
                if line:
                    cols = line.split("|")
                    if len(cols) > 2:  # Ensure we have enough columns
                        hy_list.append({
                            "code": cols[1],
                            "hy_code": cols[2]
                        })
    block_gn = []
    block_gn_path = os.path.join(tdx_home, "T0002/hq_cache/block_gn.dat")
    if os.path.exists(block_gn_path):
        block_gn = BlockReader().get_data(block_gn_path, "block_gn.dat")

    for index_item in index_list:
        codes = []
        codes.extend(
            pydash.chain(block_gn)
            .filter(lambda item: item["blockname"] == index_item["name"])
            .map(lambda item: item["code"])
            .value()
        )
        codes.extend(
            pydash.chain(hy_list)
            .filter(lambda item: item["hy_code"] == index_item["hy_code"])
            .map(lambda item: item["code"])
            .value()
        )
        if len(codes) == 0:
            continue
        index_item["codes"] = codes
        DBfreshquant.gnhy_index_list.update_one(
            {"code": index_item["code"]},
            {"$set": index_item},
            upsert=True,
        )
    # 还需要从新的板块文件T0002/hq_cache/infoharbor_block.dat获取板块信息
    # Parse infoharbor_block.dat
    infoharbor_path = os.path.join(tdx_home, "T0002/hq_cache/infoharbor_block.dat")
    if os.path.exists(infoharbor_path):
        encoding = detectEncoding(infoharbor_path)
        current_block = None
        with open(infoharbor_path, "r", encoding=encoding) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#"):
                    # Parse block info: 板块名称,含股票数量,板块代码,创建时间,变更时间
                    parts = line[1:].split(",")
                    if len(parts) >= 5:
                        if parts[2]:  # Only create block if code exists
                            current_block = {
                                "code": parts[2],
                                "name": parts[0].split("_")[-1],
                                "category": "板块",
                                "hy_code": "",
                                "updated": pendulum.now(),
                                "codes": []
                        }
                elif current_block and line:
                    # Parse stock codes: 市场#股票代码,市场#股票代码
                    codes = []
                    for code_pair in line.split(","):
                        if "#" not in code_pair:
                            continue
                        market, stock_code = code_pair.split("#")
                        if market in ("0", "1"):
                            codes.append(f"{stock_code}")
                    current_block["codes"].extend(codes)
                    # Update to database only if name doesn't contain blacklisted strings
                    if not any(black in current_block["name"] for black in black_block_list):
                        DBfreshquant.gnhy_index_list.update_one(
                            {"code": current_block["code"]},
                            {"$set": current_block},
                            upsert=True,
                        )
                    current_block = None

    DBfreshquant.gnhy_index_list.delete_many({"updated": {"$lte": pendulum.yesterday()}})


def apply_cjsd_to_stock_pool():
    trade_dates = fq_trading_fetch_trade_dates()
    future_trade_dates = trade_dates[trade_dates['trade_date'] > datetime.now().date()]
    future_trade_dates = future_trade_dates["trade_date"].head(5)
    trade_dates = trade_dates[trade_dates['trade_date'] <= datetime.now().date()]
    trade_dates = trade_dates["trade_date"].tail(5)
    cjsdList = list(
        DBfreshquant["index_score"].aggregate(
            [
                {
                    "$match": {
                        "date": {
                            "$gte": trade_dates.iloc[0].strftime("%Y-%m-%d")
                        }
                    }
                },
                {"$sort": {"date": -1, "cjsd_score": -1}},
                {"$group": {"_id": "$date", "records": {"$push": "$$ROOT"}}},
                {"$sort": {"_id": -1}},
            ]
        )
    )
    gnhyIndex = getGnhyIndex()
    for cjsd in cjsdList:
        date = cjsd["_id"]
        records = pydash.chain(cjsd).get("records").take(5).value()
        for i in range(len(records)):
            code = records[i]["code"]
            codes = pydash.get(gnhyIndex, f"{code}.codes", [])
            codes = getStockCjsdScores(date, codes)
            cjsd = f"{date}超级赛道{i+1}"
            codes = (
                pydash.chain(codes)
                .take(5)
                .map(lambda r: {"code": r["code"], "name": r["name"]})
                .value()
            )
            for item in codes:
                save_a_stock_pre_pools(
                    item["code"], cjsd, expire_at=datetime.combine(future_trade_dates.iloc[-1], datetime.max.time())
                )
        break
    # 把掉出超级赛道的股票从股票池清理掉
    retain_codes = []
    for cjsd in cjsdList:
        date = cjsd["_id"]
        # 取前10个概念行业
        records = pydash.chain(cjsd).get("records").take(10).value()
        for i in range(len(records)):
            gnhy_code = records[i]["code"]
            codes = pydash.get(gnhyIndex, f"{gnhy_code}.codes", [])
            codes = getStockCjsdScores(date, codes)
            codes = (
                pydash.chain(codes)
                .take(5)
                .map(lambda r: {"code": r["code"], "name": r["name"]})
                .value()
            )
            retain_codes.extend([item["code"] for item in codes])
    retain_codes = list(set(retain_codes))
    DBfreshquant["stock_pre_pools"].delete_many(
        {
            "code": {"$nin": retain_codes},
            "category": {"$regex": "超级赛道", "$options": "i"}
        }
    )

def calcCjsdScoreAll():
    cjsdStockScore = DBfreshquant["stock_score"]
    indexes = cjsdStockScore.index_information()
    if "idx_date" not in indexes:
        cjsdStockScore.create_index(
            [
                ("date", pymongo.DESCENDING),
            ],
            name="idx_date",
        )
    if "idx_code" not in indexes:
        cjsdStockScore.create_index(
            [
                ("code", pymongo.DESCENDING),
            ],
            name="idx_code",
        )
    if "idx_date_code" not in indexes:
        cjsdStockScore.create_index(
            [
                ("date", pymongo.DESCENDING),
                ("code", pymongo.ASCENDING),
            ],
            name="idx_date_code",
            unique=True,
        )
    cjsdIndexScore = DBfreshquant["index_score"]
    indexes = cjsdIndexScore.index_information()
    if "idx_date" not in indexes:
        cjsdIndexScore.create_index(
            [
                ("date", pymongo.DESCENDING),
            ],
            name="idx_date",
        )
    if "idx_code" not in indexes:
        cjsdIndexScore.create_index(
            [
                ("code", pymongo.DESCENDING),
            ],
            name="idx_code",
        )
    if "idx_date_code" not in indexes:
        cjsdIndexScore.create_index(
            [
                ("date", pymongo.DESCENDING),
                ("code", pymongo.ASCENDING),
            ],
            name="idx_date_code",
            unique=True,
        )

    # 如果想使用多进程的并发，可以试试设置当前进程为非daemon进程。
    # multiprocessing.current_process()._config['daemon'] = False
    # https://github.com/celery/celery/discussions/7046
    executor = concurrent.futures.ThreadPoolExecutor()
    stockList = [stock for stock in DBQuantAxis["stock_list"].find({}) if "ST" not in stock["name"]]

    tasks = [
        executor.submit(calcCjsdStockScoreItem, stockItem) for stockItem in stockList
    ]
    [
        task.result()
        for task in tqdm(
            concurrent.futures.as_completed(tasks), desc="超级赛道股票得分计算", total=len(tasks)
        )
    ]
    gnhy_index_list = list(DBfreshquant.gnhy_index_list.find({}))
    tasks = [
        executor.submit(calcCjsdIndexScoreItem, index_item)
        for index_item in gnhy_index_list
    ]
    [
        task.result()
        for task in tqdm(
            concurrent.futures.as_completed(tasks), desc="超级赛道板块得分计算", total=len(tasks)
        )
    ]


def calcCjsdIndexScoreItem(index_item):
    try:
        # Skip if code is None or empty string
        if not index_item.get("code"):
            return
        data = fqDataIndexFetchDay(
            index_item["code"], pendulum.now().add(days=-1000), pendulum.now()
        )
        if data is not None and len(data) > 60:
            close = data.close.values
            score05 = ATAN((MA(close, 5) / REF(MA(close, 5), 1) - 1) * 100) * 57.3
            score13 = ATAN((MA(close, 13) / REF(MA(close, 13), 1) - 1) * 100) * 57.3
            score20 = ATAN((MA(close, 20) / REF(MA(close, 20), 1) - 1) * 100) * 57.3
            score60 = ATAN((MA(close, 60) / REF(MA(close, 60), 1) - 1) * 100) * 57.3
            score = score05 / 60 + score13 / 40 + score20 / 21 + score60 / 10
            data["score"] = score
            data = data[-60:]
            for _, row in data.dropna(subset=["score"]).iterrows():
                date = row["datetime"].strftime("%Y-%m-%d")
                code = index_item["code"]
                name = index_item["name"]
                score = row["score"]
                DBfreshquant["index_score"].update_one(
                    {"code": code, "date": date},
                    {
                        "$set": {
                            "code": code,
                            "date": date,
                            "name": name,
                            "cjsd_score": score,
                        }
                    },
                    upsert=True,
                )
    except Exception:
        logger.error("Error Occurred: {0}".format(traceback.format_exc()))
    return


def calcCjsdStockScoreItem(stockItem):
    try:
        data = fq_data_stock_fetch_day(
            stockItem["code"], pendulum.now().add(days=-1000), pendulum.now()
        )
        if data is not None and len(data) > 60:
            close = data.close.values
            score05 = ATAN((MA(close, 5) / REF(MA(close, 5), 1) - 1) * 100) * 57.3
            score13 = ATAN((MA(close, 13) / REF(MA(close, 13), 1) - 1) * 100) * 57.3
            score20 = ATAN((MA(close, 20) / REF(MA(close, 20), 1) - 1) * 100) * 57.3
            score60 = ATAN((MA(close, 60) / REF(MA(close, 60), 1) - 1) * 100) * 57.3
            score = score05 / 60 + score13 / 40 + score20 / 21 + score60 / 10
            data["score"] = score
            data = data[-60:]
            for _, row in data.dropna(subset=["score"]).iterrows():
                date = row["datetime"].strftime("%Y-%m-%d")
                code = stockItem["code"]
                name = stockItem["name"]
                score = row["score"]
                DBfreshquant["stock_score"].update_one(
                    {"code": code, "date": date},
                    {
                        "$set": {
                            "code": code,
                            "date": date,
                            "name": name,
                            "cjsd_score": score,
                        }
                    },
                    upsert=True,
                )
    except BaseException:
        logger.error("Error Occurred: {0}".format(traceback.format_exc()))
    return


@redis_cache.memoize()
def getGnhyIndex():
    data = list(DBfreshquant["gnhy_index_list"].find({}))
    return pydash.key_by(data, "code")


@redis_cache.memoize()
def getStockCjsdScores(date, codes):
    data = list(
        DBfreshquant["stock_score"]
        .find({"date": date, "code": {"$in": codes}})
        .sort("cjsd_score", pymongo.DESCENDING)
    )
    return data


def getCjsdList():
    cjsdList = list(
        DBfreshquant["index_score"].aggregate(
            [
                {
                    "$match": {
                        "date": {
                            "$gte": pendulum.now().add(days=-100).format("YYYY-MM-DD")
                        }
                    }
                },
                {"$sort": {"date": -1, "cjsd_score": -1}},
                {"$group": {"_id": "$date", "records": {"$push": "$$ROOT"}}},
                {"$sort": {"_id": -1}},
            ]
        )
    )
    gnhyIndex = getGnhyIndex()
    # 概念行业板块前十
    # 每个概念行业前五个
    result = []
    for cjsd in cjsdList:
        date = cjsd["_id"]
        record = {"date": date}
        records = pydash.chain(cjsd).get("records").take(10).value()
        for i in range(len(records)):
            code = records[i]["code"]
            name = records[i]["name"]
            codes = pydash.get(gnhyIndex, f"{code}.codes", [])
            codes = getStockCjsdScores(date, codes)
            record[f"cjsd_{i+1}"] = {
                "score": records[i]["cjsd_score"],
                "code": records[i]["code"],
                "name": name,
                "codes": pydash.chain(codes).take(5)
                .map(
                    lambda r: {
                        "code": fq_util_code_append_market_code(r["code"]),
                        "name": r["name"],
                        "cjsd_score": r["cjsd_score"],
                    }
                )
                .value(),
            }
        result.append(record)
    return result


if __name__ == "__main__":
    calcCjsdScoreAll()

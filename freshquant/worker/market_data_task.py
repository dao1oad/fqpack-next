import pandas as pd
from pymongo import UpdateOne
from datetime import datetime
from freshquant.database.mongodb import DBfreshquant
from freshquant.database.redis import redis_db
from freshquant.worker.queue import huey
from QUANTAXIS.QAUtil.QADate import QA_util_time_stamp
from freshquant.data.stock import fq_data_stock_resample_60min
from freshquant.config import cfg

@huey.task()
def save_hq_stock_realtime(records: list, collection: str = "stock_realtime"):
    # 基础验证
    if not isinstance(records, list) or len(records) == 0:
        return
    
    # 验证必要字段
    required_fields = {"datetime", "code", "frequence"}
    if not all(all(field in record for field in required_fields) for record in records):
        raise ValueError("Missing required fields in records")

    try:
        code = records[0]["code"]
        frequence = records[0]["frequence"]
        
        # 从 MongoDB 中获取最后11条记录（多取一条以确保能获取到重叠的10条）
        last_records = list(DBfreshquant[collection].find(
            {"code": code, "frequence": frequence},
            sort=[("datetime", -1)]
        ).limit(10))
        if last_records and len(last_records) > 0:
            # 获取第11条记录的时间（如果不足11条，则取最后一条）
            cutoff_datetime = last_records[-1]["datetime"]
            # 保留所有新数据和重叠的数据
            records = [record for record in records if record["datetime"] >= cutoff_datetime]
        if len(records) == 0:
            return

        # 批量更新 MongoDB
        batch = [
            UpdateOne(
                {
                    "datetime": record["datetime"],
                    "code": code,
                    "frequence": frequence,
                },
                {"$set": record},
                upsert=True,
            )
            for record in records
        ]
        
        # 使用 ordered=False 提高性能
        DBfreshquant[collection].bulk_write(batch, ordered=False)
            
    except Exception as e:
        # 添加错误处理，可以根据需要添加日志记录
        raise Exception(f"Error saving stock realtime data: {str(e)}")

@huey.task()
def process_hq_stock_realtime(df: pd.DataFrame, collection: str = "stock_realtime"):
    # 这里进来的是一分钟的数据
    if len(df) == 0:
        return
    source = df["source"][0]
    code = df["code"][0]
    df['time_stamp'] = df.index.to_series().apply(lambda v: QA_util_time_stamp(v))
    df["date_stamp"] = df.index.to_series().apply(
        lambda dt: QA_util_time_stamp(
            datetime(year=dt.year, month=dt.month, day=dt.day)
        )
    )
    save_hq_stock_realtime(df.reset_index().to_dict(orient="records"), collection)

    # 合成5分钟的数据
    df = (
        df.resample('5T', closed='right', label='right').agg(cfg.OHLC).dropna(how='any')
    )
    df["code"] = code
    df["frequence"] = "5min"
    df["source"] = source
    df['time_stamp'] = df.index.to_series().apply(lambda v: QA_util_time_stamp(v))
    df["date_stamp"] = df.index.to_series().apply(
        lambda dt: QA_util_time_stamp(
            datetime(year=dt.year, month=dt.month, day=dt.day)
        )
    )
    if len(df) > 1:
        save_hq_stock_realtime(df[1:].reset_index().to_dict(orient="records"), collection)

    # 合成15分钟的数据
    df = (
        df.resample('15T', closed='right', label='right')
        .agg(cfg.OHLC)
        .dropna(how='any')
    )
    df["code"] = code
    df["frequence"] = "15min"
    df["source"] = source
    df['time_stamp'] = df.index.to_series().apply(lambda v: QA_util_time_stamp(v))
    df["date_stamp"] = df.index.to_series().apply(
        lambda dt: QA_util_time_stamp(
            datetime(year=dt.year, month=dt.month, day=dt.day)
        )
    )
    if len(df) > 1:
        save_hq_stock_realtime(df[1:].reset_index().to_dict(orient="records"), collection)

    # 合成30分钟的数据
    df = (
        df.resample('30T', closed='right', label='right')
        .agg(cfg.OHLC)
        .dropna(how='any')
    )
    df["code"] = code
    df["frequence"] = "30min"
    df["source"] = source
    df['time_stamp'] = df.index.to_series().apply(lambda v: QA_util_time_stamp(v))
    df["date_stamp"] = df.index.to_series().apply(
        lambda dt: QA_util_time_stamp(
            datetime(year=dt.year, month=dt.month, day=dt.day)
        )
    )
    if len(df) > 1:
        save_hq_stock_realtime(df[1:].reset_index().to_dict(orient="records"), collection)

    # 合成60分钟的数据
    df = fq_data_stock_resample_60min(df.reset_index())
    df["code"] = code
    df["frequence"] = "60min"
    df["source"] = source
    df['time_stamp'] = df.index.to_series().apply(lambda v: QA_util_time_stamp(v))
    df["date_stamp"] = df.index.to_series().apply(
        lambda dt: QA_util_time_stamp(
            datetime(year=dt.year, month=dt.month, day=dt.day)
        )
    )
    if len(df) > 1:
        save_hq_stock_realtime(df[1:].reset_index().to_dict(orient="records"), collection)

    # 先合成日线数据再过滤
    df_daily = df.resample('1D', closed='left', label='left').agg(cfg.OHLC).dropna(how='any')
    df_daily["code"] = code
    df_daily["frequence"] = "1d"
    df_daily["source"] = source
    df_daily['time_stamp'] = df_daily.index.to_series().apply(lambda v: QA_util_time_stamp(v))
    df_daily["date_stamp"] = df_daily.index.to_series().apply(
        lambda dt: QA_util_time_stamp(
            datetime(year=dt.year, month=dt.month, day=dt.day)
        )
    )

    # 过滤当前日期的数据（使用时区感知的时间处理）
    current_date = datetime.now().date()
    df_daily = df_daily[df_daily.index.date == current_date]
    if len(df_daily) > 0:
        # 保持与其他周期一致，去掉第一条数据
        save_hq_stock_realtime(df_daily.reset_index().to_dict(orient="records"), collection)

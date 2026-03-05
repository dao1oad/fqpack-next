import codecs
import pendulum
import pydash
from typing import List
from bson import ObjectId
from freshquant.signal.a_stock_common import save_a_stock_pre_pools
from freshquant.db import DBfreshquant
from freshquant.instrument.general import query_instrument_info
import pyperclip


def import_pool(file, category, days, args):
    if file is not None:
        with codecs.open(file, "r", "utf-8") as input_file:
            lines = input_file.readlines()
            codes = (
                pydash.chain(lines)
                .map(lambda line: line.strip())
                .filter_(lambda line: len(line) > 0)
                .map(lambda line: line[-6:])
                .value()
            )
            for code in codes:
                save_a_stock_pre_pools(code, category)
    if args is not None:
        codes = (
            pydash.chain(args)
            .map(lambda line: line.strip())
            .filter_(lambda line: len(line) > 0)
            .map(lambda line: line[-6:])
            .value()
        )
        for code in codes:
            save_a_stock_pre_pools(
                code, category, expire_at=pendulum.now().add(days=days)
            )

def remove(id=None, category=None, codes=None):
    """统一删除方法
    Args:
        id: 记录的唯一标识符
        category: 分类名称
        codes: 股票代码列表
    """
    if id:
        # 根据id删除记录
        DBfreshquant["stock_pre_pools"].delete_one({"_id": ObjectId(id)})
    elif category and codes:
        # 删除指定category中的指定codes
        DBfreshquant["stock_pre_pools"].delete_many({
            "category": category,
            "code": {"$in": codes}
        })
    elif category:
        # 删除整个category
        DBfreshquant["stock_pre_pools"].delete_many({
            "category": category
        })
    elif codes:
        # 从所有category中删除指定codes
        DBfreshquant["stock_pre_pools"].delete_many({
            "code": {"$in": codes}
        })
    else:
        raise ValueError("必须提供 category 或 codes 或 id 参数")

def copy(category: str):
    
    # 根据category筛选记录
    query = {"category": category} if category else {}
    codes = DBfreshquant.stock_pre_pools.distinct("code", query)
    
    if not codes:
        return "没有找到任何股票代码"
    
    # 转换为字符串并用逗号分隔
    code_str = "\n".join(codes)
    
    # 复制到剪贴板
    pyperclip.copy(code_str)
    return codes

def save_a_stock_pre_pool(
    codes: List[str],
    category: str="",
    stop_loss_price: float=None,
    expire_at=pendulum.now().add(days=89),
    append_mode: bool=True,
    **extra_fields
):
    """更新指定category的股票池，使其与传入的codes列表一致
    
    Args:
        codes: 股票代码列表
        category: 分类名称
        stop_loss_price: 止损价格
        expire_at: 过期时间
        append_mode: 是否使用追加模式更新，True为追加模式(不删除已有但不在列表中的股票)，False为覆盖模式
        **extra_fields: 额外字段
    """
    dt_now = pendulum.now()
    expire_at = pendulum.datetime(expire_at.year, expire_at.month, expire_at.day, tz=pendulum.now().timezone)
    
    # 如果不是追加模式，则删除数据库中存在但不在传入列表中的股票代码
    if not append_mode:
        DBfreshquant.stock_pre_pools.delete_many({
            "category": category,
            "code": {"$nin": codes}
        })
    
    # 4. 添加或更新传入的股票代码
    for code in codes:
        instrument = query_instrument_info(code)
        if instrument is not None:
            # 初始化 extra 字段
            extra = {}
            # 如果文档存在，获取现有的 extra 字段
            existing_doc = DBfreshquant.stock_pre_pools.find_one({"code": code, "category": category})
            if existing_doc and "extra" in existing_doc:
                extra = existing_doc["extra"]

            # 更新 extra 字段
            extra.update(extra_fields)

            DBfreshquant.stock_pre_pools.find_one_and_update(
                {"code": code, "category": category},
                {
                    "$set": {
                        "stop_loss_price": stop_loss_price,
                        "expire_at": expire_at,
                        "extra": extra  # 更新 extra 字段
                    },
                    "$setOnInsert": {
                        "datetime": dt_now,
                        "name": instrument["name"],
                    }
                },
                upsert=True,
            )

def query_a_stock_pre_pool(
    categories: List[str]=[],
    **query_params
):
    """查询指定categories的股票池，返回符合条件的记录
    Args:
        categories: 分类名称列表
        **query_params: 其他查询参数，如codes等
    """

    if len(categories) > 0:
        query = {"category": {"$in": categories}}
    else:
        query = {}
    query.update(query_params)
    return list(DBfreshquant.stock_pre_pools.find(query).sort("datetime", -1))

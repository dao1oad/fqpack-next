import pydash
import codecs
import pendulum
from freshquant.signal.a_stock_common import save_a_stock_pools
from freshquant.data.astock.holding import get_stock_holding_codes
from freshquant.database.cache import redis_cache
from freshquant.db import DBfreshquant
from bson import ObjectId
import pyperclip


@redis_cache.memoize()
def get_stock_pool_codes():
    records = list(DBfreshquant["stock_pools"].find({}))
    codes = pydash.chain(records).map(lambda record: record.get("code")).uniq().value()
    return codes


@redis_cache.memoize()
def queryMustPoolCodes():
    records = list(
        DBfreshquant["must_pool"].find(
            {"instrument_type": {"$in": ["stock_cn", "etf_cn"]}}
        )
    )
    codes = pydash.chain(records).map(lambda record: record.get("code")).uniq().value()
    return codes


@redis_cache.memoize()
def get_stock_monitor_codes(holding_only=False):
    if holding_only:
        return pydash.chain(get_stock_holding_codes()).uniq().value()
    else:
        return (
            pydash.chain(
                get_stock_holding_codes() + queryMustPoolCodes() + get_stock_pool_codes()
            )
            .uniq()
            .value()
        )

def import_pool(file, category, days, codes):
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
                save_a_stock_pools(code, category)
    if codes is not None:
        codes = (
            pydash.chain(codes)
            .map(lambda line: line.split(','))
            .flatten()
            .map(lambda line: line.strip())
            .filter_(lambda line: len(line) > 0)
            .map(lambda line: line[-6:])
            .value()
        )
        for code in codes:
            save_a_stock_pools(code, category, expire_at=pendulum.now().add(days=days))
            
def remove(id=None, category=None, codes=None):
    """统一删除方法
    Args:
        id: 记录的唯一标识符
        category: 分类名称
        codes: 股票代码列表
    """
    if id:
        # 根据id删除记录
        DBfreshquant["stock_pools"].delete_one({"_id": ObjectId(id)})
    elif category and codes:
        # 删除指定category中的指定codes
        DBfreshquant["stock_pools"].delete_many({
            "category": category,
            "code": {"$in": codes}
        })
    elif category:
        # 删除整个category
        DBfreshquant["stock_pools"].delete_many({
            "category": category
        })
    elif codes:
        # 从所有category中删除指定codes
        DBfreshquant["stock_pools"].delete_many({
            "code": {"$in": codes}
        })
    else:
        raise ValueError("必须提供 category 或 codes 或 id 参数")

def copy(category: str):
    
    # 根据category筛选记录
    query = {"category": category} if category else {}
    codes = DBfreshquant.stock_pools.distinct("code", query)
    
    if not codes:
        return "没有找到任何股票代码"
    
    # 转换为字符串并用逗号分隔
    code_str = "\n".join(codes)
    
    # 复制到剪贴板
    pyperclip.copy(code_str)
    return codes

if __name__ == "__main__":
    print(get_stock_monitor_codes())

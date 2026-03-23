from freshquant.db import DBfreshquant
import datetime
from freshquant.strategy.common import get_trade_amount
from freshquant.instrument.general import query_instrument_info
from bson import ObjectId
import pyperclip

def remove(id=None, category=None, codes=None):
    """统一删除方法
    Args:
        id: 记录的唯一标识符
        category: 分类名称
        codes: 股票代码列表
    """
    if id:
        # 根据id删除记录
        DBfreshquant.must_pool.delete_one({"_id": ObjectId(id)})
    elif category and codes:
        # 删除指定category中的指定codes
        DBfreshquant.must_pool.delete_many({
            "category": category,
            "code": {"$in": codes}
        })
    elif category:
        # 删除整个category
        DBfreshquant.must_pool.delete_many({
            "category": category
        })
    elif codes:
        # 从所有category中删除指定codes
        DBfreshquant.must_pool.delete_many({
            "code": {"$in": codes}
        })
    else:
        raise ValueError("必须提供 category 或 codes 或 id 参数")
    
def import_pool(code: str, category: str, stop_loss_price: float, initial_lot_amount: float = None, lot_amount: float = None, forever: bool = True):
    """保存股票到must_pool集合
    Args:
        code: 股票代码
        lot_amount: 每次买入金额
        category: 分类名称
        stop_loss_price: 止损价格
        initial_lot_amount: 首次买入金额 (可选，默认等于lot_amount)
    """
    
    forever = True

    if lot_amount is None:
        lot_amount = get_trade_amount(code)
    if initial_lot_amount is None:
        initial_lot_amount = lot_amount
    if not all([code, category, stop_loss_price]):
        raise ValueError("code, category, stop_loss_price 参数必须提供")

    # 检查是否已存在相同code和category的记录
    existing = DBfreshquant.must_pool.find_one({
        "code": code
    })

    instrument = query_instrument_info(code)
    
    if existing:
        # 更新现有记录
        DBfreshquant.must_pool.update_one(
            {"_id": existing["_id"]},
            {"$set": {
                "name": instrument["name"],
                "instrument_type": instrument["sec"],
                "initial_lot_amount": initial_lot_amount,
                "lot_amount": lot_amount,
                "stop_loss_price": stop_loss_price,
                "forever": forever,
                "disabled": False,
                "updated_at": datetime.datetime.now()
            }}
        )
    else:
        # 插入新记录
        DBfreshquant.must_pool.insert_one({
            "code": code,
            "name": instrument["name"],
            "instrument_type": instrument["sec"],
            "initial_lot_amount": initial_lot_amount,
            "lot_amount": lot_amount,
            "category": category,
            "stop_loss_price": stop_loss_price,
            "forever": forever,
            "disabled": False,
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now()
        })

def copy(category: str):
    
    # 根据category筛选记录
    query = {"category": category} if category else {}
    codes = DBfreshquant.must_pool.distinct("code", query)
    
    if not codes:
        return "没有找到任何股票代码"
    
    # 转换为字符串并用逗号分隔
    code_str = "\n".join(codes)
    
    # 复制到剪贴板
    pyperclip.copy(code_str)
    return codes

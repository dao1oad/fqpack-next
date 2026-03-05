def translate_account_type(account_type: int) -> str:
    """
    Translate account type code to its corresponding description.
    
    Args:
        account_type (int): The account type code.
        
    Returns:
        str: The translated account type description.
    """
    account_type_mapping = {
        1: "期货",
        2: "股票",
        3: "信用",
        5: "期货期权",
        6: "股票期权",
        7: "沪港通",
        11: "深港通"
    }
    return account_type_mapping.get(account_type, "未知类型")


def translate_order_type(order_type: int) -> str:
    """
    Translate order type code to its corresponding description.

    Args:
        order_type (int): The order type code.

    Returns:
        str: The translated order type description.
    """
    order_type_mapping = {
        23: "买入",
        24: "卖出",
        27: "融资买入",
        28: "融券卖出",
        29: "买券还券",
        30: "直接还券",
        31: "卖券还款",
        32: "直接还款",
        40: "专项融资买入",
        41: "专项融券卖出",
        42: "专项买券还券",
        43: "专项直接还券",
        44: "专项卖券还款",
        45: "专项直接还款"
    }
    return order_type_mapping.get(order_type, "未知类型")


def translate_broker_price_type(price_type: int) -> str:
    """
    Translate price type code to its corresponding description.

    Args:
        price_type (int): The price type code.

    Returns:
        str: The translated price type description.
    """
    price_type_mapping = {
        49: "市价",
        50: "限价",
        51: "最优价",
        52: "配股",
        53: "转托",
        54: "申购",
        55: "回购",
        56: "配售",
        57: "指定",
        58: "转股",
        59: "回售",
        60: "股息",
        68: "深圳配售确认",
        69: "配售放弃",
        70: "无冻质押",
        71: "冻结质押",
        72: "无冻解押",
        73: "解冻解押",
        75: "投票",
        77: "预售要约解除",
        78: "基金设红",
        79: "基金申赎",
        80: "跨市转托",
        81: "ETF申购",
        83: "权证行权",
        84: "对手方最优价格",
        85: "最优五档即时成交剩余转限价",
        86: "本方最优价格",
        87: "即时成交剩余撤销",
        88: "最优五档即时成交剩余撤销",
        89: "全额成交并撤单",
        90: "基金拆合",
        91: "债转股",
        92: "港股通竞价限价",
        93: "港股通增强限价",
        94: "港股通零股限价",
        101: "直接还券",
        107: "担保品划转",
    }
    return price_type_mapping.get(price_type, "未知类型")

from pprint import pprint
from typing import Any, Dict, List

from freshquant.database.mongodb import DBfreshquant


def get_current_positions(account_cookie: str) -> Dict[str, Any]:
    """
    获取策略的当前持仓

    参数:
    account_cookie: 账户标识

    返回:
    Dict[str, Any]: 持仓信息字典，格式为 {"trading_day": "", "positions": []}
    """

    # 从backtest_account collection中查询账户信息
    account_doc = DBfreshquant.backtest_account.find_one(
        {"account_cookie": account_cookie}
    )

    result: Dict[str, Any] = {"trading_day": "", "positions": []}

    if account_doc and "positions" in account_doc:
        # 获取当前交易日
        current_trading_day = account_doc.get("trading_day", "")
        result["trading_day"] = current_trading_day

        # 分析当日交易记录，找出有买入开仓的股票代码
        buy_open_codes: set[str] = set()
        if "trades" in account_doc and current_trading_day:
            for trade_id, trade_data in account_doc["trades"].items():
                # 检查是否为当日交易且为买入开仓 (towards=2 表示BUY_OPEN)
                trade_date = str(trade_data.get("trade_time", ""))[:10]  # 取日期部分
                if (
                    trade_date == current_trading_day
                    and trade_data.get("direction") == "BUY"
                    and trade_data.get("offset") == "OPEN"
                ):
                    buy_open_codes.add(
                        f'{trade_data.get("exchange_id", "")}.{trade_data.get("instrument_id", "")}'
                    )

        for code, pos_data in account_doc["positions"].items():
            # 只处理有多头持仓的股票
            if pos_data.get("volume_long", 0) > 0:
                volume = pos_data["volume_long"]
                cost_price = pos_data.get("position_price_long", 0)
                current_price = pos_data.get("last_price", 0)

                # 计算市值
                market_value = volume * current_price

                # 计算盈亏
                profit_loss = (
                    (current_price - cost_price) * volume if cost_price > 0 else 0
                )

                # 计算盈亏率
                profit_rate = (
                    ((current_price - cost_price) / cost_price * 100)
                    if cost_price > 0
                    else 0
                )

                # 检查当日是否有买入开仓
                has_buy_open_in_trading_day = code in buy_open_codes

                position_info = {
                    'code': code,
                    'instrument_id': pos_data.get('instrument_id', ''),
                    'volume': volume,
                    'cost_price': cost_price,
                    'current_price': current_price,
                    'market_value': market_value,
                    'profit_loss': profit_loss,
                    'profit_rate': profit_rate,
                    'has_buy_open_in_trading_day': has_buy_open_in_trading_day,
                }
                result["positions"].append(position_info)

    return result


def get_a_certain_day_positions(account_cookie: str, date: str) -> Dict[str, Any]:
    """
    获取策略在某一天的持仓情况

    参数:
    account_cookie: 账户标识
    date: 查询日期，格式为 'YYYY-MM-DD'

    返回:
    Dict[str, Any]: 持仓信息字典，格式为 {"trading_day": "", "positions": []}
    """

    # 从backtest_account_his collection中查询指定日期的账户历史信息
    account_doc = DBfreshquant.backtest_account_his.find_one(
        {"account_cookie": account_cookie, "trading_day": date}
    )

    result: Dict[str, Any] = {"trading_day": "", "positions": []}

    if account_doc and "positions" in account_doc:
        # 获取交易日
        trading_day = account_doc.get("trading_day", "")
        result["trading_day"] = trading_day

        # 分析当日交易记录，找出有买入开仓的股票代码
        buy_open_codes: set[str] = set()
        if "trades" in account_doc and trading_day:
            for trade_id, trade_data in account_doc["trades"].items():
                # 检查是否为当日交易且为买入开仓
                trade_date = str(trade_data.get("trade_time", ""))[:10]  # 取日期部分
                if (
                    trade_date == trading_day
                    and trade_data.get("direction") == "BUY"
                    and trade_data.get("offset") == "OPEN"
                ):
                    buy_open_codes.add(
                        f'{trade_data.get("exchange_id", "")}.{trade_data.get("instrument_id", "")}'
                    )

        for code, pos_data in account_doc["positions"].items():
            # 只处理有多头持仓的股票
            if pos_data.get("volume_long", 0) > 0:
                volume = pos_data["volume_long"]
                cost_price = pos_data.get("position_price_long", 0)
                current_price = pos_data.get("last_price", 0)

                # 计算市值
                market_value = volume * current_price

                # 计算盈亏
                profit_loss = (
                    (current_price - cost_price) * volume if cost_price > 0 else 0
                )

                # 计算盈亏率
                profit_rate = (
                    ((current_price - cost_price) / cost_price * 100)
                    if cost_price > 0
                    else 0
                )

                # 检查当日是否有买入开仓
                has_buy_open_in_trading_day = code in buy_open_codes

                position_info = {
                    'code': code,
                    'instrument_id': pos_data.get('instrument_id', ''),
                    'volume': volume,
                    'cost_price': cost_price,
                    'current_price': current_price,
                    'market_value': market_value,
                    'profit_loss': profit_loss,
                    'profit_rate': profit_rate,
                    'has_buy_open_in_trading_day': has_buy_open_in_trading_day,
                }
                result["positions"].append(position_info)

    return result


def get_a_certain_day_new_positions(account_cookie: str, date: str) -> Dict[str, Any]:
    """
    获取策略在某一天的新开仓持仓情况（只返回当日有买入开仓的持仓）

    参数:
    account_cookie: 账户标识
    date: 查询日期，格式为 'YYYY-MM-DD'

    返回:
    Dict[str, Any]: 新开仓持仓信息字典，格式为 {"trading_day": "", "positions": []}，但只包含has_buy_open_in_trading_day为True的持仓
    """

    # 调用get_a_certain_day_positions获取所有持仓
    all_positions_result = get_a_certain_day_positions(account_cookie, date)

    # 过滤出当日有买入开仓的持仓
    new_positions: List[Dict[str, Any]] = [
        position_data
        for position_data in all_positions_result["positions"]
        if position_data.get('has_buy_open_in_trading_day', False)
    ]

    return {
        "trading_day": all_positions_result["trading_day"],
        "positions": new_positions,
    }


if __name__ == "__main__":
    account_cookie = "五连阳动量跟随策略"
    # positions = get_current_positions(account_cookie)
    # positions = get_a_certain_day_positions(account_cookie, '2025-10-29')
    positions = get_a_certain_day_new_positions(account_cookie, '2025-10-29')
    pprint(positions)

import traceback
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from rich.console import Console
from rich.table import Table

from freshquant.data.trade_date_hist import (
    get_trade_dates_between,
    tool_trade_date_last,
)
from freshquant.database.mongodb import DBfreshquant
from freshquant.sim.analyze.statistics_calculator import StatisticsCalculator
import pendulum
from loguru import logger


class StrategyAnalyzer:
    """策略分析器，集成数据访问和统计分析功能"""

    def __init__(self, account_cookie: str, days_list: Optional[List[int]] = None):
        """
        初始化策略分析器，使用freshquant项目的数据库连接，并绑定策略账户标识
        """
        self.db = DBfreshquant
        self.account_cookie = account_cookie
        self.days_list = days_list or [7, 14, 30, 90, 360]

    def get_trades_from_qifi_records(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[Dict]:
        """
        从QIFI账户记录中获取交易数据

        参数:
        account_cookie: 策略账户标识（对应设计文档中的account_cookie）
        start_date: 开始日期
        end_date: 结束日期

        返回:
        List[Dict]: 标准化的交易记录列表
        """
        query: Dict[str, Any] = {"account_cookie": self.account_cookie}

        # 添加日期过滤
        if start_date or end_date:
            date_query = {}
            if start_date:
                date_query["$gte"] = start_date.strftime('%Y-%m-%d')
            if end_date:
                date_query["$lte"] = end_date.strftime('%Y-%m-%d')
            query["trading_day"] = date_query

        # 查询QIFI记录
        qifi_records = list(
            self.db.backtest_account_his.find(query).sort("trading_day", 1)
        )
        last_trade_date = tool_trade_date_last()
        trades_list = []
        for record in qifi_records:
            trades_dict = record.get("trades", {})
            # 提取每笔交易
            for trade_id, trade_info in trades_dict.items():
                trade_time_str = trade_info.get('trade_time', '')

                # 过滤掉 last_trade_date 当天及之后的订单
                if trade_time_str and last_trade_date:
                    try:
                        # 处理不同的时间格式
                        if len(trade_time_str) >= 10:
                            trade_date_str = trade_time_str[
                                :10
                            ]  # 提取日期部分 'YYYY-MM-DD'
                            trade_date = datetime.strptime(
                                trade_date_str, '%Y-%m-%d'
                            ).date()

                            # 如果交易日期大于等于最后交易日，则跳过
                            if trade_date >= last_trade_date:
                                continue
                    except (ValueError, TypeError):
                        traceback.print_exc()

                trade_record = {
                    'seqno': trade_info.get('seqno'),
                    'trade_id': trade_id,
                    'instrument_id': trade_info.get('instrument_id', ''),
                    'order_id': trade_info.get('order_id', ''),
                    'direction': trade_info.get('direction', ''),
                    'offset': trade_info.get('offset', ''),
                    'volume': trade_info.get('volume', 0),
                    'price': trade_info.get('price', 0.0),
                    'trade_time': trade_time_str,
                    'commission': trade_info.get('commission', 0.0),
                }
                trades_list.append(trade_record)

        return trades_list

    def save_statistics(
        self,
        calculation_date: datetime,
        trading_day: str,
        statistics: Dict[str, Dict[str, Any]],
    ):
        """
        保存统计结果到数据库

        参数:
        account_cookie: 策略账户标识
        calculation_date: 计算日期
        trading_day: 交易日
        statistics: 统计结果字典
        """
        document = {
            "account_cookie": self.account_cookie,
            "calculation_date": calculation_date,
            "trading_day": trading_day,
            "statistics": statistics,
            "updated_at": datetime.utcnow(),
        }
        # print("==========")
        # print(document)
        # 使用 upsert 避免重复文档
        self.db.backtest_statistics.replace_one(
            {"account_cookie": self.account_cookie, "trading_day": trading_day},
            document,
            upsert=True,
        )

    def get_statistics(
        self,
        days: Optional[int] = None,
        trading_day: Optional[str] = None,
    ) -> Dict:
        """
        从数据库获取统计结果

        参数:
        account_cookie: 策略账户标识
        days: 可选，指定天数
        trading_day: 可选，指定交易日

        返回:
        统计结果字典
        """
        query = {"account_cookie": self.account_cookie}
        if trading_day:
            query["trading_day"] = trading_day

        # 获取最新的统计记录
        document = self.db.backtest_statistics.find_one(
            query, sort=[("trading_day", -1)]
        )
        if not document:
            return {}

        if days is None:
            return document.get("statistics", {})
        else:
            return document.get("statistics", {}).get(str(days), {})

    def analyze_strategy(self):
        query = {"account_cookie": self.account_cookie}
        document = self.db.backtest_statistics.find_one(
            query, sort=[("trading_day", -1)]
        )
        if not document:
            start_date = pendulum.now().subtract(days=360).format('YYYY-MM-DD')
        else:
            start_date = document.get("trading_day")
        _now = pendulum.now('Asia/Shanghai')
        end_date = (
            _now.format('YYYY-MM-DD')
            if _now.hour >= 16
            else _now.subtract(days=1).format('YYYY-MM-DD')
        )
        all_trade_dates = get_trade_dates_between(start_date, end_date)
        trading_day_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        trade_dates = [date for date in all_trade_dates if date != trading_day_date]
        last_stats = None
        for trade_date in trade_dates:
            logger.info(f"Processing account: {self.account_cookie}, date: {trade_date.strftime('%Y-%m-%d')}")
            stats = self.analyze_strategy_day(trade_date.strftime('%Y-%m-%d'))
            if stats:
                last_stats = stats
            else:
                break
        return last_stats

    def analyze_strategy_day(
        self,
        analyze_day: Optional[Union[str, datetime]] = None,
    ) -> Optional[Dict[int, Dict[str, Any]]]:
        stats: Dict[int, Dict[str, Any]] = {}
        if analyze_day:
            if isinstance(analyze_day, str):
                end_date = datetime.strptime(analyze_day, '%Y-%m-%d')
            else:
                end_date = analyze_day
        else:
            end_date = datetime.now()
        # 如果这天没有回测记录就要停止统计
        doc = self.db.backtest_account_his.find_one(
            {
                "account_cookie": self.account_cookie,
                "trading_day": end_date.strftime('%Y-%m-%d'),
            }
        )
        if not doc:
            return None
        # 对每个时间窗口分别处理
        for days in self.days_list:
            # 获取该时间区间内的交易数据
            start_date = end_date - timedelta(days=days)
            trades = self.get_trades_from_qifi_records(start_date, end_date)

            if not trades:
                stats[days] = {}
                continue

            # 只计算这个时间区间内交易的盈亏
            trades_with_pnl = StatisticsCalculator.calculate_trade_pnl(trades)

            # 计算该时间区间的统计结果
            period_stats = StatisticsCalculator.calculate_period_stats(trades_with_pnl)
            stats[days] = period_stats

        # 获取计算日期（与分析截止日保持一致）
        calculation_date = end_date
        trading_day = end_date.strftime('%Y-%m-%d')

        # 保存统计结果
        formatted_stats = {str(days): stats.get(days, {}) for days in self.days_list}
        self.save_statistics(calculation_date, trading_day, formatted_stats)

        return stats

    def get_strategy_history(self, days: Optional[int] = None) -> List[Dict]:
        """
        获取策略历史统计结果

        参数:
        account_cookie: 策略账户标识
        days: 可选，指定天数

        返回:
        历史统计结果列表
        """
        query = {"account_cookie": self.account_cookie}
        history = list(self.db.backtest_statistics.find(query).sort("trading_day", -1))

        if days is not None:
            return [
                {
                    "calculation_date": doc["calculation_date"],
                    "trading_day": doc["trading_day"],
                    "stats": doc["statistics"].get(str(days), {}),
                }
                for doc in history
                if str(days) in doc["statistics"]
            ]

        return [
            {
                "calculation_date": doc["calculation_date"],
                "trading_day": doc["trading_day"],
                "stats": doc["statistics"],
            }
            for doc in history
        ]

    def close(self):
        """关闭数据库连接（使用共享连接，无需手动关闭）"""
        pass


if __name__ == "__main__":
    account_cookie = "五连阳动量跟随策略"
    analyzer = StrategyAnalyzer(account_cookie)
    stats = analyzer.analyze_strategy()
    print(stats)

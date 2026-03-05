import traceback
from typing import Any, Dict, List

from freshquant.data.stock import fq_data_stock_fetch_day


class StatisticsCalculator:
    """计算交易策略的统计指标"""

    @staticmethod
    def calculate_trade_pnl(trades: List[Dict]) -> List[Dict]:
        """
        将买入卖出记录按先进先出方式配对成交易记录

        参数:
        trades: 交易记录列表，包含字段：instrument_id, direction, volume, price, trade_time, commission

        返回:
        配对后的交易记录列表，每条记录包含：
        - instrument_id: 股票代码
        - volume: 交易数量
        - buy_price: 买入价格
        - sell_price: 卖出价格（未完成交易为None）
        - buy_time: 买入时间
        - sell_time: 卖出时间（未完成交易为None）
        - pnl: 盈亏（未完成交易为None）
        - commission: 总手续费
        - status: 'completed' 或 'pending'
        """
        # 按股票代码和时间排序
        trades_sorted = sorted(
            trades, key=lambda x: (x['instrument_id'], x['trade_time'])
        )

        # 按股票分组处理
        positions: dict[str, list] = {}  # 记录每个股票的买入队列
        completed_trades: List[Dict] = []  # 完成的交易记录

        return StatisticsCalculator._process_trades_fifo(
            trades_sorted, positions, completed_trades
        )

    @staticmethod
    def _process_trades_fifo(trades_sorted, positions, completed_trades):
        """处理交易记录的FIFO逻辑"""
        for trade in trades_sorted:
            instrument_id = trade['instrument_id']
            direction = trade['direction']
            volume = trade['volume']
            price = trade['price']
            trade_time = trade['trade_time']
            commission = trade.get('commission', 0)

            if instrument_id not in positions:
                positions[instrument_id] = []

            buy_queue = positions[instrument_id]

            if direction == 'BUY':
                buy_queue.append(
                    {
                        'volume': volume,
                        'price': price,
                        'time': trade_time,
                        'commission': commission,
                    }
                )
            elif direction == 'SELL':
                StatisticsCalculator._process_sell_order(
                    buy_queue,
                    volume,
                    price,
                    trade_time,
                    commission,
                    instrument_id,
                    completed_trades,
                )

        # 处理未完成的交易，使用最新收盘价计算pnl
        for instrument_id, buy_queue in positions.items():
            # 获取最新收盘价
            try:
                latest_data = fq_data_stock_fetch_day(instrument_id)

                if latest_data is not None and len(latest_data) > 0:
                    latest_close_price = latest_data.iloc[-1]['close']
                else:
                    latest_close_price = None
            except Exception:
                traceback.print_exc()
                latest_close_price = None
            for buy_record in buy_queue:
                # 计算基于最新收盘价的pnl
                pnl = None
                if latest_close_price is not None:
                    pnl = (
                        buy_record['volume']
                        * (latest_close_price - buy_record['price'])
                        - buy_record['commission']
                    )

                completed_trades.append(
                    {
                        'instrument_id': instrument_id,
                        'volume': buy_record['volume'],
                        'buy_price': buy_record['price'],
                        'sell_price': latest_close_price,
                        'buy_time': buy_record['time'],
                        'sell_time': None,
                        'pnl': pnl,
                        'commission': buy_record['commission'],
                        'status': 'pending',
                    }
                )
        return completed_trades

    @staticmethod
    def _process_sell_order(
        buy_queue,
        sell_volume,
        sell_price,
        sell_time,
        sell_commission,
        instrument_id,
        completed_trades,
    ):
        """处理卖出订单"""
        if not buy_queue:
            return

        sell_volume_remaining = sell_volume

        while sell_volume_remaining > 0 and buy_queue:
            buy_record = buy_queue[0]
            buy_volume = buy_record['volume']
            buy_price = buy_record['price']
            buy_time = buy_record['time']
            buy_commission = buy_record['commission']

            if sell_volume_remaining >= buy_volume:
                trade_volume = buy_volume
                sell_volume_remaining -= buy_volume
                buy_queue.pop(0)
            else:
                trade_volume = sell_volume_remaining
                buy_record['volume'] -= sell_volume_remaining
                buy_record['commission'] = buy_commission * (
                    buy_record['volume'] / buy_volume
                )
                buy_commission = buy_commission * (trade_volume / buy_volume)
                sell_volume_remaining = 0

            pnl = (
                trade_volume * (sell_price - buy_price)
                - buy_commission
                - (sell_commission * trade_volume / sell_volume)
            )

            completed_trades.append(
                {
                    'instrument_id': instrument_id,
                    'volume': trade_volume,
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'buy_time': buy_time,
                    'sell_time': sell_time,
                    'pnl': pnl,
                    'commission': buy_commission
                    + (sell_commission * trade_volume / sell_volume),
                    'status': 'completed',
                }
            )

    @staticmethod
    def calculate_period_stats(trades: List[Dict]) -> Dict[str, Any]:
        """
        计算指定时间窗口的统计指标

        参数:
        trades: 已经按时间区间筛选过的交易记录列表（包含pnl）

        返回:
        统计指标字典
        """
        if not trades:
            return {}

        # 直接使用传入的交易记录，不再进行时间过滤
        period_trades = [t for t in trades if t.get('pnl') is not None]

        if not period_trades:
            return {}

        # 计算基本统计量
        total_trades = len(period_trades)
        winning_trades = len([t for t in period_trades if t['pnl'] > 0])
        losing_trades = len([t for t in period_trades if t['pnl'] < 0])
        break_even_trades = total_trades - winning_trades - losing_trades

        # 计算金额相关指标
        total_profit = sum(t['pnl'] for t in period_trades if t['pnl'] > 0)
        total_loss = abs(sum(t['pnl'] for t in period_trades if t['pnl'] < 0))
        total_pnl = sum(t['pnl'] for t in period_trades)
        total_commission = sum(t['commission'] for t in period_trades)
        total_buy_amount = sum(t['buy_price'] * t['volume'] for t in period_trades)

        # 计算比率指标
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        profit_loss_ratio = total_profit / total_loss if total_loss > 0 else 999.99
        average_win = total_profit / winning_trades if winning_trades > 0 else 0
        average_loss = total_loss / losing_trades if losing_trades > 0 else 0
        pnl_ratio = (total_pnl / total_buy_amount * 100) if total_buy_amount > 0 else 0

        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "break_even_trades": break_even_trades,
            "win_rate": win_rate,
            "total_profit": total_profit,
            "total_loss": total_loss,
            "total_pnl": total_pnl,
            "total_commission": total_commission,
            "profit_loss_ratio": profit_loss_ratio,
            "average_win": average_win,
            "average_loss": average_loss,
            "total_buy_amount": total_buy_amount,
            "pnl_ratio": pnl_ratio,
        }

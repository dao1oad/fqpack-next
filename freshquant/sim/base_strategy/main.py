import hashlib
import math
import traceback
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd
import pendulum
import talib
import ulid
from QUANTAXIS.QAMarket.QAOrder import ORDER_DIRECTION

from freshquant.data.trade_date_hist import get_trade_dates_between
from freshquant.quantaxis.qifi.qifiaccount import QIFI_Account
from freshquant.sim.base_strategy.input_data_models import InputDataModel
from freshquant.sim.base_strategy.input_param_models import InputParamModel


class BaseStrategy(ABC):
    """
    交易策略基类

    提供通用的账户管理、订单执行、技术指标计算等功能，
    可作为各种具体策略的父类，实现代码复用。
    """

    def __init__(
        self,
        strategy_name,
        strategy_id,
        stock_pool_codes: List[str] = [],
        init_cash: int = 1000000,
        lot_size: int = 3000,
        nodatabase: bool = True,
        input_data_model: Optional[InputDataModel] = None,
        input_param_model: Optional[InputParamModel] = None,
    ):
        """
        初始化策略

        参数:
        strategy_name: 策略名称
        strategy_id: 策略ID
        stock_pool_codes: 股票池代码列表
        init_cash: 初始资金
        lot_size: 每次买入金额限制
        nodatabase: 是否使用数据库
        input_data_model: 输入数据模型，定义策略所需的数据类型
        input_param_model: 输入参数模型，定义策略运行参数
        """
        # 检查必须参数
        if not strategy_name or not isinstance(strategy_name, str):
            raise ValueError("strategy_name必须是非空字符串")
        if not strategy_id or not isinstance(strategy_id, str):
            raise ValueError("strategy_id必须是非空字符串")

        self.init_cash = init_cash
        self.lot_size = lot_size
        self.strategy_name = strategy_name
        self.min_data_length = 5  # 默认至少需要5根K线，子类可以覆盖
        self.stock_pool_codes = stock_pool_codes

        # 设置输入模型
        self.input_data_model = (
            input_data_model if input_data_model else InputDataModel()
        )
        self.input_param_model = (
            input_param_model if input_param_model else InputParamModel()
        )

        # QIFI账户将在run_strategy中初始化
        self.acc = None
        self.strategy_id = strategy_id
        self.nodatabase = nodatabase

        # 创建QIFI账户
        self.acc = QIFI_Account(
            self.strategy_name,
            self.strategy_id,
            nodatabase=self.nodatabase,
            portfolioname=self.strategy_name,
            init_cash=self.init_cash,
        )
        self.acc.initial()

    @staticmethod
    def generate_strategy_id(strategy_name: str) -> str:
        """
        根据策略名称生成策略ID（使用MD5哈希）

        参数:
        strategy_name: 策略名称

        返回:
        str: 策略ID（MD5哈希值）
        """
        return hashlib.md5(strategy_name.encode('utf-8')).hexdigest()

    # 账户管理方法
    def get_current_positions(self):
        """
        获取策略的当前持仓

        返回:
        dict: 持仓信息字典，格式为 {股票代码: {'volume': 持仓数量, 'cost_price': 成本价, 'current_price': 当前价}}
        """
        positions = {}

        if self.acc.positions:
            for code, pos in self.acc.positions.items():
                if pos.volume_long > 0:
                    positions[code] = {
                        'volume': pos.volume_long,
                        'cost_price': pos.position_price_long,
                        'current_price': pos.last_price,
                        'market_value': pos.volume_long * pos.last_price,
                        'profit_loss': (pos.last_price - pos.position_price_long)
                        * pos.volume_long,
                        'profit_rate': (
                            (
                                (pos.last_price - pos.position_price_long)
                                / pos.position_price_long
                                * 100
                            )
                            if pos.position_price_long > 0
                            else 0
                        ),
                    }

        return positions

    def get_current_trading_day(self):
        """
        获取当前交易日

        返回:
        str: 当前交易日，格式 'YYYY-MM-DD'
        """
        message = self.acc.account_col.find_one({"account_cookie": self.acc.user_id})
        if message:
            return message.get("trading_day", "")
        return ""

    def print_summary(self):
        """打印交易总结"""
        print(
            f"\n=== {self.strategy_name}{self.get_current_trading_day()}当日交易完成 ==="
        )
        print(f"账户资金: {self.acc.init_cash:,.2f}")
        print(f"当前资产: {self.acc.balance:,.2f}")
        print(f"可用资金: {self.acc.available:,.2f}")

        # 显示当前持仓
        positions = self.get_current_positions()
        if positions:
            print(f"\n当前持仓（{self.get_current_trading_day()}）:")
            for code, pos_info in positions.items():
                print(
                    f"  {code}: {pos_info['volume']}股, "
                    f"成本价: {pos_info['cost_price']:.2f}, "
                    f"当前价: {pos_info['current_price']:.2f}, "
                    f"盈亏: {pos_info['profit_loss']:.2f} ({pos_info['profit_rate']:.2f}%)"
                )
        else:
            print("当前无持仓")

    # 交易执行方法
    def _execute_buy_order(self, code, dt, price, quantity=None, market_data=None):
        """
        执行买入订单

        参数:
        code: 股票代码
        dt: 交易日期时间
        price: 买入价格
        quantity: 买入数量 (可选). 如果不提供，则根据lot_size计算.
        market_data: 市场数据字典（可选），格式为 {'day': DataFrame, 'week': DataFrame, ...}
        """
        if quantity is None:
            available_cash = self.acc.available
            if available_cash < self.lot_size:
                return False
            quantity = self.calculate_buy_quantity(price, available_cash)

        if quantity >= 100:
            orderId = ulid.new().str
            od = self.acc.send_order(
                code=code,
                amount=quantity,
                price=price,
                towards=ORDER_DIRECTION.BUY,
                order_id=orderId,
                datetime=dt,
            )
            if od:
                self.acc.make_deal(od)
                print(f"买入 {code} {quantity}股 @{price:.2f}")
                self.on_deal_callback(code, price, quantity, dt, market_data)
                return True
        return False

    def _execute_sell_order(self, code, dt, price, quantity, market_data=None):
        """
        执行卖出订单

        参数:
        code: 股票代码
        dt: 交易日期时间
        price: 卖出价格
        quantity: 持仓数量
        market_data: 市场数据字典（可选），格式为 {'day': DataFrame, 'week': DataFrame, ...}
        """
        orderId = ulid.new().str
        od = self.acc.send_order(
            code=code,
            amount=quantity,
            price=price,
            towards=ORDER_DIRECTION.SELL_CLOSE,
            order_id=orderId,
            datetime=dt,
        )
        if od:
            self.acc.make_deal(od)
            # 计算当日涨跌幅（如果提供了市场数据）
            if market_data is not None and '1d' in market_data:
                day_data = market_data['1d']
                if len(day_data) > 1:
                    current_idx = len(day_data) - 1
                    prev_close = day_data.iloc[current_idx - 1]['close']
                    profit_rate = (price - prev_close) / prev_close
                    print(
                        f"卖出 {code} {quantity}股 @{price:.2f}, 当日涨跌: {profit_rate*100:.2f}%"
                    )
                else:
                    print(f"卖出 {code} {quantity}股 @{price:.2f}")
            else:
                print(f"卖出 {code} {quantity}股 @{price:.2f}")
            return True
        return False

    def set_volume_long_stop_loss_price(self, code, volume_long_stop_loss_price):
        """设置持仓止损价"""
        pos = self.acc.get_position(code)
        if pos and pos.volume_long > 0:
            # 在持仓对象的extra字段中存储止损价
            pos.extra['volume_long_stop_loss_price'] = volume_long_stop_loss_price
            print(f"设置 {code} 止损价 {volume_long_stop_loss_price:.2f}")
            self.acc.update_position(pos)

    def set_volume_short_stop_loss_price(self, code, volume_short_stop_loss_price):
        """设置持仓止损价"""
        pos = self.acc.get_position(code)
        if pos and pos.volume_short > 0:
            # 在持仓对象的extra字段中存储止损价
            pos.extra['volume_short_stop_loss_price'] = volume_short_stop_loss_price
            print(f"设置 {code} 止损价 {volume_short_stop_loss_price:.2f}")
            self.acc.update_position(pos)

    def get_volume_long_stop_loss_price(self, code):
        """获取持仓止损价"""
        pos = self.acc.get_position(code)
        if pos and pos.volume_long > 0:
            return pos.extra.get('volume_long_stop_loss_price', None)
        return None

    def get_volume_short_stop_loss_price(self, code):
        """获取持仓止损价"""
        pos = self.acc.get_position(code)
        if pos and pos.volume_short > 0:
            return pos.extra.get('volume_short_stop_loss_price', None)
        return None

    def remove_volume_long_stop_loss_price(self, code):
        """移除止损价（卖出后清理）"""
        pos = self.acc.get_position(code)
        if pos and pos.volume_long > 0:
            del pos.extra['volume_long_stop_loss_price']

    def remove_volume_short_stop_loss_price(self, code):
        """移除止损价（卖出后清理）"""
        pos = self.acc.get_position(code)
        if pos and pos.volume_short > 0:
            del pos.extra['volume_short_stop_loss_price']

    def get_position(self, code):
        """获取持仓信息"""
        return self.acc.get_position(code)

    def update_position(self, pos):
        """更新持仓信息"""
        if pos.volume_long > 0 or pos.volume_short > 0:
            self.acc.update_position(pos)

    def on_deal_callback(self, code, price, volume, dt, market_data):
        """
        处理成交回报

        参数:
        code: 股票代码
        price: 成交价格
        volume: 成交数量
        dt: 成交时间
        market_data: 市场数据字典，格式为 {'day': DataFrame, 'week': DataFrame, ...}
        """
        pass

    def calculate_buy_quantity(self, current_price, available_cash):
        """
        计算买入数量

        参数:
        current_price: 当前价格
        available_cash: 可用资金

        返回:
        quantity: 买入数量（股）
        """
        # 计算买入数量
        quantity = math.floor(self.lot_size / current_price / 100) * 100
        if quantity < 100:
            quantity = 100

        # 确保不超过可用资金
        max_quantity = math.floor(available_cash / current_price / 100) * 100
        quantity = min(quantity, max_quantity)

        return quantity if quantity >= 100 else 0

    # 技术指标计算方法
    def calculate_atr(self, hist_data: pd.DataFrame, period=20):
        """
        使用ta-lib计算ATR (Average True Range)

        参数:
        hist_data: 历史数据
        period: ATR计算周期，默认20天

        返回:
        float: 最新的ATR值
        """
        # 检查数据长度是否足够
        data_length = len(hist_data)
        if data_length == 0:
            return 0

        # 如果数据长度不足period，调整period为可用数据长度
        adjusted_period = min(period, data_length - 1)

        # 使用ta-lib计算ATR
        atr = talib.ATR(
            hist_data['high'].values,
            hist_data['low'].values,
            hist_data['close'].values,
            timeperiod=adjusted_period,
        )
        # 返回最新的有效ATR值
        last_valid_idx = -1
        while last_valid_idx >= -data_length and pd.isna(atr[last_valid_idx]):
            last_valid_idx -= 1

        return (
            atr[last_valid_idx]
            if last_valid_idx >= -data_length and not pd.isna(atr[last_valid_idx])
            else 0
        )

    def process_stock(self, code, today):
        """
        处理单只股票的交易逻辑

        参数:
        code: 股票代码
        today: 交易日期
        """
        try:
            # 加载市场数据
            parsed_date = self._parse_date(today)
            market_data = self.input_data_model.load_data(code, parsed_date)
            if not market_data:
                return

            # 获取任意可用的行情数据来获取当前价格
            # 优先级: 1m > 3m > 5m > 15m > 30m > 60m > 90m > 120m > 180m > 1d > 1w
            timeframes = [
                '1m',
                '3m',
                '5m',
                '15m',
                '30m',
                '60m',
                '90m',
                '120m',
                '180m',
                '1d',
                '1w',
            ]
            current_price = None
            for tf in timeframes:
                if (
                    tf in market_data
                    and market_data[tf] is not None
                    and len(market_data[tf]) > 0
                ):
                    current_price = market_data[tf]['close'].iloc[-1]
                    break

            # 更新账户价格
            if current_price:
                self.acc.on_price_change(code, current_price, today)

            # 检查是否已有持仓
            pos = self.acc.get_position(code)

            if pos.volume_long > 0:
                # 已有持仓，检查卖出条件
                if self.should_sell(pos, market_data):
                    self._execute_sell_order(
                        code,
                        today + ' 15:00:00',
                        current_price,
                        pos.volume_long,
                        market_data,
                    )
            else:
                # 无持仓，检查买入条件
                if self.should_buy(pos, market_data):
                    self._execute_buy_order(
                        code,
                        today + ' 15:00:00',
                        current_price,
                        market_data=market_data,
                    )
        except Exception as e:
            print(f"处理股票 {code} 时出错: {e}")
            traceback.print_exc()

    def run_strategy(self):
        """
        运行策略

        参数:
        target_date: 目标日期，默认为当天
        """

        start_date = self.get_current_trading_day() or pendulum.now().subtract(
            days=360
        ).format('YYYY-MM-DD')

        # 获取交易日期
        _now = pendulum.now('Asia/Shanghai')
        end_date = (
            _now.format('YYYY-MM-DD')
            if _now.hour >= 16
            else _now.subtract(days=1).format('YYYY-MM-DD')
        )

        # 获取交易日期列表（不包含trading_day，但包含today）
        all_trade_dates = get_trade_dates_between(start_date, end_date)
        trading_day_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        trade_dates = [date for date in all_trade_dates if date != trading_day_date]


        for trade_date in trade_dates:
            codes = self.input_data_model.load_stock_pool_codes(trade_date)
            print(f"开始{self.strategy_name}模拟交易，日期: {trade_date}")
            print(f"股票池数量: {len(codes)}")
            if len(codes) > 0:
                for code in codes:
                    self.process_stock(code, trade_date.strftime('%Y-%m-%d'))
                # 结算
                self.acc.settle()

                # 输出交易结果
                self.print_summary()

    def _parse_date(self, today):
        """
        解析日期参数为datetime对象

        参数:
        today: 交易日期，支持多种格式:
               - None: 使用当前日期
               - datetime.date 对象
               - datetime.datetime 对象
               - 字符串: 支持 'YYYY-MM-DD', 'YYYY/MM/DD', 'YYYYMMDD' 等格式

        返回:
        datetime: 解析后的日期时间对象
        """
        if today is None:
            return datetime.now()
        elif isinstance(today, datetime):
            return today
        elif isinstance(today, date):
            return datetime.combine(today, datetime.min.time())
        elif isinstance(today, str):
            # 尝试解析多种字符串格式
            today = today.strip()
            formats = [
                '%Y-%m-%d',  # 2023-12-25
                '%Y/%m/%d',  # 2023/12/25
                '%Y%m%d',  # 20231225
                '%m/%d/%Y',  # 12/25/2023
                '%d/%m/%Y',  # 25/12/2023
                '%Y-%m-%d %H:%M:%S',  # 2023-12-25 10:30:00
                '%Y/%m/%d %H:%M:%S',  # 2023/12/25 10:30:00
            ]

            for fmt in formats:
                try:
                    return datetime.strptime(today, fmt)
                except ValueError:
                    continue

            raise ValueError(
                f"无法解析日期格式: {today}. 支持的格式包括: YYYY-MM-DD, YYYY/MM/DD, YYYYMMDD 等"
            )
        else:
            raise TypeError(
                f"today 参数类型不支持: {type(today)}. 支持 None, datetime, date, str 类型"
            )

    # 需要子类实现的抽象方法
    @abstractmethod
    def should_buy(self, pos, market_data: Dict[str, pd.DataFrame]):
        """
        判断是否应该买入（子类必须实现）

        参数:
        pos: 持仓对象
        market_data: 市场数据字典，格式为 {'day': DataFrame, 'week': DataFrame, ...}

        返回:
        bool: 是否应该买入
        """
        pass

    @abstractmethod
    def should_sell(self, pos, market_data: Dict[str, pd.DataFrame]):
        """
        判断是否应该卖出（子类必须实现）

        参数:
        pos: 持仓对象
        market_data: 市场数据字典，格式为 {'day': DataFrame, 'week': DataFrame, ...}

        返回:
        bool: 是否应该卖出
        """
        pass

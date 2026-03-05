import time
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from decimal import Decimal, getcontext
from loguru import logger
from freshquant.market_data.tick_data_buffer import TickDataBuffer
from freshquant.util import datetime_helper
from freshquant.config import cfg


class OneMinuteAggregator:
    """
    1分钟K线数据聚合器

    功能：
    1. 时间窗口管理算法（使用右值时间戳，9:30:00-9:30:59.999的tick合并为9:31的K线）
    2. OHLC计算核心逻辑
    3. 成交量聚合功能
    """

    def __init__(self, tick_buffer: TickDataBuffer):
        """
        初始化1分钟聚合器

        Args:
            tick_buffer: Tick数据缓冲区实例
        """
        self.tick_buffer = tick_buffer

        # 存储每只股票的最后一个合成好的分钟窗口数据
        self.minute_windows: Dict[str, Dict[str, Any]] = defaultdict(self._create_minute_window)

        # 存储每只股票最后处理的tick的score，默认值为当天的9:30
        self.last_processed_tick_scores: Dict[str, int] = defaultdict(self._min_tick_score)

        # 存储聚合完成的1分钟K线数据
        # 使用双层字典结构：股票代码 -> 分钟时间 -> K线数据
        self.kline_data: Dict[str, Dict[datetime, Dict[str, Any]]] = defaultdict(dict)

        # 线程锁，确保线程安全
        self.lock = threading.RLock()

        # 统计信息
        self.stats = {
            'total_ticks_processed': 0,
            'total_klines_generated': 0,
            'total_windows_managed': 0,
            'stock_count': 0
        }

        # 交易时间配置
        self.market_hours = {
            'morning': {'start': (9, 30), 'end': (11, 30)},
            'afternoon': {'start': (13, 0), 'end': (15, 0)}
        }

        logger.info("OneMinuteAggregator初始化完成")
        
    def _min_tick_score(self) -> int:
        """
        返回当天9:30的时间戳作为最小的tick score
        
        Returns:
            float: 当天9:30的时间戳
        """
        today = datetime_helper.now().replace(hour=9, minute=30, second=0, microsecond=0)
        return int(today.timestamp())

    def _create_minute_window(self) -> Dict[str, Any]:
        """
        创建新的分钟窗口数据结构

        Returns:
            Dict: 分钟窗口数据结构
        """
        return {
            'window_start': None,
            'window_end': None,
            'code': None,
            'name': None,
            'ticks': [],
            'open': None,
            'high': None,
            'low': None,
            'close': None,
            'volume': Decimal('0'),
            'amount': Decimal('0'),
            'tick_count': 0,
            'first_tick_time': None,
            'last_tick_time': None
        }

    def process(self, stock_code: str) -> List[Dict[str, Any]]:
        """
        处理单个tick数据，更新分钟窗口

        Args:
            stock_code: 股票代码
            tick_data: tick数据字典

        Returns:
            List[Dict]: 如果完成了一个分钟窗口，返回聚合的K线数据
        """
        kline_results = []
        with self.lock:
            last_processed_tick_score = self.last_processed_tick_scores[stock_code]
            ticks = self.tick_buffer.get_ticks_by_range(stock_code, last_processed_tick_score + 1, last_processed_tick_score + 86400)
            for tick_data in ticks:
                try:
                    # 解析tick时间
                    code = tick_data.get('code')
                    name = tick_data.get('name')
                    tick_time = self._parse_tick_time(tick_data)
                    if not tick_time:
                        continue

                    # 检查是否在交易时间内
                    if not self._is_market_hours(tick_time):
                        continue

                    # 获取或创建分钟窗口
                    window_data = self._get_or_create_minute_window(stock_code, tick_time)
                    minute_window = window_data["minute_window"]
                    if window_data["kline_result"]:
                        kline_result = window_data["kline_result"]
                        kline_result['code'] = code
                        kline_result['name'] = name
                        kline_results.append(kline_result)

                    # 更新分钟窗口数据
                    kline_result = self._update_minute_window(stock_code, minute_window, tick_data, tick_time)
                    if kline_result:
                        kline_result['code'] = code
                        kline_result['name'] = name
                        kline_results.append(kline_result)
                    self.last_processed_tick_scores[stock_code] = tick_data['score']

                    # 更新统计信息
                    self.stats['total_ticks_processed'] += 1
                except (ValueError, TypeError, KeyError) as e:
                    logger.error(f"处理tick数据失败: {stock_code}, 数据类型错误: {e}, tick_data: {tick_data}")
                except Exception as e:
                    logger.error(f"处理tick数据失败: {stock_code}, 未知错误: {e}, tick_data: {tick_data}")
            return kline_results

    def _parse_tick_time(self, tick_data: Dict[str, Any]) -> Optional[datetime]:
        """
        解析tick数据中的时间戳

        Args:
            tick_data: tick数据字典

        Returns:
            Optional[datetime]: 解析后的时间对象
        """
        try:
            date_str = tick_data.get('date', '')
            time_str = tick_data.get('time', '')

            if not date_str or not time_str:
                return None

            # 解析时间格式，假设格式为 "YYYY-MM-DD" 和 "HH:MM:SS"
            datetime_str = f"{date_str} {time_str}"
            return cfg.TZ.localize(datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S"))

        except (ValueError, TypeError) as e:
            logger.error(f"解析tick时间失败: {e}, date_str: {date_str}, time_str: {time_str}")
            return None
        except Exception as e:
            logger.error(f"解析tick时间未知错误: {e}, date_str: {date_str}, time_str: {time_str}")
            return None

    def _is_market_hours(self, tick_time: datetime) -> bool:
        """
        检查是否在交易时间内

        Args:
            tick_time: tick时间

        Returns:
            bool: 是否在交易时间内
        """
        time_obj = tick_time.time()
        current_time = (time_obj.hour, time_obj.minute)

        # 检查上午交易时间
        morning_start = self.market_hours['morning']['start']
        morning_end = self.market_hours['morning']['end']
        if morning_start <= current_time <= morning_end:
            return True

        # 检查下午交易时间
        afternoon_start = self.market_hours['afternoon']['start']
        afternoon_end = self.market_hours['afternoon']['end']
        if afternoon_start <= current_time <= afternoon_end:
            return True

        return False

    def _get_or_create_minute_window(self, stock_code: str, tick_time: datetime) -> Dict[str, Any]:
        """
        获取或创建分钟窗口

        Args:
            stock_code: 股票代码
            tick_time: tick时间

        Returns:
            Dict: 分钟窗口数据
        """
        minute_window = self.minute_windows[stock_code]
        kline_result = None
        # 计算分钟窗口的开始和结束时间
        window_start = tick_time.replace(second=0, microsecond=0)
        window_end = window_start + timedelta(minutes=1)

        # 如果窗口不存在或时间不匹配，创建新窗口
        if (minute_window['window_start'] != window_start or
            minute_window['window_end'] != window_end):

            # 如果存在未完成的窗口，先完成它
            if minute_window['window_start'] is not None and minute_window['tick_count'] > 0:
                kline_result = self._finalize_minute_window(stock_code, minute_window)

            # 创建新窗口
            minute_window.update(self._create_minute_window())
            minute_window['window_start'] = window_start
            minute_window['window_end'] = window_end

            self.stats['total_windows_managed'] += 1

        return {"minute_window": minute_window, "kline_result": kline_result}

    def _update_minute_window(self, stock_code: str, minute_window: Dict[str, Any],
                            tick_data: Dict[str, Any], tick_time: datetime) -> Optional[Dict[str, Any]]:
        """
        更新分钟窗口数据

        Args:
            stock_code: 股票代码
            minute_window: 分钟窗口数据
            tick_data: tick数据
            tick_time: tick时间

        Returns:
            Optional[Dict]: 如果完成了一个分钟窗口，返回聚合的K线数据
        """
        # 添加tick到窗口
        minute_window['ticks'].append(tick_data)
        minute_window['tick_count'] += 1

        # 更新时间信息
        if minute_window['first_tick_time'] is None:
            minute_window['first_tick_time'] = tick_time
        minute_window['last_tick_time'] = tick_time

        # 获取当前价格（临时设置Decimal精度）
        original_prec = getcontext().prec
        getcontext().prec = 10

        try:
            current_price = Decimal(str(tick_data.get('now', 0)))
            volume = Decimal(str(tick_data.get('volume', 0)))
            amount = Decimal(str(tick_data.get('turnover', 0)))
        finally:
            getcontext().prec = original_prec

        # OHLC计算核心逻辑
        if minute_window['open'] is None:
            minute_window['open'] = current_price

        minute_window['close'] = current_price

        if minute_window['high'] is None or current_price > minute_window['high']:
            minute_window['high'] = current_price

        if minute_window['low'] is None or current_price < minute_window['low']:
            minute_window['low'] = current_price

        # 成交量聚合功能
        minute_window['volume'] += volume
        minute_window['amount'] += amount
        return None


    def _finalize_minute_window(self, stock_code: str, minute_window: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        完成分钟窗口，生成K线数据

        Args:
            stock_code: 股票代码
            minute_window: 分钟窗口数据

        Returns:
            Dict: 聚合的K线数据
        """
        try:
            # 基础OHLC数据
            kline_data = {
                'code': stock_code,
                'datetime': minute_window['window_end'],
                'date': minute_window['window_end'].strftime('%Y-%m-%d'),
                'time': minute_window['window_end'].strftime('%H:%M:%S'),
                'open': float(minute_window['open'] or 0),
                'high': float(minute_window['high'] or 0),
                'low': float(minute_window['low'] or 0),
                'close': float(minute_window['close'] or 0),
                'volume': float(minute_window['volume']),
                'amount': float(minute_window['amount']),
                'tick_count': minute_window['tick_count'],
                'first_tick_time': minute_window['first_tick_time'],
                'last_tick_time': minute_window['last_tick_time'],
                'frequence': "1min"
            }


            # 存储K线数据 - 使用分钟时间作为索引进行去重
            kline_datetime = kline_data['datetime']

            # 检查是否已存在相同分钟时间的K线数据
            if kline_datetime in self.kline_data[stock_code]:
                # 更新已存在的K线数据（覆盖处理）
                self.kline_data[stock_code][kline_datetime] = kline_data
            else:
                # 添加新的K线数据
                self.kline_data[stock_code][kline_datetime] = kline_data
                self.stats['total_klines_generated'] += 1

            # 更新统计信息
            self.stats['stock_count'] = len(self.kline_data)

            # 重置分钟窗口
            minute_window.update(self._create_minute_window())

            return kline_data

        except (ValueError, TypeError) as e:
            logger.error(f"完成分钟窗口失败: {stock_code}, 数据类型错误: {e}, minute_window: {minute_window}")
            return None
        except Exception as e:
            logger.error(f"完成分钟窗口失败: {stock_code}, 未知错误: {e}, minute_window: {minute_window}")
            return None


    def aggregate_stale_windows(self) -> List[Dict[str, Any]]:
        """
        聚合过期的分钟窗口

        Returns:
            List[Dict]: 聚合的K线数据列表
        """
        current_time = datetime.now()
        kline_results = []

        try:
            with self.lock:
                for stock_code, minute_window in list(self.minute_windows.items()):
                    # 如果窗口有数据且已过期（超过2分钟没有新数据）
                    if (minute_window['window_start'] is not None and
                        minute_window['tick_count'] > 0 and
                        current_time - minute_window['last_tick_time'] > timedelta(minutes=2)):

                        kline_result = self._finalize_minute_window(stock_code, minute_window)
                        if kline_result:
                            kline_results.append(kline_result)

        except (ValueError, TypeError) as e:
            logger.error(f"聚合过期窗口失败: {e}")
        except Exception as e:
            logger.error(f"聚合过期窗口未知错误: {e}")

        return kline_results

    def cleanup_inactive_windows(self, inactive_minutes: int = 30) -> int:
        """
        清理长时间不活跃的窗口

        Args:
            inactive_minutes: 不活跃时间阈值（分钟）

        Returns:
            int: 清理的窗口数量
        """
        current_time = datetime.now()
        cleaned_count = 0

        try:
            with self.lock:
                for stock_code, minute_window in list(self.minute_windows.items()):
                    # 如果窗口长时间没有数据（超过指定分钟）
                    if (minute_window['window_start'] is not None and
                        minute_window['tick_count'] == 0 and
                        current_time - minute_window['window_start'] > timedelta(minutes=inactive_minutes)):

                        # 清理空窗口
                        del self.minute_windows[stock_code]
                        cleaned_count += 1

        except (ValueError, TypeError) as e:
            logger.error(f"清理不活跃窗口失败: {e}")
        except Exception as e:
            logger.error(f"清理不活跃窗口未知错误: {e}")

        return cleaned_count

    def get_kline_data(self, stock_code: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        获取指定股票的K线数据

        Args:
            stock_code: 股票代码
            limit: 返回数据条数限制

        Returns:
            List[Dict]: K线数据列表
        """
        with self.lock:
            klines_dict = self.kline_data.get(stock_code, {})
            # 按时间排序并转换为列表
            klines_list = sorted(klines_dict.values(), key=lambda x: x['datetime'])
            if limit is None:
                return klines_list.copy()
            else:
                return klines_list[-limit:].copy()

    def get_latest_kline(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        获取指定股票的最新K线数据

        Args:
            stock_code: 股票代码

        Returns:
            Optional[Dict]: 最新K线数据
        """
        with self.lock:
            klines_dict = self.kline_data.get(stock_code, {})
            if not klines_dict:
                return None
            # 获取最新的K线数据（按时间排序的最后一个）
            klines_list = sorted(klines_dict.values(), key=lambda x: x['datetime'])
            return klines_list[-1] if klines_list else None

    def get_all_stock_codes(self) -> List[str]:
        """
        获取所有有K线数据的股票代码

        Returns:
            List[str]: 股票代码列表
        """
        with self.lock:
            return list(self.kline_data.keys())

    def clear_kline_data(self, stock_code: Optional[str] = None) -> int:
        """
        清空K线数据

        Args:
            stock_code: 指定股票代码，None表示清空所有

        Returns:
            int: 清空的数据条数
        """
        with self.lock:
            if stock_code:
                count = len(self.kline_data.get(stock_code, {}))
                del self.kline_data[stock_code]
            else:
                count = sum(len(klines_dict) for klines_dict in self.kline_data.values())
                self.kline_data.clear()

            return count

    def get_stats(self) -> Dict[str, Any]:
        """
        获取聚合器统计信息

        Returns:
            Dict: 统计信息字典
        """
        with self.lock:
            stats = self.stats.copy()
            stats['current_kline_count'] = sum(len(klines_dict) for klines_dict in self.kline_data.values())
            stats['active_windows'] = len([w for w in self.minute_windows.values() if w['tick_count'] > 0])
            return stats


    def __str__(self) -> str:
        """
        字符串表示

        Returns:
            str: 聚合器信息字符串
        """
        stats = self.get_stats()
        return (f"OneMinuteAggregator(股票数量={stats['stock_count']}, "
                f"K线数量={stats['current_kline_count']}, "
                f"活跃窗口={stats['active_windows']}, "
                f"已处理tick={stats['total_ticks_processed']}, "
                f"已生成K线={stats['total_klines_generated']})")



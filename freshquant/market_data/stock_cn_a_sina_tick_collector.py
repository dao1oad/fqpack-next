import re
import signal
import threading
import time
import traceback
from datetime import datetime, timedelta
from time import sleep
from typing import Dict, Any, Optional

import durationpy
import websocket
from loguru import logger

from freshquant.config import cfg
from freshquant.data.astock.pool import get_stock_monitor_codes
from freshquant.data.trade_date_hist import tool_trade_date_seconds_to_start
from freshquant.util.code import fq_util_code_append_market_code, fq_util_code_append_market_code_suffix
from freshquant.market_data.tick_data_buffer import TickDataBuffer
from freshquant.market_data.one_minute_aggregator import OneMinuteAggregator
from freshquant.worker import save_hq_stock_realtime
from freshquant.util import datetime_helper

grep_detail = re.compile(
    r"(\d+)=([^\s,]+?)%s%s" % (r",([\.\d]+)" * 29, r",([-\.\d:]+)" * 2)
)


def validate_and_clean_tick_data(tick_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    数据预处理和清洗逻辑

    Args:
        tick_data: 原始tick数据

    Returns:
        Optional[Dict]: 清洗后的数据，如果数据无效则返回None
    """
    try:
        # 检查必要字段是否存在
        required_fields = ['code', 'name', 'now', 'volume', 'date', 'time']
        for field in required_fields:
            if field not in tick_data or tick_data[field] is None:
                logger.warning(f"Tick数据缺少必要字段: {field}, 数据: {tick_data}")
                return None

        # 价格数据验证和清洗
        price_fields = ['open', 'pre_close', 'now', 'high', 'low', 'buy', 'sell',
                       'bid1', 'bid2', 'bid3', 'bid4', 'bid5',
                       'ask1', 'ask2', 'ask3', 'ask4', 'ask5']

        for field in price_fields:
            if field in tick_data:
                try:
                    value = float(tick_data[field])
                    # 价格不能为负数
                    if value < 0:
                        logger.warning(f"股票 {tick_data['code']} 的 {field} 价格为负数: {value}, 设置为0")
                        tick_data[field] = 0.0
                    # 检查价格是否合理（避免异常值）
                    elif value > 100000:  # 假设单股价格不超过10万
                        logger.warning(f"股票 {tick_data['code']} 的 {field} 价格异常: {value}")
                        return None
                    else:
                        tick_data[field] = value
                except (ValueError, TypeError):
                    logger.warning(f"股票 {tick_data['code']} 的 {field} 价格格式错误: {tick_data[field]}")
                    tick_data[field] = 0.0

        # 成交量数据验证和清洗
        volume_fields = ['turnover', 'bid1_volume', 'bid2_volume', 'bid3_volume',
                        'bid4_volume', 'bid5_volume', 'ask1_volume', 'ask2_volume',
                        'ask3_volume', 'ask4_volume', 'ask5_volume']

        for field in volume_fields:
            if field in tick_data:
                try:
                    value = int(tick_data[field])
                    if value < 0:
                        logger.warning(f"股票 {tick_data['code']} 的 {field} 成交量为负数: {value}, 设置为0")
                        tick_data[field] = 0
                    tick_data[field] = value
                except (ValueError, TypeError):
                    logger.warning(f"股票 {tick_data['code']} 的 {field} 成交量格式错误: {tick_data[field]}")
                    tick_data[field] = 0

        # 时间格式验证和标准化
        try:
            date_str = tick_data['date']
            time_str = tick_data['time']

            # 验证日期格式
            if not re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                logger.warning(f"股票 {tick_data['code']} 日期格式错误: {date_str}")
                return None

            # 验证时间格式
            if not re.match(r'\d{2}:\d{2}:\d{2}', time_str):
                logger.warning(f"股票 {tick_data['code']} 时间格式错误: {time_str}")
                return None

            # 检查时间合理性
            hour, minute, second = map(int, time_str.split(':'))
            if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
                logger.warning(f"股票 {tick_data['code']} 时间值不合理: {time_str}")
                return None

        except Exception as e:
            logger.error(f"股票 {tick_data['code']} 时间处理错误: {e}")
            return None

        # 检查数据一致性
        now_price = tick_data.get('now', 0)
        high_price = tick_data.get('high', 0)
        low_price = tick_data.get('low', 0)

        if now_price > 0:
            if high_price > 0 and now_price > high_price:
                logger.warning(f"股票 {tick_data['code']} 现价 {now_price} 高于最高价 {high_price}, 调整最高价")
                tick_data['high'] = now_price

            if low_price > 0 and now_price < low_price:
                logger.warning(f"股票 {tick_data['code']} 现价 {now_price} 低于最低价 {low_price}, 调整最低价")
                tick_data['low'] = now_price

        # 添加数据接收时间戳
        tick_data['received_at'] = datetime_helper.now().strftime('%Y-%m-%d %H:%M:%S')
        tick_data['processed_at'] = datetime_helper.now().strftime('%Y-%m-%d %H:%M:%S')

        return tick_data

    except Exception as e:
        logger.error(f"清洗tick数据时发生错误: {e}, 数据: {tick_data}")
        logger.error(f"堆栈跟踪信息:\n{traceback.format_exc()}")
        return None


def format_response_data(rep_data, prefix=False):
    """
    格式化响应数据并添加清洗逻辑
    """
    try:
        result = grep_detail.finditer(rep_data)
        stock_dict = dict()

        for stock_match_object in result:
            stock = stock_match_object.groups()

            # 构建原始数据字典
            raw_tick_data = {
                'code': stock[0],
                'name': stock[1],
                'open': float(stock[2]) if stock[2] else 0.0,
                'pre_close': float(stock[3]) if stock[3] else 0.0,
                'now': float(stock[4]) if stock[4] else 0.0,
                'high': float(stock[5]) if stock[5] else 0.0,
                'low': float(stock[6]) if stock[6] else 0.0,
                'buy': float(stock[7]) if stock[7] else 0.0,
                'sell': float(stock[8]) if stock[8] else 0.0,
                'turnover': int(stock[9]) if stock[9] else 0,
                'volume': float(stock[10]) if stock[10] else 0.0,
                'bid1_volume': int(stock[11]) if stock[11] else 0,
                'bid1': float(stock[12]) if stock[12] else 0.0,
                'bid2_volume': int(stock[13]) if stock[13] else 0,
                'bid2': float(stock[14]) if stock[14] else 0.0,
                'bid3_volume': int(stock[15]) if stock[15] else 0,
                'bid3': float(stock[16]) if stock[16] else 0.0,
                'bid4_volume': int(stock[17]) if stock[17] else 0,
                'bid4': float(stock[18]) if stock[18] else 0.0,
                'bid5_volume': int(stock[19]) if stock[19] else 0,
                'bid5': float(stock[20]) if stock[20] else 0.0,
                'ask1_volume': int(stock[21]) if stock[21] else 0,
                'ask1': float(stock[22]) if stock[22] else 0.0,
                'ask2_volume': int(stock[23]) if stock[23] else 0,
                'ask2': float(stock[24]) if stock[24] else 0.0,
                'ask3_volume': int(stock[25]) if stock[25] else 0,
                'ask3': float(stock[26]) if stock[26] else 0.0,
                'ask4_volume': int(stock[27]) if stock[27] else 0,
                'ask4': float(stock[28]) if stock[28] else 0.0,
                'ask5_volume': int(stock[29]) if stock[29] else 0,
                'ask5': float(stock[30]) if stock[30] else 0.0,
                'date': stock[31] if stock[31] else '',
                'time': stock[32] if stock[32] else '',
            }

            # 数据清洗和验证
            cleaned_data = validate_and_clean_tick_data(raw_tick_data)
            if cleaned_data:
                stock_dict[stock[0]] = cleaned_data
            else:
                logger.warning(f"股票 {stock[0]} 数据清洗失败，已丢弃")

        return stock_dict

    except Exception as e:
        logger.error(f"格式化响应数据时发生错误: {e}")
        logger.error(f"堆栈跟踪信息:\n{traceback.format_exc()}")
        return {}


class SinaTickCollector:
    """新浪Tick数据收集器类"""
    
    def __init__(self):
        self.running = True
        self.current_ws = None
        self.tick_buffer = None
        self.aggregator = None
        self.aggregation_thread = None
        self.setup_signal_handlers()
    
    def setup_signal_handlers(self):
        """设置信号处理器"""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signalnum, frame):
        """信号处理函数，优雅地停止程序"""
        logger.info(f"接收到停止信号 {signalnum}，正在优雅地停止程序...")
        
        # 停止主循环
        self.running = False
        # 执行资源清理
        self.cleanup_resources()
        
        logger.info("程序已优雅停止")
    
    def cleanup_resources(self):
        """清理资源，确保所有资源被正确释放"""
        # 停止聚合线程
        if self.aggregation_thread is not None:
            try:
                logger.info("正在停止聚合处理线程...")
                self.aggregation_thread.join(timeout=5)
                if self.aggregation_thread.is_alive():
                    logger.warning("聚合处理线程未能在5秒内停止")
                else:
                    logger.info("聚合处理线程已停止")
            except Exception as e:
                logger.error(f"停止聚合处理线程时发生错误: {e}")
            finally:
                self.aggregation_thread = None
        
        # 关闭WebSocket连接
        if self.current_ws is not None:
            try:
                logger.info("正在关闭WebSocket连接...")
                self.current_ws.close()
                logger.info("WebSocket连接已关闭")
            except Exception as e:
                logger.error(f"关闭WebSocket连接时发生错误: {e}")
                logger.error(f"堆栈跟踪信息:\n{traceback.format_exc()}")
            finally:
                self.current_ws = None
        
        # 这里可以添加其他资源的清理代码
        # 例如关闭数据库连接、释放文件句柄等
        
        logger.info("资源清理完成")
    
    def start_aggregation_thread(self):
        """启动聚合处理线程"""
        if self.aggregation_thread is not None and self.aggregation_thread.is_alive():
            logger.warning("聚合处理线程已经在运行")
            return
        
        self.aggregation_thread = threading.Thread(
            target=self._aggregation_worker,
            name="AggregationThread",
            daemon=True
        )
        self.aggregation_thread.start()
        logger.info("聚合处理线程已启动")
    
    def check_market_close_time(self):
        """检查是否已过闭市15分钟，如果是则停止运行"""
        now = datetime_helper.now()
        # 闭市时间15:00 + 15分钟 = 15:15
        market_close_plus_15min = now.replace(hour=15, minute=15, second=0, microsecond=0)
        
        if now > market_close_plus_15min:
            logger.info(f"已过闭市15分钟（15:15），停止数据收集器运行")
            return True
        return False

    def _aggregation_worker(self):
        """聚合处理工作线程，确保两次处理间隔至少3秒"""
        logger.info("聚合处理线程开始运行，两次处理间隔至少3秒")
        
        while self.running:
            try:
                if self.check_market_close_time():
                    if self.current_ws is not None:
                        self.current_ws.close()
                    self.running = False
                    break
                process_start_time = time.time()
                
                # 获取缓冲区中所有股票代码
                if self.tick_buffer is not None:
                    stock_codes = self.tick_buffer.get_all_stock_codes()
                    
                    if stock_codes:
                        processed_count = 0
                        for stock_code in stock_codes:
                            try:
                                # 处理每只股票的聚合
                                kline_results = self.aggregator.process(stock_code)
                                if len(kline_results) > 0:
                                    logger.info(f"股票 {stock_code} 生成1分钟K线: {kline_results}")
                                    processed_count += 1
                                    
                                    # 添加source字段
                                    for record in kline_results:
                                        record['source'] = 'sina_tick'
                                        code = record['code']
                                        record['code'] = fq_util_code_append_market_code(code, upper_case=False)
                                        record['inst_code'] = fq_util_code_append_market_code_suffix(code)
                                    
                                    save_hq_stock_realtime(kline_results)
                            except Exception as e:
                                logger.error(f"聚合处理股票 {stock_code} 时发生错误: {e}")
                                continue
                        
                        if processed_count > 0:
                            logger.debug(f"本轮聚合处理完成， {processed_count} 只股票产生了新的1分钟K线")
                
                # 计算本次处理耗时
                processing_time = time.time() - process_start_time
                sleep_time = max(3 - processing_time, 0)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"聚合处理线程发生错误: {e}")
                logger.error(f"堆栈跟踪信息:\n{traceback.format_exc()}")
                sleep(3)  # 发生错误时也要等待，避免无限循环
        
        logger.info("聚合处理线程已退出")


    def on_message(self, ws, message):
        """处理WebSocket接收到的消息，只负责将数据放入缓冲区"""
        try:
            # 如果是bytes类型，先转换为字符串
            if isinstance(message, bytes):
                message = message.decode('utf-8', errors='ignore')
            
            lines = message.splitlines()

            for item in lines:
                if not item.strip():
                    continue

                # 格式化并清洗数据
                data = format_response_data(item)
                if not data:
                    continue

                # 处理每只股票的数据，只添加到缓冲区
                for stock_code, tick_data in data.items():
                    try:
                        # 只添加到缓冲区
                        buffer_success = self.tick_buffer.add_tick(stock_code, tick_data)
                        if not buffer_success:
                            logger.error(f"股票 {stock_code} 数据添加到缓冲区失败")
                    except Exception as e:
                        logger.error(f"处理股票 {stock_code} 数据时发生错误: {e}")
                        continue

        except Exception as e:
            logger.error(f"处理WebSocket消息时发生错误: {e}")
            logger.error(f"堆栈跟踪信息:\n{traceback.format_exc()}")

    def on_error(self, ws, error):
        """增强的错误处理函数"""
        logger.error(f"WebSocket连接发生错误: {type(error).__name__}: {error}")

        # 记录详细的错误信息
        if hasattr(error, '__dict__'):
            logger.error(f"错误详情: {error.__dict__}")

        # 根据错误类型进行不同的处理
        if isinstance(error, websocket.WebSocketConnectionClosedException):
            logger.error("WebSocket连接已关闭，将尝试重新连接")
        elif isinstance(error, ConnectionError):
            logger.error("网络连接错误，检查网络连接")
        elif isinstance(error, TimeoutError):
            logger.error("连接超时")
        else:
            logger.error(f"未知错误类型: {type(error)}")

        # 这里可以添加重连逻辑或其他恢复措施

    def on_close(self, ws, msg1, msg2):
        """增强的连接关闭处理函数"""
        close_reason = f"reason={msg1}, message={msg2}" if msg1 or msg2 else "未知原因"
        logger.warning(f"WebSocket连接已关闭: {close_reason}")
        self.running = False

    def on_open(self, ws):
        """WebSocket连接打开时的处理函数"""
        logger.info("WebSocket连接已成功打开")

        try:
            # 初始化缓冲区和聚合器
            self.tick_buffer = TickDataBuffer()
            logger.info("Tick数据缓冲区初始化完成")
            self.aggregator = OneMinuteAggregator(tick_buffer=self.tick_buffer)
            logger.info("1分钟聚合器初始化完成")
            
            # 启动聚合处理线程
            self.start_aggregation_thread()
            
            logger.info("数据收集器准备就绪，开始接收tick数据")
        except Exception as e:
            logger.error(f"初始化缓冲区或聚合器时发生错误: {e}")
            logger.error(f"堆栈跟踪信息:\n{traceback.format_exc()}")

    def run(self):
        """运行数据收集器主循环"""
        logger.info("新浪Tick数据收集器启动")

        try:
            while self.running:
                try:
                    # 检查是否在交易时间内
                    seconds = tool_trade_date_seconds_to_start()
                    if seconds > 0:
                        logger.info(
                            "%s 距离交易开始还有 %s，进入休眠状态"
                            % (
                                datetime_helper.now().strftime(cfg.DT_FORMAT_FULL),
                                durationpy.to_str(timedelta(seconds=seconds)),
                            )
                        )
                        sleep(min(seconds, 900))
                        continue

                    # 获取需要监控的股票代码
                    monitor_codes = get_stock_monitor_codes()
                    if not monitor_codes:
                        logger.warning("没有找到需要监控的股票代码，等待30秒后重试")
                        sleep(30)
                        continue

                    symbols = ','.join(map(fq_util_code_append_market_code, monitor_codes))
                    logger.info(f"开始监控 {len(monitor_codes)} 只股票: {symbols[:100]}...")

                    # 创建WebSocket连接
                    websocket.enableTrace(False)  # 不在控制台打印详细连接信息
                    ws = websocket.WebSocketApp(
                        f"wss://hq.sinajs.cn/wskt?list={symbols}",
                        header={
                            "Referer": "http://finance.sina.com.cn",
                            "Origin": "http://finance.sina.com.cn",
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:96.0) Gecko/20100101 Firefox/96.0",
                        },
                        on_open=self.on_open,
                        on_message=self.on_message,
                        on_error=self.on_error,
                        on_close=self.on_close,
                    )
                    
                    # 保存当前WebSocket连接
                    self.current_ws = ws

                    # 运行WebSocket连接
                    logger.info("建立WebSocket连接...")
                    ws.run_forever(
                        ping_interval=30,  # 每30秒发送一次ping
                        ping_timeout=10,   # ping超时时间
                        skip_utf8_validation=True  # 跳过UTF8验证以提高性能
                    )
                    
                    # 连接结束后清空当前连接
                    self.current_ws = None

                except websocket.WebSocketConnectionClosedException:
                    logger.warning("WebSocket连接已关闭，5秒后尝试重新连接")
                    sleep(5)
                    continue

                except ConnectionError as e:
                    logger.error(f"网络连接错误: {e}，30秒后尝试重新连接")
                    sleep(30)
                    continue

                except TimeoutError as e:
                    logger.error(f"连接超时: {e}，10秒后尝试重新连接")
                    sleep(10)
                    continue

                except Exception as e:
                    logger.error(f"程序运行时发生未预期的错误: {type(e).__name__}: {e}")
                    logger.error(f"堆栈跟踪信息:\n{traceback.format_exc()}")
                    logger.exception("详细错误信息:")

                    # 短暂等待后继续尝试
                    sleep(10)
                    continue

        except KeyboardInterrupt:
            logger.info("收到键盘中断信号，正在优雅地退出...")
            # KeyboardInterrupt已经由signal_handler处理，这里只是额外的保障

        except Exception as e:
            logger.error(f"主程序发生严重错误: {type(e).__name__}: {e}")
            logger.error(f"堆栈跟踪信息:\n{traceback.format_exc()}")
            logger.exception("详细错误信息:")

        finally:
            # 确保资源被正确清理
            logger.info("程序正在退出，清理资源...")
            # 确保running标志被设置为False
            self.running = False
            # 执行资源清理
            self.cleanup_resources()
            logger.info("程序已完全退出")


if __name__ == "__main__":
    collector = SinaTickCollector()
    collector.run()
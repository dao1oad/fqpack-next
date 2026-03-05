import json
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any, Tuple
from collections import defaultdict
from loguru import logger

from freshquant.database.redis import redis_db
from freshquant.util import datetime_helper


class TickDataBuffer:
    """
    Tick数据缓冲区，使用Redis存储模式
    
    - 使用Redis的zset存储tick数据
    - zset的key格式为: {prefix}:{code}:{date}，例如 tick_buffer:000001.SZ:20230101
    - zset的score为tick的时间戳（秒级）
    - zset的value为tick的json序列化字符串
    - zset的TTL可配置
    """

    def __init__(self, 
                 redis_key_prefix: str = "tick_buffer",
                 buffer_ttl_seconds: int = 86400):  # 默认24小时
        """
        初始化TickDataBuffer
        
        Args:
            redis_key_prefix: Redis键前缀，默认为"tick_buffer"
            buffer_ttl_seconds: 缓冲区数据的生存时间（秒），默认24小时
        """
        self.redis_key_prefix = redis_key_prefix
        self.buffer_ttl_seconds = buffer_ttl_seconds
        
        # 统计信息
        self.stats = {
            "total_ticks_added": 0,
            "total_ticks_dropped": 0,
            "stocks_count": 0
        }
    
    def _get_key(self, code: str) -> str:
        """
        生成Redis的key，使用当天日期
        
        Args:
            code: 股票代码
            
        Returns:
            Redis的key
        """
        today = datetime_helper.now().strftime("%Y%m%d")
        return f"{self.redis_key_prefix}:{code}:{today}"
    
    
    def add_tick(self, code: str, tick_data: Dict[str, Any]) -> bool:
        """
        添加一个tick到缓冲区
        
        Args:
            code: 股票代码
            tick_data: tick数据字典，应包含以下字段:
                - code: 股票代码
                - name: 股票名称
                - open: 开盘价
                - pre_close: 昨收价
                - now: 当前价
                - high: 最高价
                - low: 最低价
                - buy: 买入价
                - sell: 卖出价
                - turnover: 成交量
                - volume: 成交额
                - bid1_volume ~ bid5_volume: 买一到买五量
                - bid1 ~ bid5: 买一到买五价
                - ask1_volume ~ ask5_volume: 卖一到卖五量
                - ask1 ~ ask5: 卖一到卖五价
                - date: 日期
                - time: 时间
            
        Returns:
            是否添加成功
        """
        try:
            # 从tick_data中提取时间
            date_str = tick_data.get('date')
            time_str = tick_data.get('time')
            
            if not time_str or not date_str:
                logger.warning(f"添加tick失败: 缺少日期或时间信息")
                return False
                
            # 解析时间
            try:
                # 使用提供的日期和时间
                tick_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            except ValueError:
                logger.warning(f"添加tick失败: 时间格式错误 {date_str} {time_str}")
                return False
            
            # 使用时间戳作为score（秒级）
            score = int(tick_time.timestamp())
            tick_data['score'] = score

            # Redis存储模式
            key = self._get_key(code)
            
            # 将tick转换为json字符串
            tick_json = json.dumps(tick_data)
            # 添加到zset
            redis_db.zadd(key, {tick_json: score})
            
            # 设置TTL
            redis_db.expire(key, self.buffer_ttl_seconds)
            
            # 更新统计信息
            self.stats["total_ticks_added"] += 1
            
            return True
        except Exception as e:
            logger.error(f"添加tick失败: {e}")
            return False
    
    def add_ticks(self, code: str, ticks: List[Dict[str, Any]]) -> int:
        """
        批量添加ticks到缓冲区
        
        Args:
            code: 股票代码
            ticks: tick数据字典列表
            
        Returns:
            成功添加的tick数量
        """
        success_count = 0
        for tick in ticks:
            if self.add_tick(code, tick):
                success_count += 1
        return success_count
    
    def get_ticks_by_minute(self, code: str, hour: int, minute: int) -> List[Dict[str, Any]]:
        """
        获取指定股票在指定日期指定分钟的所有ticks
        
        Args:
            code: 股票代码
            hour: 小时（0-23）
            minute: 分钟（0-59）
            
        Returns:
            tick数据字典列表
        """
        try:                
            # 计算该分钟的起始和结束时间戳
            base_date = datetime_helper.now()
            start_time = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            end_time = start_time + timedelta(minutes=1) - timedelta(microseconds=1)
            
            # 转换为秒级时间戳
            min_score = int(start_time.timestamp())
            max_score = int(end_time.timestamp())
            
            # Redis存储模式
            key = self._get_key(code)
            
            # 从zset中获取指定范围的ticks
            tick_jsons = redis_db.zrangebyscore(key, min_score, max_score)
            
            # 将json字符串转换为字典
            ticks = []
            for tick_json in tick_jsons:
                tick_dict = json.loads(tick_json)
                ticks.append(tick_dict)
            
            return ticks
        except Exception as e:
            logger.error(f"获取分钟ticks失败: {e}")
            return []
    
    def get_ticks_by_day(self, code: str) -> List[Dict[str, Any]]:
        """
        获取指定股票在指定日期的所有ticks
        
        Args:
            code: 股票代码
            date_str: 日期字符串，格式为'%Y-%m-%d'，默认为当天
            
        Returns:
            tick数据字典列表
        """
        try:
            # Redis存储模式
            key = self._get_key(code)

            # 获取zset中的所有元素
            tick_jsons = redis_db.zrange(key, 0, -1)
            
            # 将json字符串转换为字典
            ticks = []
            for tick_json in tick_jsons:
                tick_dict = json.loads(tick_json)
                ticks.append(tick_dict)
            
            return ticks
        except Exception as e:
            logger.error(f"获取日ticks失败: {e}")
            return []

    def get_ticks_by_range(self, code: str, min_score: float, max_score: float) -> List[Dict[str, Any]]:
        """
        获取指定股票在指定时间戳范围内的所有ticks
        
        Args:
            code: 股票代码
            min_score: 最小时间戳（包含）
            max_score: 最大时间戳（包含）
            
        Returns:
            tick数据字典列表
        """
        try:
            # Redis存储模式
            key = self._get_key(code)
            
            # 从zset中获取指定范围的ticks
            tick_jsons = redis_db.zrangebyscore(key, min_score, max_score)
            
            # 将json字符串转换为字典
            ticks = []
            for tick_json in tick_jsons:
                tick_dict = json.loads(tick_json)
                ticks.append(tick_dict)
            
            return ticks
        except Exception as e:
            logger.error(f"获取时间范围ticks失败: {e}")
            return []
    
    def get_last_tick(self, code: str) -> Optional[Dict[str, Any]]:
        """
        获取指定股票的最新tick
        
        Args:
            code: 股票代码
            
        Returns:
            最新的tick数据字典，如果没有则返回None
        """
        try:
            # Redis存储模式
            key = self._get_key(code)
            
            # 获取zset中的最后一个元素（分数最高的元素）
            result = redis_db.zrange(key, -1, -1)
            
            if not result:
                return None
            
            # 将json字符串转换为字典
            tick_json = result[0]
            tick_dict = json.loads(tick_json)
            return tick_dict
        except Exception as e:
            logger.error(f"获取最新tick失败: {e}")
            return None
    
    def get_ticks_count(self, code: str) -> int:
        """
        获取指定股票的tick数量
        
        Args:
            code: 股票代码
            
        Returns:
            tick数量
        """
        try:
            # Redis存储模式
            key = self._get_key(code)
            
            # 获取zset的大小
            return redis_db.zcard(key)
        except Exception as e:
            logger.error(f"获取tick数量失败: {e}")
            return 0
    
    def clear_ticks(self, code: str) -> bool:
        """
        清除指定股票的所有ticks
        
        Args:
            code: 股票代码
            
        Returns:
            是否清除成功
        """
        try:
            # Redis存储模式
            key = self._get_key(code)
            
            # 删除key
            redis_db.delete(key)
            
            return True
        except Exception as e:
            logger.error(f"清除ticks失败: {e}")
            return False
    
    def get_all_stock_codes(self) -> List[str]:
        """
        获取缓冲区中所有股票代码
        
        Returns:
            股票代码列表
        """
        try:
            # Redis存储模式
            # 获取所有当天的key
            pattern = f"{self.redis_key_prefix}:*:{datetime_helper.now().strftime('%Y%m%d')}"
            keys = redis_db.keys(pattern)
            
            # 从key中提取股票代码
            stock_codes = []
            for key in keys:
                # key格式为: tick_buffer:000001.SZ:20230101
                # 提取中间的股票代码部分
                parts = key.split(':')
                if len(parts) >= 3:
                    stock_code = parts[1]  # 股票代码在第二个位置
                    stock_codes.append(stock_code)
            
            return stock_codes
        except Exception as e:
            logger.error(f"获取所有股票代码失败: {e}")
            return []

    def clear_all_ticks(self) -> bool:
        """
        清除所有ticks

        Returns:
            是否清除成功
        """
        try:
            # Redis存储模式
            # 获取所有当天的key
            pattern = f"{self.redis_key_prefix}:*:{datetime_helper.now().strftime('%Y%m%d')}"
            keys = redis_db.keys(pattern)
            
            if keys:
                # 删除所有key
                redis_db.delete(*keys)
            
            # 重置统计信息
            self.stats["stocks_count"] = 0
            
            return True
        except Exception as e:
            logger.error(f"清除所有ticks失败: {e}")
            return False

import hashlib
import json
from abc import ABC, abstractmethod
from enum import Enum, StrEnum
from typing import Any, Dict, List, Optional, Type

from loguru import logger
from pydantic import BaseModel

# ============================================================================
# 数据类型定义
# ============================================================================


class DataType(StrEnum):
    """量化选股数据类型"""

    # 量化选股特定类型
    STOCK_CODE = "STOCK_CODE"
    STOCK_LIST = "STOCK_LIST"
    FACTOR = "FACTOR"
    FACTORS = "FACTORS"
    SCORES = "SCORES"
    SIGNAL = "SIGNAL"
    WEIGHTS = "WEIGHTS"
    PORTFOLIO = "PORTFOLIO"
    BACKTEST_RESULT = "BACKTEST_RESULT"
    STRATEGY_CONFIG = "STRATEGY_CONFIG"
    FACTOR_CONFIG = "FACTOR_CONFIG"

    # 基础类型
    STRING = "STRING"
    INT = "INT"
    FLOAT = "FLOAT"
    BOOL = "BOOL"
    DICT = "DICT"
    LIST = "LIST"
    DATAFRAME = "DATAFRAME"
    ANY = "*"


class NodeStatus(str, Enum):
    """节点执行状态"""

    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CACHED = "cached"


# ============================================================================
# 基础Node类
# ============================================================================


class BaseNode(ABC):
    """所有节点的基类"""

    # 节点元数据
    NODE_ID: str = ""
    NODE_NAME: str = ""
    NODE_DESCRIPTION: str = ""
    CATEGORY: str = "custom"
    VERSION: str = "1.0.0"
    AUTHOR: str = ""
    TAGS: List[str] = []

    def __init__(self):
        self.logger = logger.bind(node=self.__class__.__name__)
        self.status = NodeStatus.IDLE
        self.execution_time: float = 0.0
        self.cache_key: Optional[str] = None
        self.cached_result: Optional[Any] = None

    @classmethod
    @abstractmethod
    def input_schema(cls) -> Type[BaseModel]:
        """返回输入Schema"""
        pass

    @classmethod
    @abstractmethod
    def output_schema(cls) -> Type[BaseModel]:
        """返回输出Schema"""
        pass

    @abstractmethod
    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """执行节点逻辑"""
        pass

    def get_cache_key(self, inputs: Dict[str, Any]) -> Optional[str]:
        """生成缓存键"""
        try:
            # 只对基础类型生成缓存键
            serializable = {}
            for k, v in inputs.items():
                if isinstance(v, (str, int, float, bool, list, dict)):
                    serializable[k] = v
            input_str = json.dumps(serializable, default=str, sort_keys=True)
            return hashlib.md5(input_str.encode()).hexdigest()
        except Exception as e:
            self.logger.warning(f"Failed to generate cache key: {e}")
            return None

    def can_use_cache(self) -> bool:
        """是否支持缓存"""
        return False

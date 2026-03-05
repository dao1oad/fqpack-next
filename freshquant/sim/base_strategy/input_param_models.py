"""
策略输入参数模型

定义策略运行参数的基类，提供参数验证、序列化等功能
"""

from enum import Enum
from typing import Any, Dict, Optional


class MarketDirection(str, Enum):
    """市场方向"""

    LONG = "long"  # 多头/看涨
    SHORT = "short"  # 空头/看跌
    NEUTRAL = "neutral"  # 中性


class InputParamModel:
    """
    策略输入参数模型基类

    用于定义和管理策略运行时的参数配置，支持参数验证、默认值、序列化等功能。
    子类可以继承此类来定义特定策略的参数模型。

    示例:
        class MyStrategyParams(InputParamModel):
            def __init__(self, stop_loss_ratio=0.05, take_profit_ratio=0.1):
                super().__init__()
                self.set_param('stop_loss_ratio', stop_loss_ratio, float, (0, 1))
                self.set_param('take_profit_ratio', take_profit_ratio, float, (0, 1))
    """

    def __init__(self) -> None:
        """
        初始化参数模型
        """
        self._params: Dict[str, Any] = {}
        self._param_types: Dict[str, type] = {}
        self._param_ranges: Dict[str, tuple] = {}
        self._param_descriptions: Dict[str, str] = {}

    def set_param(
        self,
        name: str,
        value: Any,
        param_type: Optional[type] = None,
        value_range: Optional[tuple] = None,
        description: str = '',
    ):
        """
        设置参数

        参数:
        name: 参数名称
        value: 参数值
        param_type: 参数类型（可选），如 int, float, str, bool 等
        value_range: 参数取值范围（可选），格式为 (min, max) 或 [choice1, choice2, ...]
        description: 参数描述（可选）

        异常:
        TypeError: 参数类型不匹配
        ValueError: 参数值超出范围
        """
        # 类型检查
        if param_type is not None:
            if not isinstance(value, param_type):
                raise TypeError(
                    f"参数 '{name}' 类型错误: 期望 {param_type.__name__}, 实际 {type(value).__name__}"
                )
            self._param_types[name] = param_type

        # 范围检查
        if value_range is not None:
            if isinstance(value_range, tuple) and len(value_range) == 2:
                # 数值范围 (min, max)
                min_val, max_val = value_range
                if not (min_val <= value <= max_val):
                    raise ValueError(
                        f"参数 '{name}' 超出范围: {value} 不在 [{min_val}, {max_val}] 内"
                    )
            elif isinstance(value_range, (list, set)):
                # 枚举值
                if value not in value_range:
                    raise ValueError(
                        f"参数 '{name}' 值无效: {value} 不在 {value_range} 中"
                    )
            self._param_ranges[name] = value_range

        self._params[name] = value
        if description:
            self._param_descriptions[name] = description

    def get_param(self, name: str, default: Any = None) -> Any:
        """
        获取参数值

        参数:
        name: 参数名称
        default: 默认值（可选），如果参数不存在则返回此值

        返回:
        参数值
        """
        return self._params.get(name, default)

    def has_param(self, name: str) -> bool:
        """
        检查参数是否存在

        参数:
        name: 参数名称

        返回:
        bool: 参数是否存在
        """
        return name in self._params

    def remove_param(self, name: str):
        """
        删除参数

        参数:
        name: 参数名称
        """
        if name in self._params:
            del self._params[name]
        if name in self._param_types:
            del self._param_types[name]
        if name in self._param_ranges:
            del self._param_ranges[name]
        if name in self._param_descriptions:
            del self._param_descriptions[name]

    def update_params(self, params: Dict[str, Any]):
        """
        批量更新参数

        参数:
        params: 参数字典，格式为 {'param_name': value}
        """
        for name, value in params.items():
            # 如果已有类型和范围定义，使用set_param进行验证
            if name in self._param_types or name in self._param_ranges:
                self.set_param(
                    name,
                    value,
                    self._param_types.get(name),
                    self._param_ranges.get(name),
                )
            else:
                self._params[name] = value

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典

        返回:
        Dict[str, Any]: 参数字典
        """
        return self._params.copy()

    def get_param_info(self, name: str) -> Dict[str, Any]:
        """
        获取参数的详细信息

        参数:
        name: 参数名称

        返回:
        Dict: 包含参数值、类型、范围、描述等信息的字典
        """
        if name not in self._params:
            return {}

        param_type = self._param_types.get(name)
        return {
            'value': self._params[name],
            'type': param_type.__name__ if param_type is not None else None,
            'range': self._param_ranges.get(name),
            'description': self._param_descriptions.get(name, ''),
        }

    def get_all_params_info(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有参数的详细信息

        返回:
        Dict: 所有参数的信息字典
        """
        return {name: self.get_param_info(name) for name in self._params.keys()}

    def validate(self) -> bool:
        """
        验证所有参数是否符合定义的类型和范围

        返回:
        bool: 验证是否通过

        异常:
        TypeError: 参数类型不匹配
        ValueError: 参数值超出范围
        """
        for name, value in self._params.items():
            # 重新验证类型和范围
            if name in self._param_types or name in self._param_ranges:
                self.set_param(
                    name,
                    value,
                    self._param_types.get(name),
                    self._param_ranges.get(name),
                )
        return True

    def __getitem__(self, key: str) -> Any:
        """支持字典式访问: params['key']"""
        return self._params[key]

    def __setitem__(self, key: str, value: Any):
        """支持字典式赋值: params['key'] = value"""
        self._params[key] = value

    def __contains__(self, key: str) -> bool:
        """支持 in 操作符: 'key' in params"""
        return key in self._params

    def __repr__(self) -> str:
        """字符串表示"""
        return f"InputParamModel({self._params})"

    def __str__(self) -> str:
        """可读的字符串表示"""
        lines = ["策略参数:"]
        for name, value in self._params.items():
            info = self.get_param_info(name)
            desc = f" - {info['description']}" if info['description'] else ""
            type_str = f" ({info['type']})" if info['type'] else ""
            range_str = f" 范围: {info['range']}" if info['range'] else ""
            lines.append(f"  {name}: {value}{type_str}{range_str}{desc}")
        return '\n'.join(lines)

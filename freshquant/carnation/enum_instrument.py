# -*- coding: utf-8 -*-

import json
from enum import Enum


class InstrumentType(Enum):
    """
    标的类型
    根据现在要做的标的，先定义这么多。
    """

    STOCK_CN = 'stock_cn'
    BOND_CN = 'bond_cn'
    ETF_CN = 'etf_cn'
    INDEX_CN = 'index_cn'

    def to_json(self):
        """转换为JSON可序列化的值"""
        return self.value

    @classmethod
    def from_json(cls, value):
        """从JSON值创建枚举实例"""
        return cls(value)

    def __json__(self):
        """支持某些JSON库的自动序列化"""
        return self.value


if __name__ == "__main__":
    print(str(InstrumentType.STOCK_CN.value))

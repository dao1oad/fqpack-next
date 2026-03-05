#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json

from freshquant.carnation.enum_instrument import InstrumentType


def test_enum_serialization():
    """测试枚举的JSON序列化功能"""

    # 测试基本序列化
    instrument = InstrumentType.STOCK_CN
    print(f"原始枚举值: {instrument}")
    print(f"枚举的value: {instrument.value}")

    # 方法1：使用自定义的to_json方法
    json_value = instrument.to_json()
    print(f"使用to_json(): {json_value}")

    # 方法2：在字典中使用（需要手动转换）
    data = {"instrument_type": instrument.value, "name": "测试股票"}  # 直接使用.value
    json_str = json.dumps(data, ensure_ascii=False)
    print(f"JSON字符串: {json_str}")

    # 反序列化测试
    parsed_data = json.loads(json_str)
    restored_instrument = InstrumentType.from_json(parsed_data["instrument_type"])
    print(f"反序列化后的枚举: {restored_instrument}")
    print(f"是否相等: {instrument == restored_instrument}")

    # 测试所有枚举值
    print("\n所有枚举值的序列化:")
    for enum_item in InstrumentType:
        print(f"{enum_item.name} -> {enum_item.to_json()}")


if __name__ == "__main__":
    test_enum_serialization()

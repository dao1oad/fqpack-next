# -*- coding: utf-8 -*-

from freshquant.database.mongodb import DBfreshquant


def init_strategy_dict():
    # 初始化策略字典
    DBfreshquant.strategies.update_one(
        {"code": "Guardian"},
        {"$setOnInsert": {"name": "守护者策略", "desc": "这是一个高抛低吸的超级网格策略"}},
        upsert=True,
    )
    DBfreshquant.strategies.update_one(
        {"code": "Manual"},
        {"$setOnInsert": {"name": "手动策略", "desc": "这是手动挡交易策略"}},
        upsert=True,
    )

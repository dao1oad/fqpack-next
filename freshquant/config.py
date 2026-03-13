# -*- coding: utf-8 -*-

import os
import sys
from typing import cast

import pytz  # type: ignore
from dynaconf import Dynaconf

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # freshquant所在目录
EXE_DIR = os.path.split(os.path.realpath(sys.argv[0]))[0]  # 程序或脚本所在目录
CWD_DIR = os.getcwd()  # 执行程序或脚本的目录


class Config:
    BASE_DIR = BASE_DIR
    EXE_DIR = EXE_DIR
    CWD_DIR = CWD_DIR
    TIME_ZONE = 'Asia/Shanghai'
    TZ = pytz.timezone(TIME_ZONE)
    DT_FORMAT_FULL = "%Y-%m-%d %H:%M:%S"
    DT_FORMAT_DAY = "%Y-%m-%d"
    DT_FORMAT_M = "%Y-%m-%d %H:%M"

    PROXIES = {
        "http": os.environ.get('freshquant_PROXY', 'http://127.0.0.1:10809'),
        "https": os.environ.get('freshquant_PROXY', 'http://127.0.0.1:10809'),
    }
    PROXY_HOST = os.environ.get('freshquant_PROXY_HOST', '127.0.0.1')
    PROXY_PORT = os.environ.get('freshquant_PROXY_PORT', '10809')
    CUSTOM_DATA_DIR = os.environ.get('freshquant_CUSTOM_DATA_DIR')
    OHLC = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'amount': 'sum',
    }
    TIME_DELTA = {
        '1m': -13,
        '3m': -38,
        '5m': -63,
        '15m': -125,
        '30m': -375,
        '60m': -750,
        '90m': -1000,
        '120m': -1000,
        '180m': -1000,
        '1d': -1500,
        '1w': -3000,
    }
    FUTURE_OHLC = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'position': 'sum',
        'amount': 'sum',
    }


class DevelopmentConfig(Config):
    # 局域网2台电脑公用数据库
    MONGODB_SETTINGS = {
        'url': os.environ.get('freshquant_MONGO_URL', 'mongodb://localhost:27027')
    }
    TEMPORAL_SETTINGS = {
        'host': os.environ.get('TEMPORAL_HOST', 'localhost'),
        'port': int(os.environ.get('TEMPORAL_PORT', '7233')),
        'TASK_QUEUE': "freshquant",
        'NAMESPACE': "default",
    }


class ProductionConfig(Config):
    MONGODB_SETTINGS = {
        'url': os.environ.get('freshquant_MONGO_URL', 'mongodb://localhost:27027')
    }
    TEMPORAL_SETTINGS = {
        'host': os.environ.get('TEMPORAL_HOST', 'temporal'),
        'port': int(os.environ.get('TEMPORAL_PORT', '7233')),
        'TASK_QUEUE': "freshquant",
        'NAMESPACE': "default",
    }


config = {
    'default': DevelopmentConfig,
    'production': ProductionConfig,
    'symbolList': [
        # 第一组  28个
        # 黑色系
        "RB",
        "HC",
        "I",
        "J",
        # "JM",
        # 金属类
        "AG",
        "AU",
        "NI",
        "ZN",
        # 化工系
        "RU",
        "FU",
        "BU",
        "MA",
        "TA",
        "PP",
        # "EG",
        # "EB",
        # "L",
        # "PG",
        # 农产品
        "CF",
        "SR",
        "AP",
        # "JD",
        # "A",
        "M",
        # "RM",
        # 食用油
        "Y",
        "P",
        # "OI",
        # "IC",
        # "IF",
        # "IH",
        #   第二组 新增品种 15
        #     "AL",
        #     "SN",
        #     "PB",
        #     "SM",
        # "SF",
        # "B",
        "C",
        # "CS",
        # "CJ",
        # "SP",
        "FG",
        "SA",
        # "ZC",
        # "UR",
        "V",
    ],
    # 华安期货是在标准保证金基础上加1个点，这个可以找期货公司调整 b
    'margin_rate_company': 0.01,
    # 商品期货保证金率一般固定，只有过节会变下。因为换合约期间需要拿到老合约保证金率，因此保存起来
    'futureConfig': {
        # 上期所
        'RB': {'margin_rate': 0.09, 'contract_multiplier': 10},
        'HC': {'margin_rate': 0.09, 'contract_multiplier': 10},
        'RU': {'margin_rate': 0.11, 'contract_multiplier': 10},
        'FU': {'margin_rate': 0.11, 'contract_multiplier': 10},
        'BU': {'margin_rate': 0.11, 'contract_multiplier': 10},
        'AU': {'margin_rate': 0.08, 'contract_multiplier': 1000},
        'AG': {'margin_rate': 0.12, 'contract_multiplier': 15},
        'NI': {'margin_rate': 0.1, 'contract_multiplier': 1},
        'ZN': {'margin_rate': 0.1, 'contract_multiplier': 5},
        # 'SP': {'margin_rate': 0.08, 'contract_multiplier': 10},
        # 'CU': {'margin_rate': 0.1, 'contract_multiplier': 5},
        # 沪铝
        # 'AL': {'margin_rate': 0.1, 'contract_multiplier': 5},
        # 沪锡
        # 'SN': {'margin_rate': 0.1, 'contract_multiplier': 1},
        # 沪铅
        # 'PB': {'margin_rate': 0.1, 'contract_multiplier': 5},
        # 郑商所
        'MA': {'margin_rate': 0.07, 'contract_multiplier': 10},
        'TA': {'margin_rate': 0.07, 'contract_multiplier': 5},
        'CF': {'margin_rate': 0.07, 'contract_multiplier': 5},
        'SR': {'margin_rate': 0.05, 'contract_multiplier': 10},
        # 'OI': {'margin_rate': 0.06, 'contract_multiplier': 10},
        # 'RM': {'margin_rate': 0.06, 'contract_multiplier': 10},
        'AP': {'margin_rate': 0.08, 'contract_multiplier': 10},
        # 'CJ': {'margin_rate': 0.08, 'contract_multiplier': 5},
        # 玻璃
        'FG': {'margin_rate': 0.06, 'contract_multiplier': 20},
        # 纯碱
        'SA': {'margin_rate': 0.06, 'contract_multiplier': 20},
        # 锰硅
        # 'SM': {'margin_rate': 0.07, 'contract_multiplier': 5},
        # 尿素
        # 'UR': {'margin_rate': 0.05, 'contract_multiplier': 20},
        # 动力煤
        # 'ZC': {'margin_rate': 0.05, 'contract_multiplier': 100},
        # 硅铁
        # 'SF': {'margin_rate': 0.07, 'contract_multiplier': 5},
        # 大商所
        'J': {'margin_rate': 0.08, 'contract_multiplier': 100},
        # 'JM': {'margin_rate': 0.08, 'contract_multiplier': 60},
        'I': {'margin_rate': 0.08, 'contract_multiplier': 100},
        'M': {'margin_rate': 0.08, 'contract_multiplier': 10},
        # 'EG': {'margin_rate': 0.11, 'contract_multiplier': 10},
        # 聚丙烯
        'PP': {'margin_rate': 0.11, 'contract_multiplier': 5},
        # 苯乙烯
        # 'EB': {'margin_rate': 0.12, 'contract_multiplier': 5},
        # 聚乙烯
        # 'L': {'margin_rate': 0.11, 'contract_multiplier': 5},
        'P': {'margin_rate': 0.08, 'contract_multiplier': 10},
        'Y': {'margin_rate': 0.08, 'contract_multiplier': 10},
        # 'JD': {'margin_rate': 0.09, 'contract_multiplier': 10},
        # 'PG': {'margin_rate': 0.11, 'contract_multiplier': 20},
        # 豆一
        # 'A': {'margin_rate': 0.08, 'contract_multiplier': 10},
        # 豆二
        # 'B': {'margin_rate': 0.08, 'contract_multiplier': 10},
        # 玉米
        'C': {'margin_rate': 0.07, 'contract_multiplier': 10},
        # 淀粉
        # 'CS': {'margin_rate': 0.07, 'contract_multiplier': 10},
        # 聚氯乙烯
        'V': {'margin_rate': 0.09, 'contract_multiplier': 5},
        # 'IC': {'margin_rate': 0.12, 'contract_multiplier': 200},
        # 'IF': {'margin_rate': 0.10, 'contract_multiplier': 300},
        # 'IH': {'margin_rate': 0.10, 'contract_multiplier': 300},
        'BTC': {'margin_rate': 0.05, 'contract_multiplier': 1},
        'DOGE-USDT': {'margin_rate': 0.05, 'contract_multiplier': 1},
        # 外盘
        'CL': {
            'margin_rate': 0.16,
            'contract_multiplier': 500,
        },  # 8:30 -14:00 0.1      其它时间 0.15       11756
        'GC': {
            'margin_rate': 0.07,
            'contract_multiplier': 10,
        },  # 8:30 -14:00 0.02   其它时间 0.03         10065
        'SI': {
            'margin_rate': 0.14,
            'contract_multiplier': 5000,
        },  # 18:30 -14:00 0.04   其它时间 0.06       10271
        'HG': {
            'margin_rate': 0.06,
            'contract_multiplier': 25000,
        },  # 18:30 -14:00 0.04   其它时间 0.06       10271
        'NID': {'margin_rate': 0.1, 'contract_multiplier': 1},
        'ZSD': {'margin_rate': 0.1, 'contract_multiplier': 1},
        # 'CN': {'margin_rate': 0.09, 'contract_multiplier': 1},  # 18:30 -14:00 0.04   其它时间 0.06          1045
        'S': {'margin_rate': 0.03, 'contract_multiplier': 50},  # 2314
        'SM': {'margin_rate': 0.04, 'contract_multiplier': 100},  # 2062
        'BO': {'margin_rate': 0.04, 'contract_multiplier': 600},  # 935
        'FCPO': {'margin_rate': 0.1, 'contract_multiplier': 1},
        'CT': {'margin_rate': 0.1, 'contract_multiplier': 1},
        # 'SB': {'margin_rate': 0.1, 'contract_multiplier': 1},
        # wshq
        # 'YM': {'margin_rate': 0.13, 'contract_multiplier': 0.5},  # 18:30 -14:00 0.04   其它时间 0.06          13200
        # 'ES': {'margin_rate': 0.086, 'contract_multiplier': 5},  # 18:30 -14:00 0.04   其它时间 0.06          13200
        # 'NQ': {'margin_rate': 0.086, 'contract_multiplier': 2},  # 18:30 -14:00 0.04   其它时间 0.06          13200
        # 'AAPL': {'margin_rate': 1, 'contract_multiplier': 1},
        # 'MSFT': {'margin_rate': 1, 'contract_multiplier': 1},
        # 'GOOG': {'margin_rate': 1, 'contract_multiplier': 1},
        # 'FB': {'margin_rate': 1, 'contract_multiplier': 1},
        # 'AMZN': {'margin_rate': 1, 'contract_multiplier': 1},
        # 'NFLX': {'margin_rate': 1, 'contract_multiplier': 1},
        # 'NVDA': {'margin_rate': 1, 'contract_multiplier': 1},
        # 'AMD': {'margin_rate': 1, 'contract_multiplier': 1},
        # 'ROKU': {'margin_rate': 1, 'contract_multiplier': 1},
    },
    'periodList': ['1m', '3m', '5m', '15m', '30m', '60m', '180m', '1d', '1w'],
    # 外盘期货品种
    # CL:原油; GC:黄金;SI:白银; CT:棉花;S:大豆;SM:豆粕; BO:豆油;NID:伦镍; ZSD:伦锌;HG:美铜
    # YM:道琼斯 CN:A50 ;FCPO:马棕榈
    # wshq 'SB'
    # 'global_future_symbol': ['CL', 'GC', 'SI', 'YM', 'NQ', 'ES', 'CN', 'ZS', 'ZM', 'ZL', 'NID', 'ZSD'],
    # 新浪外盘品种名
    'global_future_symbol': [
        'CL',
        'GC',
        'SI',
        'HG',
        'NID',
        'ZSD',
        'S',
        'SM',
        'BO',
        'FCPO',
        'CT',
    ],
    # 美国股票
    'global_stock_symbol': [
        'AAPL',
        'MSFT',
        'GOOG',
        'FB',
        'AMZN',
        'NFLX',
        'NVDA',
        'AMD',
    ],
    # wshq
    'global_future_alias': {
        'NECLA0': 'CL',
        'CMGCA0': 'GC',
        'CMSIA0': 'SI',
        'CEYMA0': 'YM',
        'CEESA0': 'ES',
        'CENQA0': 'NQ',
        'WGCNA0': 'CN',
        'COZSA0': 'ZS',
        'COZMA0': 'ZM',
        'COZLA0': 'ZL',
        'IECTA0': 'CT',  # 美棉花
        'IESBA0': 'SB',  # 美糖
        'LENID3M': 'NID',  # 伦镍
        'LEZSD3M': 'ZSD',  # 伦锌
    },
    'digit_coin_symbol': ['DOGE-USDT'],
    'digit_coin_symbol_info': [
        {
            'contract_multiplier': 1,
            'de_listed_date': 'forever',
            'exchange': 'OKEX',
            'listed_date': 'forever',
            'margin_rate': 0.05,
            'market_tplus': 0,
            'maturity_date': 'forever',
            'order_book_id': 'DOGE-USDT',
            'round_lot': 1,
            'symbol': '狗狗币',
            'trading_hours': '7*24',
            'type': 'Future',
            'underlying_order_book_id': 'null',
            'underlying_symbol': 'DOGE-USDT',
            'feeRate': 0.012,
        }
    ],
    'global_future_symbol_info': [
        {
            'contract_multiplier': 500,
            'exchange': '美国',
            'margin_rate': 0.16,
            'order_book_id': 'CL',
            'trading_hours': '7*24',
            'type': 'future',
            'feeRate': 0.012,
        },
        {
            'contract_multiplier': 10,
            'exchange': '美国',
            'margin_rate': 0.07,
            'order_book_id': 'GC',
            'trading_hours': '7*24',
            'type': 'future',
            'feeRate': 0.012,
        },
        {
            'contract_multiplier': 5000,
            'exchange': '美国',
            'margin_rate': 0.14,
            'order_book_id': 'SI',
            'trading_hours': '7*24',
            'type': 'future',
            'feeRate': 0.012,
        },
        {
            'contract_multiplier': 25000,
            'exchange': '美铜',
            'margin_rate': 0.06,
            'order_book_id': 'HG',
            'trading_hours': '7*24',
            'type': 'future',
            'feeRate': 0.012,
        },
        # {
        #     'contract_multiplier': 1,
        #     'exchange': '新加坡',
        #     'margin_rate': 0.09,
        #     'order_book_id': 'CN',
        #     'trading_hours': '7*24',
        #     'type': 'stock',
        #     'feeRate': 0.012
        # },
        # {
        #     'contract_multiplier': 0.5,
        #     'exchange': '美国',
        #     'margin_rate': 0.13,
        #     'order_book_id': 'YM',
        #     'trading_hours': '7*24',
        #     'type': 'future',
        #     'feeRate': 0.012
        # },
        # {
        #     'contract_multiplier': 5,
        #     'exchange': '美国',
        #     'margin_rate': 0.086,
        #     'order_book_id': 'ES',
        #     'trading_hours': '7*24',
        #     'type': 'future',
        #     'feeRate': 0.012
        # },
        # {
        #     'contract_multiplier': 2,
        #     'exchange': '美国',
        #     'margin_rate': 0.086,
        #     'order_book_id': 'NQ',
        #     'trading_hours': '7*24',
        #     'type': 'future',
        #     'feeRate': 0.012
        # },
        {
            'contract_multiplier': 1,
            'exchange': '伦敦',
            'margin_rate': 0.1,
            'order_book_id': 'NID',
            'trading_hours': '7*24',
            'type': 'future',
            'feeRate': 0.012,
        },
        {
            'contract_multiplier': 1,
            'exchange': '伦敦',
            'margin_rate': 0.1,
            'order_book_id': 'ZSD',
            'trading_hours': '7*24',
            'type': 'future',
            'feeRate': 0.012,
        },
        # {
        #     'contract_multiplier': 1,
        #     'exchange': '美国',
        #     'margin_rate': 0.1,
        #     'order_book_id': 'SB',
        #     'trading_hours': '7*24',
        #     'type': 'future',
        #     'feeRate': 0.012
        # },
        {
            'contract_multiplier': 50,
            'exchange': '美豆',
            'margin_rate': 0.03,
            'order_book_id': 'S',
            'trading_hours': '7*24',
            'type': 'future',
            'feeRate': 0.012,
        },
        # {
        #     'contract_multiplier': 50,
        #     'exchange': '美玉米',
        #     'margin_rate': 0.06,
        #     'order_book_id': 'C',
        #     'trading_hours': '7*24',
        #     'type': 'future',
        #     'feeRate': 0.012
        # },
        {
            'contract_multiplier': 100,
            'exchange': '美豆粕',
            'margin_rate': 0.04,
            'order_book_id': 'SM',
            'trading_hours': '7*24',
            'type': 'future',
            'feeRate': 0.012,
        },
        {
            'contract_multiplier': 600,
            'exchange': '美豆油',
            'margin_rate': 0.04,
            'order_book_id': 'BO',
            'trading_hours': '7*24',
            'type': 'future',
            'feeRate': 0.012,
        },
        {
            'contract_multiplier': 1,
            'exchange': '美棉',
            'margin_rate': 0.1,
            'order_book_id': 'CT',
            'trading_hours': '7*24',
            'type': 'future',
            'feeRate': 0.012,
        },
        {
            'contract_multiplier': 1,
            'exchange': '马来西亚',
            'margin_rate': 0.1,
            'order_book_id': 'FCPO',
            'trading_hours': '7*24',
            'type': 'stock',
            'feeRate': 0.012,
        },
    ],
}
cfg: type[Config] = cast(
    type[Config], config[os.environ.get("FRESHQUANT_CONFIG_ENV", "default")]
)
config_path = os.path.expanduser('~')
config_path = '{}{}{}'.format(config_path, os.sep, '.freshquant')
settings = Dynaconf(
    settings_files=[
        os.path.join(BASE_DIR, "freshquant.yaml"),
        os.path.join(BASE_DIR, "freshquant.yml"),
        os.path.join(BASE_DIR, "freshquant.json"),
        os.path.join(EXE_DIR, "freshquant.yaml"),
        os.path.join(EXE_DIR, "freshquant.yml"),
        os.path.join(EXE_DIR, "freshquant.json"),
        os.path.join(config_path, "freshquant.yaml"),
        os.path.join(config_path, "freshquant.yml"),
        os.path.join(config_path, "freshquant.json"),
        os.path.join(CWD_DIR, "freshquant.yaml"),
        os.path.join(CWD_DIR, "freshquant.yml"),
        os.path.join(CWD_DIR, "freshquant.json"),
    ],
    includes=[
        os.path.join(BASE_DIR, "freshquant_*.yaml"),
        os.path.join(BASE_DIR, "freshquant_*.yml"),
        os.path.join(BASE_DIR, "freshquant_*.json"),
        os.path.join(EXE_DIR, "freshquant_*.yaml"),
        os.path.join(EXE_DIR, "freshquant_*.yml"),
        os.path.join(EXE_DIR, "freshquant_*.json"),
        os.path.join(config_path, "freshquant_*.yaml"),
        os.path.join(config_path, "freshquant_*.yml"),
        os.path.join(config_path, "freshquant_*.json"),
        os.path.join(CWD_DIR, "freshquant_*.yaml"),
        os.path.join(CWD_DIR, "freshquant_*.yml"),
        os.path.join(CWD_DIR, "freshquant_*.json"),
    ],
    envvar_prefix="freshquant",
)

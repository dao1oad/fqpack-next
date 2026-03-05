import pandas as pd

from freshquant.database.cache import in_memory_cache
from freshquant.database.mongodb import DBQuantAxis

CN_FUTURE_PRODUCT_TABLE = [
    ["name", "tdx_product_code", "tdx_month_code_len", "tq_product_code", "tq_month_code_len", "wh_product_code", "wh_month_code_len", "exchange_code"],
    ["沪深300股指", "IF", 4, "IF", 4, "IF", 4, "CFFEX"],
    ["上证50股指", "IH", 4, "IH", 4, "IH", 4, "CFFEX"],
    ["中证500股指", "IC", 4, "IC", 4, "IC", 4, "CFFEX"],
    ["中证1000股指", "IM", 4, "IM", 4, "IM", 4, "CFFEX"],
    ["二年债", "TS", 4, "TS", 4, "TS", 4, "CFFEX"],
    ["五年债", "TF", 4, "TF", 4, "TF", 4, "CFFEX"],
    ["十年债", "T", 4, "T", 4, "T", 4, "CFFEX"],
    ["三十年债", "TL", 4, "TL", 4, "TL", 4, "CFFEX"],
    ["沪金", "AU", 4, "au", 4, "au", 4, "SHFE"],
    ["沪银", "AG", 4, "ag", 4, "ag", 4, "SHFE"],
    ["沪铜", "CU", 4, "cu", 4, "cu", 4, "SHFE"],
    ["沪铝", "AL", 4, "al", 4, "al", 4, "SHFE"],
    ["沪锌", "ZN", 4, "zn", 4, "zn", 4, "SHFE"],
    ["沪铅", "PB", 4, "pb", 4, "pb", 4, "SHFE"],
    ["沪镍", "NI", 4, "ni", 4, "ni", 4, "SHFE"],
    ["沪锡", "SN", 4, "sn", 4, "sn", 4, "SHFE"],
    ["国际铜", "BC", 4, "bc", 4, "bc", 4, "INE"],
    ["工业硅", "SI", 4, "si", 4, "si", 4, "GFEX"],
    ["螺纹钢", "RB", 4, "rb", 4, "rb", 4, "SHFE"],
    ["铁矿石", "I", 4, "i", 4, "i", 4, "DCE"],
    ["热卷", "HC", 4, "hc", 4, "hc", 4, "SHFE"],
    ["不锈钢", "SS", 4, "ss", 4, "ss", 4, "SHFE"],
    ["线材", "WR", 4, "wr", 4, "wr", 4, "SHFE"],
    ["硅铁", "SF", 4, "SF", 3, "SF", 3, "CZCE"],
    ["锰硅", "SM", 4, "SM", 3, "SM", 3, "CZCE"],
    ["焦煤", "JM", 4, "jm", 4, "jm", 4, "DCE"],
    ["焦炭", "J", 4, "j", 4, "j", 4, "DCE"],
    ["动力煤", "ZC", 4, "ZC", 3, "ZC", 3, "CZCE"],
    ["玻璃", "FG", 4, "FG", 3, "FG", 3, "CZCE"],
    ["纸浆", "SP", 4, "sp", 4, "sp", 4, "SHFE"],
    ["纤维板", "FB", 4, "fb", 4, "fb", 4, "DCE"],
    ["胶合板", "BB", 4, "bb", 4, "bb", 4, "DCE"],
    ["原油", "SC", 4, "sc", 4, "sc", 4, "INE"],
    ["燃油", "FU", 4, "fu", 4, "fu", 4, "SHFE"],
    ["低硫油", "LU", 4, "lu", 4, "lu", 4, "INE"],
    ["沥青", "BU", 4, "bu", 4, "bu", 4, "SHFE"],
    ["液化气", "PG", 4, "pg", 4, "pg", 4, "DCE"],
    ["PTA", "TA", 4, "TA", 3, "TA", 3, "CZCE"],
    ["PVC", "V", 4, "v", 4, "v", 4, "DCE"],
    ["橡胶", "RU", 4, "ru", 4, "ru", 4, "SHFE"],
    ["20号胶", "NR", 4, "nr", 4, "nr", 4, "INE"],
    ["塑料", "L", 4, "l", 4, "l", 4, "DCE"],
    ["短纤", "PF", 4, "PF", 3, "PF", 3, "CZCE"],
    ["乙二醇", "EG", 4, "eg", 4, "eg", 4, "DCE"],
    ["甲醇", "MA", 4, "MA", 3, "MA", 3, "CZCE"],
    ["聚丙烯", "PP", 4, "pp", 4, "pp", 4, "DCE"],
    ["苯乙烯", "EB", 4, "eb", 4, "eb", 4, "DCE"],
    ["尿素", "UR", 4, "UR", 3, "UR", 3, "CZCE"],
    ["纯碱", "SA", 4, "SA", 3, "SA", 3, "CZCE"],
    ["玉米", "C", 4, "c", 4, "c", 4, "DCE"],
    ["豆一", "A", 4, "a", 4, "a", 4, "DCE"],
    ["淀粉", "CS", 4, "cs", 4, "cs", 4, "DCE"],
    ["强麦", "WH", 4, "WH", 3, "WH", 3, "CZCE"],
    ["普麦", "PM", 4, "PM", 3, "PM", 3, "CZCE"],
    ["粳米", "RR", 4, "rr", 4, "rr", 4, "DCE"],
    ["早籼稻", "RI", 4, "RI", 3, "RI", 3, "CZCE"],
    ["粳稻", "JR", 4, "JR", 3, "JR", 3, "CZCE"],
    ["晚籼稻", "LR", 4, "LR", 3, "LR", 3, "CZCE"],
    ["豆二", "B", 4, "b", 4, "b", 4, "DCE"],
    ["豆粕", "M", 4, "m", 4, "m", 4, "DCE"],
    ["豆油", "Y", 4, "y", 4, "y", 4, "DCE"],
    ["油菜籽", "RS", 4, "RS", 3, "RS", 3, "CZCE"],
    ["菜籽粕", "RM", 4, "RM", 3, "RM", 3, "CZCE"],
    ["菜籽油", "OI", 4, "OI", 3, "OI", 3, "CZCE"],
    ["棕榈油", "P", 4, "p", 4, "p", 4, "DCE"],
    ["花生", "PK", 4, "PK", 3, "PK", 3, "CZCE"],
    ["棉花", "CF", 4, "CF", 3, "CF", 3, "CZCE"],
    ["白糖", "SR", 4, "SR", 3, "SR", 3, "CZCE"],
    ["棉纱", "CY", 4, "CY", 3, "CY", 3, "CZCE"],
    ["鸡蛋", "JD", 4, "jd", 4, "jd", 4, "DCE"],
    ["生猪", "LH", 4, "lh", 4, "lh", 4, "DCE"],
    ["苹果", "AP", 4, "AP", 3, "AP", 3, "CZCE"],
    ["红枣", "CJ", 4, "CJ", 3, "CJ", 3, "CZCE"],
]


def query_cn_future_product_table() -> pd.DataFrame:
    return pd.DataFrame(
        CN_FUTURE_PRODUCT_TABLE[1:],
        columns=CN_FUTURE_PRODUCT_TABLE[0],
    )


@in_memory_cache.memoize(expiration=3600)
def query_future_map() -> dict:
    future_list = list(DBQuantAxis.future_list.find({}))
    future_map = {}
    for future in future_list:
        k3 = f'{future["code"]}'
        future_map[k3] = {
            "code": future["code"],
            "name": future["name"],
            "market": future["market"],
            "category": future["category"],
            "desc": future["desc"],
        }
    return future_map

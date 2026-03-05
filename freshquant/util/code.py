import pydash

from freshquant.database.cache import in_memory_cache
from freshquant.instrument.bond import query_bond_map
from freshquant.instrument.etf import query_etf_map
from freshquant.instrument.index import query_index_map
from freshquant.instrument.stock import query_stock_map


@in_memory_cache.memoize(expiration=864000)
def fq_util_code_append_market_code(code, upper_case=False):
    code = str(code).zfill(6)
    inst = pydash.get(query_stock_map(), code)
    if inst is None:
        inst = pydash.get(query_etf_map(), code)
    if inst is None:
        inst = pydash.get(query_bond_map(), code)
    if inst is None:
        inst = pydash.get(query_index_map(), code)
    if inst is not None:
        return inst["sse"].upper() + code if upper_case else inst["sse"].lower() + code
    return code


@in_memory_cache.memoize(expiration=864000)
def fq_util_code_append_market_code_suffix(code, upper_case=True):
    inst = pydash.get(query_stock_map(), code)
    if inst is None:
        inst = pydash.get(query_etf_map(), code)
    if inst is None:
        inst = pydash.get(query_bond_map(), code)
    if inst is None:
        inst = pydash.get(query_index_map(), code)
    if inst is not None:
        return (
            code + "." + inst["sse"].upper()
            if upper_case
            else code + "." + inst["sse"].lower()
        )
    return code


def normalize_to_base_code(code: str) -> str:
    """
    将输入代码标准化为6位数字基础代码（不含前缀/后缀），用于在映射表中查询交易所信息。
    支持以下输入：
    - "002808"
    - "002808.SZ"
    - "sz002808" / "SZ002808"
    """
    s = str(code).strip()
    if not s:
        return s

    s = s.upper()

    # 处理形如 "SZ002808" / "SH603517"
    if (s.startswith("SZ") or s.startswith("SH")) and len(s) >= 8:
        s = s[2:]

    # 处理形如 "002808.SZ"
    if "." in s:
        parts = s.split(".")
        if parts and parts[0].isdigit():
            s = parts[0]

    # 保留6位数字
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits.zfill(6) if digits else s


def normalize_to_inst_code_with_suffix(code: str) -> str:
    """
    将任意格式的代码标准化为 '000000.SZ/SH' 格式。
    """
    base_code = normalize_to_base_code(code)
    return fq_util_code_append_market_code_suffix(base_code, upper_case=True)


if __name__ == "__main__":
    print(fq_util_code_append_market_code("159629"))

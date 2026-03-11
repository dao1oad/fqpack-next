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


def infer_cn_security_prefixed_code(code: str) -> str | None:
    """
    将中国证券代码标准化为 `sz000001` / `sh600000` 形式。

    当证券映射表不可用时，仍对常见 6 位 A 股/ETF 代码做保守兜底：
    - `6* / 5* / 9*` 归为 `sh`
    - 其余 6 位代码默认归为 `sz`
    """
    raw = str(code or "").strip()
    if not raw:
        return None

    upper = raw.upper()
    if len(upper) == 8 and upper[:2] in {"SH", "SZ"} and upper[2:].isdigit():
        return upper[:2].lower() + upper[2:]

    if len(upper) == 9 and upper[:6].isdigit() and upper[6:] in {".SH", ".SZ"}:
        return upper[7:].lower() + upper[:6]

    if not (len(upper) == 6 and upper.isdigit()):
        return None

    mapped = fq_util_code_append_market_code(upper, upper_case=False)
    if mapped != upper:
        return mapped.lower()

    prefix = "sh" if upper.startswith(("5", "6", "9")) else "sz"
    return prefix + upper


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

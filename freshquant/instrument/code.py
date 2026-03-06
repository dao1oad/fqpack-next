import pandas as pd
import pendulum

from freshquant.database.cache import in_memory_cache
from freshquant.instrument.future import query_cn_future_product_table


@in_memory_cache.memoize(expiration=864000)
def extract_code_alpha_prefix(code):
    prefix = ""
    for char in code:
        if char.isalpha():
            prefix += char
        else:
            break
    return prefix


@in_memory_cache.memoize(expiration=864000)
def convert_code_tdx_to_tq(code: str):
    productTable: pd.DataFrame = query_cn_future_product_table()
    tdxProductCode = extract_code_alpha_prefix(code)
    products = productTable[productTable["tdx_product_code"] == tdxProductCode]
    productId = products["tq_product_code"].values[0]
    productTable = productTable[productTable["tq_month_code_len"] == 3]
    if productId in productTable.tq_product_code.to_list() and len(code) == 6:
        code = productId + code[len(productId) + 1 : 6]
    else:
        code = productId + code[len(productId) :]
    return code


@in_memory_cache.memoize(expiration=864000)
def convert_code_tq_to_tdx(code: str):
    productTable: pd.DataFrame = query_cn_future_product_table()
    tqProductCode = extract_code_alpha_prefix(code)
    products = productTable[productTable["tq_product_code"] == tqProductCode]
    productId = products["tdx_product_code"].values[0]
    productTable = productTable[productTable["tq_month_code_len"] == 3]
    if productId in productTable.tq_product_code.to_list() and len(code) == 6:
        code = productId + str(pendulum.now().year)[0] + code[len(productId) :]
    else:
        code = productId + code[len(productId) :]
    return code


@in_memory_cache.memoize(expiration=864000)
def convert_code_wh_to_tdx(code: str):
    """
    将文华格式的期货代码转换为通达信格式。
    
    :param code: 文华格式的期货代码
    :return: 通达信格式的期货代码
    """
    productTable: pd.DataFrame = query_cn_future_product_table()
    whProductCode = extract_code_alpha_prefix(code)
    products = productTable[productTable["wh_product_code"] == whProductCode]
    if products.empty:
        raise ValueError(f"无法识别的文华期货代码: {code}")

    productId = products["tdx_product_code"].values[0]
    month_code_len = products["tdx_month_code_len"].values[0]

    if month_code_len == 4:
        year = str(pendulum.now().year)[-2:]
        month_code = code[len(whProductCode):]
        code = f"{productId}{year}{month_code}"
    elif month_code_len == 3:
        month_code = code[len(whProductCode):]
        code = f"{productId}{month_code}"
    else:
        raise ValueError(f"不支持的月份代码长度: {month_code_len}")

    return code


@in_memory_cache.memoize(expiration=864000)
def identify_futures_code(code: str) -> str:
    """
    根据给定的期货代码，判断其属于哪个软件的编码格式。
    
    :param code: 期货代码
    :return: 软件名称 ('TQ', 'TDX', 'WH')
    """
    product_table = query_cn_future_product_table()
    for _, row in product_table.iterrows():
        tdx_product_code = row['tdx_product_code']
        tdx_month_code_len = row['tdx_month_code_len']
        tq_product_code = row['tq_product_code']
        tq_month_code_len = row['tq_month_code_len']
        wh_product_code = row['wh_product_code']
        wh_month_code_len = row['wh_month_code_len']
        
        prefix = extract_code_alpha_prefix(code)
        month_code = code[len(prefix):]

        if prefix == tdx_product_code and len(month_code) == tdx_month_code_len:
            return 'TDX'
        elif prefix == tq_product_code and len(month_code) == tq_month_code_len:
            return 'TQ'
        elif prefix == wh_product_code and len(month_code) == wh_month_code_len:
            return 'WH'
    raise ValueError(f"无法识别的期货代码: {code}")


@in_memory_cache.memoize(expiration=864000)
def convert_code_wh_to_tq(code: str) -> str:
    """
    将文华格式的期货代码转换为天勤格式。
    
    :param code: 文华格式的期货代码
    :return: 天勤格式的期货代码
    """
    productTable: pd.DataFrame = query_cn_future_product_table()
    whProductCode = extract_code_alpha_prefix(code)
    products = productTable[productTable["wh_product_code"] == whProductCode]
    if products.empty:
        raise ValueError(f"无法识别的文华期货代码: {code}")

    productId = products["tq_product_code"].values[0]
    month_code_len = products["tq_month_code_len"].values[0]

    if month_code_len == 4:
        year = str(pendulum.now().year)[-2:]
        month_code = code[len(whProductCode):]
        code = f"{productId}{year}{month_code}"
    elif month_code_len == 3:
        month_code = code[len(whProductCode):]
        code = f"{productId}{month_code}"
    else:
        raise ValueError(f"不支持的月份代码长度: {month_code_len}")

    return code


@in_memory_cache.memoize(expiration=864000)
def convert_code_to_tdx(code: str) -> str:
    """
    将任意格式的期货代码转换为通达信的格式。
    
    :param code: 期货代码
    :return: 通达信格式的期货代码
    """
    code_format = identify_futures_code(code)
    if code_format == 'TDX':
        return code
    elif code_format == 'TQ':
        return convert_code_tq_to_tdx(code)
    elif code_format == 'WH':
        return convert_code_wh_to_tdx(code)
    else:
        raise ValueError(f"无法识别的期货代码格式: {code}")


@in_memory_cache.memoize(expiration=864000)
def convert_code_to_tq(code: str) -> str:
    """
    将任意格式的期货代码转换为天勤的格式。
    
    :param code: 期货代码
    :return: 天勤格式的期货代码
    """
    code_format = identify_futures_code(code)
    if code_format == 'TQ':
        return code
    elif code_format == 'TDX':
        return convert_code_tdx_to_tq(code)
    elif code_format == 'WH':
        return convert_code_wh_to_tq(code)
    else:
        raise ValueError(f"无法识别的期货代码格式: {code}")

if __name__ == "__main__":
    print(convert_code_to_tq("c2405"))

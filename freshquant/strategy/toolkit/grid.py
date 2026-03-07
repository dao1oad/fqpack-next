import numpy as np
import pandas as pd


def plan_grid_distribution(
    ceiling_price: float,
    floor_price: float,
    amount: float,
    quantity: int,
    grid_num: int = 10,
    lot_shares: int = 100,
) -> pd.DataFrame:
    """
    计划网格交易的价格和数量分布。使用等百分比间隔的价格网格，按价格倒数分配交易数量。

    Args:
        ceiling_price (float): 网格上限价格
        floor_price (float): 网格下限价格
        amount (float): 计划投入的总金额
        quantity (int): 计划交易的总数量
        grid_num (int, optional): 网格数量，默认为10
        lot_shares (int, optional): 每手股数，默认为100，确保交易数量为手数的整数倍

    Returns:
        pd.DataFrame: 包含以下列的数据框（按价格从高到低排序）：
            - price: 网格价格
            - quantity: 该价格对应的交易数量
            - amount: 该价格层级的交易金额
            - amount_adjust: 总金额调整系数，用于将实际总金额调整至目标金额

    Notes:
        - 实际网格数可能少于指定的grid_num，因为要满足手数整数倍的约束
        - 分配原则是价格越低配置越多的数量，使用价格倒数作为权重
    """
    # 采用等百分比间隔价格（从低到高）
    # 计算等百分比步长
    step_percent = (ceiling_price / floor_price - 1) / (grid_num - 1)
    # 按百分比创建价格网格
    base_prices = [floor_price * (1 + step_percent * i) for i in range(grid_num)]
    if base_prices[-1] < ceiling_price:
        base_prices[-1] = ceiling_price  # 确保最高价为ceiling_price
    base_prices = np.array(base_prices)  # 按价格的倒数分配权重
    base_weights = 1 / base_prices
    base_weights /= base_weights.sum()  # 归一化

    base_quantities = base_weights * quantity
    # 调整为手数整数倍
    quantities = []
    remaining = quantity
    for i in range(grid_num):
        q = base_quantities[i]
        if i == grid_num - 1:
            q = remaining  # 最后一个网格获取剩余股数
        else:
            q = max(0, min(q, remaining, quantity))  # 保证非负且不超过剩余量
            if q > 0:
                q = round(q / lot_shares) * lot_shares  # 调整为手数整数倍
                q = min(q, remaining)  # 不超过剩余量
            else:
                q = lot_shares if remaining >= lot_shares else remaining

        quantities.append(q)
        remaining -= q
        if remaining <= 0:
            quantities.extend([0] * (grid_num - i - 1))
            break

    # 反转价格和数量：高价格在前
    prices = base_prices[::-1]
    quantities = quantities[::-1]
    amounts = [q * p for q, p in zip(quantities, prices)]
    total_amount = sum(amounts)
    # 计算金额调整系数
    amount_adjust = amount / total_amount if abs(total_amount) > 1e-8 else 1.0

    # 创建数据帧（高价格在前）
    df = pd.DataFrame(
        {
            "price": prices,
            "quantity": quantities,
            "amount": amounts,
            "amount_adjust": amount_adjust,
        }
    )
    # 删除0数量行
    df = df[df["quantity"] > 0]

    # 计算相邻价格差和涨幅百分比（相对于下一行的涨幅）
    # 使用shift(-1)获取下一行的价格，因为价格是从高到低排序的
    next_prices = df["price"].shift(-1)  # 获取下一行的价格
    df["price_diff"] = df["price"] - next_prices  # 当前价格减去下一行价格
    df["price_percent"] = df["price_diff"] / next_prices * 100  # 相对下一行的涨幅百分比

    # 最后一行的差价和百分比设为NaN，因为没有下一个价格了
    df.loc[df.index[-1], ["price_diff", "price_percent"]] = float("nan")

    return df

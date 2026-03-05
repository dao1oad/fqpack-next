from fqcopilot import fq_clxs  # type: ignore
from fqchan04 import fq_recognise_bi  # type: ignore


def locate_macd_divergence(datetime_list, high_list, low_list, open_list, close_list, bi_list=None, min_pivot_num=2):
    """
    使用fq_clxs函数计算MACD背驰信号

    Args:
        datetime_list: 日期时间列表
        high_list: 最高价列表
        low_list: 最低价列表
        close_list: 收盘价列表
        bi_list: 笔信号列表（可选，用于确定止损价格，不传时内部计算）

    Returns:
        dict: 包含看涨和看跌背离信号的字典
    """
    length = len(datetime_list)

    # 如果没有提供笔信号数据，内部计算
    if bi_list is None:
        bi_list = fq_recognise_bi(length, high_list, low_list)

    # 使用默认成交量数据
    volume_list = [1.0] * length

    # 初始化结果
    bullish_divergence = {
        'idx': [],
        'datetime': [],
        'price': [],
        'stop_lose_price': [],
        'zhongshu_count': [],
        'tag': []
    }

    bearish_divergence = {
        'idx': [],
        'datetime': [],
        'price': [],
        'stop_lose_price': [],
        'zhongshu_count': [],
        'tag': []
    }

    try:
        # 使用fq_clxs计算背驰信号，model_opt=8表示计算背驰信号
        clxs_signals = fq_clxs(
            length,
            high_list,
            low_list,
            open_list,
            close_list,
            volume_list,
            wave_opt=1560,    # 默认参数
            stretch_opt=0,    # 默认参数
            trend_opt=1,      # 默认参数
            model_opt=8       # 8表示计算背驰信号
        )

        # 遍历信号，寻找背驰点
        for i in range(length):
            signal_value = int(clxs_signals[i])

            if signal_value == 0:
                continue

            # 计算中枢个数
            zhongshu_count = abs(signal_value) // 100

            # 只保留中枢个数大于等于2的信号
            if zhongshu_count < min_pivot_num:
                continue

            # 看涨背驰信号 (正值)
            if signal_value > 0:
                # 寻找止损价格：往前找最近的笔底
                stop_loss_price = None
                for j in range(i, -1, -1):
                    if bi_list[j] == -1:
                        stop_loss_price = low_list[j]
                        break

                # 如果没有找到止损价格，使用当前价格下方5%
                if stop_loss_price is None:
                    stop_loss_price = close_list[i] * 0.95

                bullish_divergence['idx'].append(i)
                bullish_divergence['datetime'].append(datetime_list[i])
                bullish_divergence['price'].append(close_list[i])
                bullish_divergence['stop_lose_price'].append(stop_loss_price)
                bullish_divergence['zhongshu_count'].append(zhongshu_count)
                bullish_divergence['tag'].append('')

            # 看跌背驰信号 (负值)
            elif signal_value < 0:
                # 寻找止损价格：往前找最近的笔顶
                stop_loss_price = None
                for j in range(i, -1, -1):
                    if bi_list[j] == 1:
                        stop_loss_price = high_list[j]
                        break

                # 如果没有找到止损价格，使用当前价格上方5%
                if stop_loss_price is None:
                    stop_loss_price = close_list[i] * 1.05

                bearish_divergence['idx'].append(i)
                bearish_divergence['datetime'].append(datetime_list[i])
                bearish_divergence['price'].append(close_list[i])
                bearish_divergence['stop_lose_price'].append(stop_loss_price)
                bearish_divergence['zhongshu_count'].append(zhongshu_count)
                bearish_divergence['tag'].append('')

    except Exception as e:
        # 如果fq_clxs调用失败，返回空结果
        print(f"Error calling fq_clxs: {e}")

    return {
        'bullish': bullish_divergence,
        'bearish': bearish_divergence
    }

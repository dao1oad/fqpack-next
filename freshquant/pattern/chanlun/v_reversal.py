from fqchan04 import fq_recognise_bi  # type: ignore
from fqcopilot import fq_clxs  # type: ignore


def locate_v_reversal(
    datetime_list, high_list, low_list, open_list, close_list, bi_list=None
):
    result = {
        "buy_v_reverse": {
            "idx": [],
            "datetime": [],
            "price": [],
            "stop_lose_price": [],
            "tag": [],
        },
        "sell_v_reverse": {
            "idx": [],
            "datetime": [],
            "price": [],
            "stop_lose_price": [],
            "tag": [],
        },
    }
    length = len(datetime_list)
    # 如果没有提供笔信号数据，内部计算
    if bi_list is None:
        bi_list = fq_recognise_bi(length, high_list, low_list)
    try:
        # 使用fq_clxs计算V反信号，model_opt=12表示计算V反信号
        # 使用默认成交量数据，信号计算不需要引用成交量
        volume_list = [1.0] * length
        clxs_signals = fq_clxs(
            length,
            high_list,
            low_list,
            open_list,
            close_list,
            volume_list,
            wave_opt=1560,  # 默认参数
            stretch_opt=0,  # 默认参数
            trend_opt=0,  # 默认参数
            model_opt=12,  # 12表示计算V反信号
        )

        # 遍历信号，寻找V反点
        for i in range(length):
            signal_value = int(clxs_signals[i])

            if signal_value == 0:
                continue

            # 买入V反信号 (正值)
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

                result["buy_v_reverse"]['idx'].append(i)
                result["buy_v_reverse"]['datetime'].append(datetime_list[i])
                result["buy_v_reverse"]['price'].append(close_list[i])
                result["buy_v_reverse"]['stop_lose_price'].append(stop_loss_price)
                result["buy_v_reverse"]['tag'].append('')

            # 卖出V反信号 (负值)
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

                result["sell_v_reverse"]['idx'].append(i)
                result["sell_v_reverse"]['datetime'].append(datetime_list[i])
                result["sell_v_reverse"]['price'].append(close_list[i])
                result["sell_v_reverse"]['stop_lose_price'].append(stop_loss_price)
                result["sell_v_reverse"]['tag'].append('')

    except Exception as e:
        # 如果fq_clxs调用失败，返回空结果
        print(f"Error calling fq_clxs: {e}")
    return result

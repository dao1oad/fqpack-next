#pragma once

#include "../indicator/indicator.h"
#include "copilot.h"

class SignalUtils {
public:
    static EntrypointType is_buy_signal(int n, 
                            const std::vector<float>& high,
                            const std::vector<float>& low,
                            const std::vector<float>& open,
                            const std::vector<float>& close,
                            const std::vector<float>& vol,
                            const std::vector<float>& wave_sigs,
                            const std::vector<StdBar>& std_bars,
                            const std::vector<float>& ma5,
                            const std::vector<float>& macd,
                            const float support_price = 0)
    {
        // 是不是pinbar产生信号
        if (n >= 0 && is_pinbar(high[n], low[n], open[n], close[n]) == 1 && 
            (support_price == 0 || close[n] > support_price)) {
            return EntrypointType::ENTRYPOINT_BUY_OPEN_2;
        }
        // 是不是吞没反包产生信号
        if (n >= 1 && is_engulfing(high[n - 1], low[n - 1], open[n - 1], close[n - 1], 
                        high[n], low[n], open[n], close[n]) == 1 &&
            (support_price == 0 || close[n] > support_price)) {
            return EntrypointType::ENTRYPOINT_BUY_OPEN_3;
        }
        // 是不是强底分型
        auto strong_factors = STRONG_FACTAL(high, low, open, close, wave_sigs, std_bars);
        if (n >=0 && strong_factors[n] == 1 && 
            (support_price == 0 || close[n] > support_price)) {
            return EntrypointType::ENTRYPOINT_BUY_OPEN_4;
        }
        // 是不是MA5拐头
        if (n >= 2 && ma5[n] > ma5[n - 1] && ma5[n - 1] <= ma5[n - 2] &&
            (support_price == 0 || close[n] > support_price)) {
            return EntrypointType::ENTRYPOINT_BUY_OPEN_5;
        }
        // 是不是量价齐升
        if (n >= 1 && is_price_vol_rising(open[n - 1], close[n - 1], vol[n - 1], 
                                        open[n], close[n], vol[n]) == 1 &&
            (support_price == 0 || close[n] > support_price)) {
            return EntrypointType::ENTRYPOINT_BUY_OPEN_6;
        }
        // 是不是MACD金叉的买点
        if (n >= 1 && macd[n] > 0 && macd[n - 1] <= 0 &&
            (support_price == 0 || close[n] > support_price)) {
            return EntrypointType::ENTRYPOINT_BUY_OPEN_7;
        }
        return EntrypointType::ENTRYPOINT_UNKNOWN;
    }

    static EntrypointType is_sell_signal(int n,
                             const std::vector<float>& high,
                             const std::vector<float>& low,
                             const std::vector<float>& open,
                             const std::vector<float>& close,
                             const std::vector<float>& vol,
                             const std::vector<float>& wave_sigs,
                             const std::vector<StdBar>& std_bars,
                             const std::vector<float>& ma5,
                            const std::vector<float>& macd,
                             const float resistance_price = 0)
    {
        // 是不是pinbar产生信号
        if (n >= 0 && is_pinbar(high[n], low[n], open[n], close[n]) == -1 && 
            (resistance_price == 0 || close[n] < resistance_price)) {
            return EntrypointType::ENTRYPOINT_SELL_OPEN_2;
        }
        // 是不是吞没反包产生信号
        if (n >= 1 && is_engulfing(high[n - 1], low[n - 1], open[n - 1], close[n - 1], 
                        high[n], low[n], open[n], close[n]) == -1 &&
            (resistance_price == 0 || close[n] < resistance_price)) {
            return EntrypointType::ENTRYPOINT_SELL_OPEN_3;
        }
        // 是不是强顶分型
        auto strong_factors = STRONG_FACTAL(high, low, open, close, wave_sigs, std_bars);
        if (n >= 0 && strong_factors[n] == -1 && 
            (resistance_price == 0 || close[n] < resistance_price)) {
            return EntrypointType::ENTRYPOINT_SELL_OPEN_4;
        }
        // 是不是MA5拐头
        if (n >= 2 && ma5[n] < ma5[n - 1] && ma5[n - 1] >= ma5[n - 2] &&
            (resistance_price == 0 || close[n] < resistance_price)) {
            return EntrypointType::ENTRYPOINT_SELL_OPEN_5;
        }
        // 是不是量价齐跌
        if (n >= 1 && is_price_vol_rising(open[n - 1], close[n - 1], vol[n - 1], 
                                        open[n], close[n], vol[n]) == -1 &&
            (resistance_price == 0 || close[n] < resistance_price)) {
            return EntrypointType::ENTRYPOINT_SELL_OPEN_6;
        }
        // 是不是MACD死叉的卖点
        if (n >= 1 && macd[n] < 0 && macd[n - 1] >= 0 &&
            (resistance_price == 0 || close[n] < resistance_price)) {
            return EntrypointType::ENTRYPOINT_SELL_OPEN_7;
        }
        return EntrypointType::ENTRYPOINT_UNKNOWN;
    }
};

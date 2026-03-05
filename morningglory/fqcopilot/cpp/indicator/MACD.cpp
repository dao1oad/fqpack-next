#include <vector>
#include <cmath>
#include <numeric>
#include "indicator.h"

// 计算EMA（指数移动平均线）
std::vector<float> EMA(const std::vector<float>& prices, int period) {
    int size = static_cast<int>(prices.size());
    std::vector<float> ema(size, 0.0f);
    if (period <= 0 || size < period) {
        return ema;
    }

    float k = 2.0f / (period + 1);
    ema[0] = prices[0];

    for (int i = 1; i < size; ++i) {
        ema[i] = (prices[i] - ema[i - 1]) * k + ema[i - 1];
    }

    return ema;
}

// 计算DIF（差离值）
std::vector<float> DIF(const std::vector<float>& prices, int short_period, int long_period) {
    std::vector<float> short_ema = EMA(prices, short_period);
    std::vector<float> long_ema = EMA(prices, long_period);

    std::vector<float> dif(prices.size(), 0.0f);
    for (size_t i = 0; i < prices.size(); ++i) {
        dif[i] = short_ema[i] - long_ema[i];
    }

    return dif;
}

// 计算DEA（差离平均值）
std::vector<float> DEA(const std::vector<float>& dif, int signal_period) {
    return EMA(dif, signal_period);
}

// 计算MACD（指数平滑异同移动平均线）
std::tuple<std::vector<float>, std::vector<float>, std::vector<float>> MACD(const std::vector<float>& prices, int short_period, int long_period, int signal_period) {
    std::vector<float> dif = DIF(prices, short_period, long_period);
    std::vector<float> dea = DEA(dif, signal_period);

    std::vector<float> macd(prices.size(), 0.0f);
    for (size_t i = 0; i < prices.size(); ++i) {
        macd[i] = (dif[i] - dea[i]) * 2;
    }

    return {dif, dea, macd};
}

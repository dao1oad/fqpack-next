#pragma once

// Function prototype for MA calculation
#include <vector>
#include <stdexcept>
#include <cmath> // For std::nan
#include "../chanlun/czsc.h"

// Function prototype for Pinbar detection
int is_pinbar(float high, float low, float open, float close);

// Function prototype for Engulfing pattern detection
int is_engulfing(
    float prev_high, float prev_low, float prev_open, float prev_close,
    float curr_high, float curr_low, float curr_open, float curr_close);

// Function prototype for Rising detection
int is_price_vol_rising(float prev_open, float prev_close, float prev_vol, float curr_open, float curr_close, float curr_vol);

// Function prototype for MA calculation
std::vector<float> MA(const std::vector<float> &prices, const int period);

std::vector<float> STRONG_FACTAL(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &bi, const std::vector<StdBar> &std_bars);

std::vector<float> NORMAL_FACTAL(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &bi, const std::vector<StdBar> &std_bars);

// Function prototype for ATR calculation
std::vector<float> ATR(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &close,
    const int period);

// Function prototype for EMA calculation
std::vector<float> EMA(const std::vector<float>& prices, int period);

// Function prototype for DIF calculation
std::vector<float> DIF(const std::vector<float>& prices, int short_period, int long_period);

// Function prototype for DEA calculation
std::vector<float> DEA(const std::vector<float>& dif, int signal_period);

// Function prototype for MACD calculation
std::tuple<std::vector<float>, std::vector<float>, std::vector<float>> MACD(const std::vector<float>& prices, int short_period, int long_period, int signal_period);

#include "indicator.h"
#include <algorithm> // For std::max
#include <cmath> // For std::nan
#include <stdexcept>

// Function to calculate the Average True Range
std::vector<float> ATR(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &close,
    const int period) {

    int size = static_cast<int>(high.size());
    // Initialize result vector with NaN
    std::vector<float> atr(high.size(), 0.0f);
    
    // Check input sizes match
    if (high.size() != low.size() || high.size() != close.size()) {
        return atr;
    }
    
    // Need at least period+1 values to calculate ATR
    if (period <= 0 || size < period + 1) {
        return atr;
    }
    
    // Calculate True Range for each period
    std::vector<float> tr(high.size());
    for (size_t i = 1; i < high.size(); ++i) {
        float hl = high[i] - low[i];
        float hc = std::fabs(high[i] - close[i-1]);
        float lc = std::fabs(low[i] - close[i-1]);
        tr[i] = std::max({hl, hc, lc});
    }
    
    // Calculate first ATR value as simple average of first period TRs
    float atr_sum = 0.0f;
    for (int i = 1; i <= period; ++i) {
        atr_sum += tr[i];
    }
    atr[period] = atr_sum / period;
    
    // Calculate subsequent ATR values using Wilder's smoothing method
    for (int i = period + 1; i < size; ++i) {
        atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period;
    }
    
    return atr;
}

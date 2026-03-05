// Function to calculate the Moving Average
#include "indicator.h"
#include <numeric> // For std::accumulate
#include <stdexcept>
#include <cmath> // For std::nan

// Function to calculate the Moving Average
std::vector<float> MA(const std::vector<float>& prices, const int period) {
    int size = static_cast<int>(prices.size());
    std::vector<float> ma(size, 0.0f);
    if (period <= 0 || size < period) {
        return ma;
    }

    for (int i = 0; i < period - 1; ++i) {
        ma[i] = std::accumulate(prices.begin(), prices.begin() + i + 1, 0.0f) / (i + 1);
    }
    for (int i = period - 1; i < size; ++i) {
        ma[i] = std::accumulate(prices.begin() + i - period + 1, prices.begin() + i + 1, 0.0f) / period;
    }

    return ma;
}

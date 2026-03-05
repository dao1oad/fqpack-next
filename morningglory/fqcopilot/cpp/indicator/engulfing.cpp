#include "indicator.h"

// Function to check if two consecutive bars form an engulfing pattern
int is_engulfing(
    float prev_high, float prev_low, float prev_open, float prev_close,
    float curr_high, float curr_low, float curr_open, float curr_close)
{
    // Calculate the body size of the previous and current bars
    float prev_body = std::abs(prev_close - prev_open);
    float curr_body = std::abs(curr_close - curr_open);

    // Calculate the upper and lower wicks of the previous and current bars
    float prev_upper_wick = prev_high - std::max(prev_open, prev_close);
    float prev_lower_wick = std::min(prev_open, prev_close) - prev_low;
    float curr_upper_wick = curr_high - std::max(curr_open, curr_close);
    float curr_lower_wick = std::min(curr_open, curr_close) - curr_low;

    // Check if the body size is at least 2 times the size of the wicks
    if (prev_body < 2 * prev_upper_wick || prev_body < 2 * prev_lower_wick ||
        curr_body < 2 * curr_upper_wick || curr_body < 2 * curr_lower_wick)
    {
        return 0;
    }

    // Check for bullish engulfing pattern with body size condition
    if (prev_close < prev_open && curr_close > curr_open && curr_close > prev_open && curr_open <= prev_close)
    {
        return 1;
    }
    // Check for bearish engulfing pattern with body size condition
    else if (prev_close > prev_open && curr_close < curr_open && curr_close < prev_open && curr_open >= prev_close)
    {
        return -1;
    }
    // No engulfing pattern
    else
    {
        return 0;
    }
}
          
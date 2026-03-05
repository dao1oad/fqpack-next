#include "indicator.h"

int is_price_vol_rising(float prev_open, float prev_close, float prev_vol, float curr_open, float curr_close, float curr_vol) {
    // Check if both K-lines are bullish (close > open)
    bool is_prev_bullish = prev_close > prev_open;
    bool is_curr_bullish = curr_close > curr_open;

    // Check if both K-lines are bearish (close < open)
    bool is_prev_bearish = prev_close < prev_open;
    bool is_curr_bearish = curr_close < curr_open;

    // Check for rising trend
    if (is_prev_bullish && is_curr_bullish) {
        // Check if the current bullish body is at least twice the previous bullish body
        float prev_body = prev_close - prev_open;
        float curr_body = curr_close - curr_open;

        if (curr_body >= 2 * prev_body && curr_vol >= 2 * prev_vol) {
            return 1; // Rising trend
        }
    }

    // Check for falling trend
    if (is_prev_bearish && is_curr_bearish) {
        // Check if the current bearish body is at least twice the previous bearish body
        float prev_body = prev_open - prev_close;
        float curr_body = curr_open - curr_close;

        if (curr_body >= 2 * prev_body && curr_vol >= 2 * prev_vol) {
            return -1; // Falling trend
        }
    }

    return 0; // No clear trend
}

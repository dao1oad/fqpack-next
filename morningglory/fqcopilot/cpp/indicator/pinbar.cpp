#include "indicator.h"

int is_pinbar(float high, float low, float open, float close)
{
    // 计算上影线、下影线和实体的长度
    float upper_shadow = high - std::max(open, close);
    float lower_shadow = std::min(open, close) - low;
    float body_length = std::abs(close - open);

    // 判断是否为看涨 Pin Bar
    if (lower_shadow > 2 * upper_shadow && lower_shadow > 2 * body_length && close >= open)
    {
        return 1; // 是看涨 Pin Bar
    }
    // 判断是否为看跌 Pin Bar
    else if (upper_shadow > 2 * lower_shadow && upper_shadow > 2 * body_length && close <= open)
    {
        return -1; // 是看跌 Pin Bar
    }
    else
    {
        return 0; // 不是 Pin Bar
    }
}

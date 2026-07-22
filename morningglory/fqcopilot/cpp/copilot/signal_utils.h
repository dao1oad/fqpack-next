#pragma once

#include "../indicator/indicator.h"
#include "copilot.h"
#include <utility>

class SignalUtils {
public:
    // Calculate every base entrypoint predicate for every bar exactly once.
    // Bits 0..6 represent entrypoints 1..7.  Entrypoint 1 is a model
    // structural trigger, so this shared, model-independent mask deliberately
    // leaves bit 0 clear; the Python research adapter adds it when an emitted
    // raw signal has primary entrypoint 1.
    static std::pair<std::vector<int>, std::vector<int>> calc_base_trigger_masks(
                            const std::vector<float>& high,
                            const std::vector<float>& low,
                            const std::vector<float>& open,
                            const std::vector<float>& close,
                            const std::vector<float>& vol,
                            const std::vector<float>& wave_sigs,
                            const std::vector<StdBar>& std_bars,
                            const std::vector<float>& ma5,
                            const std::vector<float>& macd)
    {
        const int length = static_cast<int>(high.size());
        std::vector<int> buy_masks(length, 0);
        std::vector<int> sell_masks(length, 0);
        if (length == 0)
        {
            return {buy_masks, sell_masks};
        }

        // STRONG_FACTAL evaluates the complete series.  Keeping it outside
        // the bar loop is important: the legacy primary-selector calls it on
        // demand, whereas detailed research output needs only one evaluation.
        const auto strong_factors = STRONG_FACTAL(
            high, low, open, close, wave_sigs, std_bars);

        constexpr int ENTRYPOINT_2_BIT = 1 << (2 - 1);
        constexpr int ENTRYPOINT_3_BIT = 1 << (3 - 1);
        constexpr int ENTRYPOINT_4_BIT = 1 << (4 - 1);
        constexpr int ENTRYPOINT_5_BIT = 1 << (5 - 1);
        constexpr int ENTRYPOINT_6_BIT = 1 << (6 - 1);
        constexpr int ENTRYPOINT_7_BIT = 1 << (7 - 1);

        for (int n = 0; n < length; ++n)
        {
            const int pinbar = is_pinbar(high[n], low[n], open[n], close[n]);
            if (pinbar == 1) buy_masks[n] |= ENTRYPOINT_2_BIT;
            if (pinbar == -1) sell_masks[n] |= ENTRYPOINT_2_BIT;

            if (n >= 1)
            {
                const int engulfing = is_engulfing(
                    high[n - 1], low[n - 1], open[n - 1], close[n - 1],
                    high[n], low[n], open[n], close[n]);
                if (engulfing == 1) buy_masks[n] |= ENTRYPOINT_3_BIT;
                if (engulfing == -1) sell_masks[n] |= ENTRYPOINT_3_BIT;
            }

            if (n < static_cast<int>(strong_factors.size()))
            {
                if (strong_factors[n] == 1) buy_masks[n] |= ENTRYPOINT_4_BIT;
                if (strong_factors[n] == -1) sell_masks[n] |= ENTRYPOINT_4_BIT;
            }

            if (n >= 2)
            {
                if (ma5[n] > ma5[n - 1] && ma5[n - 1] <= ma5[n - 2])
                    buy_masks[n] |= ENTRYPOINT_5_BIT;
                if (ma5[n] < ma5[n - 1] && ma5[n - 1] >= ma5[n - 2])
                    sell_masks[n] |= ENTRYPOINT_5_BIT;
            }

            if (n >= 1)
            {
                const int price_vol = is_price_vol_rising(
                    open[n - 1], close[n - 1], vol[n - 1],
                    open[n], close[n], vol[n]);
                if (price_vol == 1) buy_masks[n] |= ENTRYPOINT_6_BIT;
                if (price_vol == -1) sell_masks[n] |= ENTRYPOINT_6_BIT;

                if (macd[n] > 0 && macd[n - 1] <= 0)
                    buy_masks[n] |= ENTRYPOINT_7_BIT;
                if (macd[n] < 0 && macd[n - 1] >= 0)
                    sell_masks[n] |= ENTRYPOINT_7_BIT;
            }
        }
        return {buy_masks, sell_masks};
    }

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
                            const std::vector<float>& strong_factors,
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
                            const std::vector<float>& strong_factors,
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

    // ========================================================================
    // 线段方向判定与 occurrence 计算（S0000 顺势 / 逆势）
    // ========================================================================

    // 位置 i 所属线段的「到达方向」：+1 向上 / -1 向下 / 0 未知
    // stretch_sigs 编码：1=向上线段终点，-1=向下线段终点，
    //   0.5=向上线段中间点(段已成立)，-0.5=向下线段中间点(段已成立)
    // 规则：从 i 往回找最近的有意义标记，其符号即方向（不翻转）
    //   先遇到 0.5 或 1.0 → 向上；先遇到 -0.5 或 -1.0 → 向下
    // 方向切换以「反向中间点 ±0.5 出现」为标志；终点 ±1.0 仅标记极值，不触发翻转。
    // 故顶 1.0 之后、反向 -0.5 出现之前仍算向上，底 -1.0 之后、0.5 出现之前仍算向下。
    static int seg_direction_at(const std::vector<float> &stretch_sigs, int i)
    {
        if (i < 0 || i >= static_cast<int>(stretch_sigs.size()))
        {
            return 0;
        }
        for (int j = i; j >= 0; --j)
        {
            float s = stretch_sigs[j];
            if (s == 0.5f || s == 1.0f) return 1;
            if (s == -0.5f || s == -1.0f) return -1;
        }
        return 0;
    }

    // 触发笔(方向 wave_dir)在位置 i 的 occurrence
    //   1 = 逆势(笔线反向)/无线段信息/找不到起点/顺势首创新极值
    //   N≥2 = 顺势(笔线同向)时，该线段内到 i 为止的创新极值次数
    // 注：occurrence=1 兼含逆势与顺势第1次，单凭此位无法区分
    static int calc_occurrence(
        const std::vector<float> &wave_sigs,
        const std::vector<float> &stretch_sigs,
        const std::vector<float> &high,
        const std::vector<float> &low,
        int i, int wave_dir)
    {
        if (i < 0 || i >= static_cast<int>(stretch_sigs.size()) ||
            i >= static_cast<int>(wave_sigs.size()) ||
            i >= static_cast<int>(high.size()) || i >= static_cast<int>(low.size()))
        {
            return 1;
        }
        int seg_dir = seg_direction_at(stretch_sigs, i);
        if (seg_dir == 0 || seg_dir != wave_dir)
        {
            return 1; // 逆势或无线段
        }

        // 顺势：定位线段起点 s（前一个反向端点）
        float opposite = static_cast<float>(-seg_dir);
        int s = -1;
        for (int j = i - 1; j >= 0; --j)
        {
            if (stretch_sigs[j] == opposite)
            {
                s = j;
                break;
            }
        }
        if (s == -1)
        {
            return 1; // 退路：找不到起点则无计数基准，保守回落到 1
        }

        // 统计 (s, i] 内顺势笔终点创新极值的累计次数
        int cnt = 0;
        float running = 0;
        bool started = false;
        if (seg_dir == 1)
        {
            for (int x = s + 1; x <= i; ++x)
            {
                // 确认笔(1.0)任意位置计入；候选笔(0.5)仅末点(触发点 i)计入
                float w = wave_sigs[x];
                bool eligible = (w == 1.0f) || (w == 0.5f && x == i);
                if (!eligible) continue;
                if (!started || high[x] > running)
                {
                    ++cnt;
                    running = high[x];
                    started = true;
                }
            }
        }
        else
        {
            for (int x = s + 1; x <= i; ++x)
            {
                // 确认笔(-1.0)任意位置计入；候选笔(-0.5)仅末点(触发点 i)计入
                float w = wave_sigs[x];
                bool eligible = (w == -1.0f) || (w == -0.5f && x == i);
                if (!eligible) continue;
                if (!started || low[x] < running)
                {
                    ++cnt;
                    running = low[x];
                    started = true;
                }
            }
        }
        return std::min(cnt, 99); // 防御：限制 occurrence 位宽，避免 ×100 编码溢出
    }
};

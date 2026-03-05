#include "../chanlun/czsc.h"
#include "base_calculator.h"
#include "copilot.h"
#include "signal_utils.h"

/**
 * @brief S0009_Calculator - 拉回中枢选股策略计算器
 *
 * 基于缠论的中枢理论，识别股价离开中枢后拉回中枢的买卖点机会。
 *
 * 策略核心逻辑：
 * 1. 识别完备中枢：在线段内寻找符合条件的完备中枢
 * 2. 监测离开中枢：检测股价突破或跌破中枢的行为
 * 3. 等待拉回确认：股价重新回到中枢区间后，等待2个K线延迟再开始检测信号
 * 4. 捕捉入场机会：通过连续3个K线收盘价确认突破来产生交易信号
 *
 * 买点逻辑（向下线段）：
 * - 找到向下线段中的最后一个完备中枢
 * - 检测跌破中枢下沿(dd)的K线位置，记录支撑价位
 * - 当股价重新站上中枢下沿/中沿/上沿时，等待2个K线后开始检测
 * - Case1(突破确认)：连续3个K线收盘价都高于目标价位时产生买入信号
 * - Case2(回踩确认)：出现向上笔后的向下笔回踩时，通过技术指标确认买入信号
 * - 风控机制：如果价格跌破记录的支撑价位，则停止该级别的信号检测
 *
 * 卖点逻辑（向上线段）：
 * - 找到向上线段中的最后一个完备中枢
 * - 检测突破中枢上沿(gg)的K线位置，记录阻力价位
 * - 当股价重新跌破中枢上沿/中沿/下沿时，等待2个K线后开始检测
 * - Case1(跌破确认)：连续3个K线收盘价都低于目标价位时产生卖出信号
 * - Case2(反弹确认)：出现向下笔后的向上笔反弹时，通过技术指标确认卖出信号
 * - 风控机制：如果价格突破记录的阻力价位，则停止该级别的信号检测
 *
 * 信号分级系统：
 * - 100系列：基于中枢下沿(dd)/上沿(gg)的拉回信号（最强级别）
 * - 200系列：基于中枢中沿(zd/zg)的拉回信号（中等级别）
 * - 300系列：基于中枢上沿(zg)/下沿(zd)的拉回信号（较弱级别）
 *
 * 技术特点：
 * - 延迟确认：信号触发前有2个K线的观察期，减少假信号
 * - 三重确认：需要连续3个K线收盘价满足条件才触发信号
 * - 动态风控：实时跟踪支撑/阻力位，及时止损
 * - 多级信号：提供不同强度的交易机会选择
 *
 * 适用场景：适合捕捉中短期的反弹和回调机会，在震荡市和趋势修正中表现较好
 */
class S0009_Calculator : public BaseCalculator {
private:
  void calculate() {
    int trend_type = 0;
    for (int i = 0; i < length; i++) {
      // 先判断trend_type，当前是向上走势类型还是向下走势类型
      if (trend_sigs[i] == 0.5 || trend_sigs[i] == 1) {
        trend_type = 1;
      } else if (trend_sigs[i] == -0.5 || trend_sigs[i] == -1) {
        trend_type = -1;
      }
      // trend_type == 1 表示当前是向上走势，trend_type == -1 表示当前是向下走势
      if (stretch_sigs[i] == -0.5 || stretch_sigs[i] == -1.0) {
        if (switch_opt == 0 || (switch_opt == 1 && trend_type == -1)) {
          find_buy_signals(i);
        }
      } else if (stretch_sigs[i] == 0.5 || stretch_sigs[i] == 1.0) {
        if (switch_opt == 0 || (switch_opt == 1 && trend_type == 1)) {
          find_sell_signals(i);
        }
      }
    }
  }

  void find_buy_signals(int origin_pos) {
    // origin_pos是线段的结束点，stretch_sigs[origin_pos] == -0.5 ||
    // stretch_sigs[origin_pos] == -1.0 找到这个线段的起点 stretch_sigs[x]
    // == 1.0的索引坐标
    int i = -1;
    int j = origin_pos;
    for (int x = origin_pos - 1; x >= 0; x--) {
      if (stretch_sigs[x] == 1.0) {
        i = x;
        break;
      }
    }
    // 找到i是线段的起点
    if (i >= 0) {
      // 找到i到j之间的中枢
      std::vector<Pivot> pivots = locate_pivots(wave_sigs, high, low, -1, i, j);
      int pivots_num = static_cast<int>(pivots.size());
      if (pivots_num > 0) {
        Pivot last_pivot = pivots[pivots_num - 1];
        if (last_pivot.is_comprehensive) {
          // 最后一个是完备中枢，找完备中枢的拉回点
          int break_pivot_start = -1;
          int meet_bi = 0;
          for (int x = last_pivot.end + 1; x <= j; x++) {
            if (wave_sigs[x] == -0.5 || wave_sigs[x] == -1.0) {
              meet_bi = 1;
            }
            if (meet_bi && low[x] < last_pivot.dd) {
              break_pivot_start = x;
              break;
            }
          }
          // break_pivot_start 找到跌破中枢的那个K线位置
          if (break_pivot_start >= 0) {
            float river_prices[3] = {last_pivot.dd, last_pivot.zd, last_pivot.zg};
            float support_price = low[break_pivot_start];
            int support_price_index = break_pivot_start;

            int c = 0;
            int reatched = 0;
            int last_x = break_pivot_start + 1;
            for (int x = break_pivot_start + 1; x < length && c < 3; x++) {
              last_x = x;
              if (low[x] < support_price) {
                support_price = low[x];
                support_price_index = x;
                c = 0;
                reatched = 0;
                continue;
              }
              if (reatched < 3 && high[x] > river_prices[reatched]) {
                reatched++;
              }
              if ((x - support_price_index) >= 3 &&
                  close[x] > river_prices[c] &&
                  close[x - 1] > river_prices[c] &&
                  close[x - 2] > river_prices[c] &&
                  low[x - 3] <= river_prices[c]) {
                inner_result[x] =
                    (++c) * 100 +
                    static_cast<int>(EntrypointType::ENTRYPOINT_BUY_OPEN_1);
                if (c < 3 && close[x] > river_prices[c] &&
                    close[x - 1] > river_prices[c] &&
                    close[x - 2] > river_prices[c] &&
                    low[x - 3] <= river_prices[c]) {
                  ++c;
                }
                if (c < 3 && close[x] > river_prices[c] &&
                    close[x - 1] > river_prices[c] &&
                    close[x - 2] > river_prices[c] &&
                    low[x - 3] <= river_prices[c]) {
                  ++c;
                }
              }
              if (wave_sigs[x] == 1) {
                break;
              }
            }
            
            // 从support_price_index到结尾查找值是1.0的索引位置
            int wave_end_index = -1;
            for (int x = support_price_index; x < length; x++) {
              if (wave_sigs[x] == 1.0) {
                wave_end_index = x;
                break;
              }
            }
            
            // 有了向上笔后就要开始找回踩笔
            if (wave_end_index >= 0 && reatched > 0) {
              for (int y = last_x + 1; y < length; y++) {
                if (low[y] < support_price) {
                  break;
                }
                if (wave_sigs[y] == -0.5 || wave_sigs[y] == -1) {
                  for (int n = y; n < length; n++) {
                    if (wave_sigs[n] == 0.5 || wave_sigs[n] == 1 ||
                        low[n] < low[y]) {
                      break;
                    }
                    if ((low[n] - support_price) / (high[wave_end_index] - support_price) < 0.5) {
                      EntrypointType signal = SignalUtils::is_buy_signal(
                          n, high, low, open, close, vol, wave_sigs, std_bars,
                          ma5, macd);

                      if (signal != EntrypointType::ENTRYPOINT_UNKNOWN) {
                        inner_result[n] =
                            reatched * 100 + static_cast<int>(signal);
                        break;
                      }
                    }
                  }
                  if (wave_sigs[y] == -1) {
                    break;
                  }
                }
              }
            }
          }
        }
      }
    }
  }

  void find_sell_signals(int origin_pos) {
    // origin_pos是线段的结束点，stretch_sigs[origin_pos] == 0.5 ||
    // stretch_sigs[origin_pos] == 1.0 找到这个线段的起点 stretch_sigs[x] ==
    // -1.0的索引坐标
    int i = -1;
    int j = origin_pos;
    for (int x = origin_pos - 1; x >= 0; x--) {
      if (stretch_sigs[x] == -1.0) {
        i = x;
        break;
      }
    }
    if (i >= 0) {
      std::vector<Pivot> pivots = locate_pivots(wave_sigs, high, low, 1, i, j);
      int pivots_num = static_cast<int>(pivots.size());
      if (pivots_num > 0) {
        Pivot last_pivot = pivots[pivots_num - 1];
        if (last_pivot.is_comprehensive) {
          // 最后一个是完备中枢，找完备中枢的突破点
          int break_pivot_start = -1;
          int meet_bi = 0;
          for (int x = last_pivot.end + 1; x <= j; x++) {
            if (wave_sigs[x] == 0.5 || wave_sigs[x] == 1.0) {
              meet_bi = 1;
            }
            if (meet_bi == 1 && high[x] > last_pivot.gg) {
              break_pivot_start = x;
              break;
            }
          }
          if (break_pivot_start >= 0) {
            float river_prices[3] = {last_pivot.gg, last_pivot.zg, last_pivot.zd};
            // resistance_price是离开中枢的一笔到达的最高价格
            float resistance_price = high[break_pivot_start];
            int resistance_price_index = break_pivot_start;

            int c = 0;
            int reatched = 0;
            int last_x = break_pivot_start + 1;
            for (int x = break_pivot_start + 1; x < length && c < 3; x++) {
              last_x = x;
              if (high[x] > resistance_price) {
                resistance_price = high[x];
                resistance_price_index = x;
                c = 0;
                reatched = 0;
                continue;
              }
              if (reatched < 3 && low[x] < river_prices[reatched]) {
                reatched++;
              }
              if (x - resistance_price_index >= 3 &&
                  close[x] < river_prices[c] &&
                  close[x - 1] < river_prices[c] &&
                  close[x - 2] < river_prices[c] &&
                  high[x - 3] >= river_prices[c]) {
                inner_result[x] =
                    -(++c) * 100 +
                    static_cast<int>(EntrypointType::ENTRYPOINT_SELL_OPEN_1);
                if (c < 3 && close[x] < river_prices[c] &&
                    close[x - 1] < river_prices[c] &&
                    close[x - 2] < river_prices[c] &&
                    high[x - 3] >= river_prices[c]) {
                  ++c;
                }
                if (c < 3 && close[x] < river_prices[c] &&
                    close[x - 1] < river_prices[c] &&
                    close[x - 2] < river_prices[c] &&
                    high[x - 3] >= river_prices[c]) {
                  ++c;
                }
              }
              if (wave_sigs[x] == -1) {
                break;
              }
            }
            
            // 从resistance_price_index到结尾查找值是-1.0的索引位置
            int wave_end_index = -1;
            for (int x = resistance_price_index; x < length; x++) {
              if (wave_sigs[x] == -1.0) {
                wave_end_index = x;
                break;
              }
            }
            
            // 有了向下笔后就要开始找上拉笔
            if (wave_end_index >= 0 && reatched > 0) {
              for (int y = last_x + 1; y < length; y++) {
                if (high[y] > resistance_price) {
                  break;
                }
                if (wave_sigs[y] == 0.5 || wave_sigs[y] == 1) {
                  for (int n = y; n < length; n++) {
                    if (wave_sigs[n] == -0.5 || wave_sigs[n] == -1 ||
                        high[n] > high[y]) {
                      break;
                    }
                    if ((resistance_price - high[n]) / (resistance_price - low[wave_end_index]) < 0.5) {
                      EntrypointType signal = SignalUtils::is_sell_signal(
                          n, high, low, open, close, vol, wave_sigs, std_bars,
                          ma5, macd);

                      if (signal != EntrypointType::ENTRYPOINT_UNKNOWN) {
                        inner_result[n] =
                            -reatched * 100 + static_cast<int>(signal);
                        break;
                      }
                    }
                  }
                  if (wave_sigs[y] == 1) {
                    break;
                  }
                }
              }
            }
          }
        }
      }
    }
  }

public:
  S0009_Calculator(const std::vector<float> &high,
                   const std::vector<float> &low,
                   const std::vector<float> &open,
                   const std::vector<float> &close,
                   const std::vector<float> &vol, int switch_opt,
                   const ChanOptions &options)
      : BaseCalculator(high, low, open, close, vol, switch_opt, options) {
    calculate();
  }
};

std::vector<int> F_S0009(const std::vector<float> &high,
                         const std::vector<float> &low,
                         const std::vector<float> &open,
                         const std::vector<float> &close,
                         const std::vector<float> &vol, int switch_opt,
                         const ChanOptions &options) {
  S0009_Calculator calculator(high, low, open, close, vol, switch_opt, options);
  return calculator.result();
}

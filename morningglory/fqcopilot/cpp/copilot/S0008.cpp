#include "../chanlun/czsc.h"
#include "base_calculator.h"
#include "copilot.h"


/**
 * @brief S0008_Calculator - 盘整或趋势背驰选股计算器
 *
 * 基于缠论理论的背驰选股策略，通过分析中枢结构和MACD指标来识别买卖信号。
 *
 * 核心逻辑：
 * 1. 识别线段中的中枢结构（至少包含5笔的线段）
 * 2. 对比进入中枢的一笔和离开中枢的一笔的MACD特征
 * 3. 当发生MACD金叉/死叉时，判断是否存在背驰现象
 *
 * 买点判断条件：
 * - 向下线段结束时（stretch_sigs为-0.5或-1.0）
 * - 线段包含完整中枢结构（至少5笔）
 * - 离开中枢时发生MACD金叉
 * -
 * 满足背驰条件：离开中枢的DIF值大于进入中枢的DIF值，或离开中枢的MACD绿柱面积小于进入中枢
 * - 价格突破中枢下沿且形成新的笔结构
 * - 避免MACD失真情况（收盘价等于最低价）
 *
 * 卖点判断条件：
 * - 向上线段结束时（stretch_sigs为0.5或1.0）
 * - 线段包含完整中枢结构（至少5笔）
 * - 离开中枢时发生MACD死叉
 * -
 * 满足背驰条件：离开中枢的DIF值小于进入中枢的DIF值，或离开中枢的MACD红柱面积小于进入中枢
 * - 价格突破中枢上沿且形成新的笔结构
 * - 避免MACD失真情况（收盘价等于最高价）
 *
 * 信号强度：根据中枢数量进行编码，中枢越多信号越强
 */
class S0008_Calculator : public BaseCalculator {
private:
  void calculate() {

    for (int i = 0; i < length; i++) {
      if (stretch_sigs[i] == -0.5 || stretch_sigs[i] == -1.0) {
        find_buy_signals(i);
      } else if (stretch_sigs[i] == 0.5 || stretch_sigs[i] == 1.0) {
        find_sell_signals(i);
      }
    }
  }

  void find_buy_signals(int origin_pos) {
    int i = -1;
    int j = origin_pos;
    for (int x = origin_pos - 1; x >= 0; x--) {
      // 这是寻找向下线段的起点
      if (stretch_sigs[x] == 1.0) {
        i = x;
        break;
      }
    }
    // i是线段的起点，j是线段的终点
    // 如果i小于0，说明没有找到线段的起点，不会有买点
    if (i >= 0) {
      std::vector<Pivot> pivots = locate_pivots(wave_sigs, high, low, -1, i, j);
      // pivots是这个向下线段中的中枢
      int pivots_num = static_cast<int>(pivots.size());
      // pivots_num是中枢的数量（完备中枢和不完备中枢都算在内）
      std::unordered_map<float, int> values_num =
          count_values_float(wave_sigs, {1.0, -1.0}, i, j, false);
      // values_num是这个线段中笔顶和笔底的数量，不含起点和终点
      int total_count = 0;
      for (const auto &pair : values_num) {
        if (pair.first == 1.0 || pair.first == -1.0) {
          total_count += pair.second;
        }
      }
      // total_count >= 4 保证了线段至少要有5笔，这个时候判断是不是pivots_num >
      // 0无所谓了，这肯定是大于0的。
      if (total_count >= 4 && pivots_num > 0) {
        Pivot last_pivot = pivots[pivots_num - 1];
        // last_pivot可能是完备的，也可能不是完备的。
        int enter_pivot_wave_start = -1;
        for (int x = last_pivot.start - 1; x >= 0; x--) {
          if (wave_sigs[x] == 1.0) {
            enter_pivot_wave_start = x;
            break;
          }
        }
        // enter_pivot_wave_start是进入中枢笔的开始
        int enter_pivot_wave_end = last_pivot.start;
        for (int x = last_pivot.start; x < last_pivot.end; x++) {
          enter_pivot_wave_end = x;
          if (macd[x - 1] <= 0 && macd[x] > 0) {
            break;
          }
        }
        float dif_a = 0.0f;      // 进入一笔的dif
        float macd_acc_a = 0.0f; // 进入一笔的macd绿柱的累计
        if (enter_pivot_wave_start > -1) {
          for (int x = enter_pivot_wave_start; x <= enter_pivot_wave_end; x++) {
            if (dif_a == 0.0f || dif[x] < dif_a) {
              dif_a = dif[x];
            }
            if (macd[x] < 0) {
              macd_acc_a += macd[x];
            }
          }
        }

        float dif_b = 0.0f;      // 离开一笔的dif
        float macd_acc_b = 0.0f; // 离开一笔的macd绿柱的累计
        int n = -1;
        int meet_bi = 0;
        int meet_break = 0;
        float most_low = 0.0f; // 离开中枢的最低价
        // n用来记录发生金叉的位置
        for (int x = last_pivot.end + 1; x < length; x++) {
          if (most_low == 0.0f || low[x] < most_low) {
            most_low = low[x];
          }
          if (dif_b == 0.0f || dif[x] < dif_b) {
            dif_b = dif[x];
          }
          if (macd[x] < 0) {
            macd_acc_b += macd[x];
          }
          if (low[x] < last_pivot.dd) {
            meet_break = 1;
          }
          if (wave_sigs[x] == -0.5 || wave_sigs[x] == -1.0) {
            meet_bi = 1;
          }
          if (macd[x - 1] <= 0 && macd[x] > 0) {
            if (meet_bi == 1 && meet_break == 1) {
              n = x;
              break;
            }
          }
          if (stretch_sigs[x] == 0.5 || stretch_sigs[x] == 1) {
            break;
          }
        }
        // n是离开中枢的金叉位置
        if (n > -1 && dif[n] < 0.0 && (dif_b > dif_a || macd_acc_b > macd_acc_a)) {
          int distortion = 0;
          if (close[n] == most_low) {
            distortion = 1;
          }
          if (distortion == 0) {
            int last_buy_pos = -1;
            // 找到上一次的买点位置，保存在last_buy_pos中
            for (int x = n - 1; x >= 0; x--) {
              if (stretch_sigs[x] == 1.0) {
                break;
              }
              if (inner_result[x] > 0) {
                last_buy_pos = x;
                break;
              }
            }
            bool is_buy_signal = false;
            // 存在一个中枢，他的起点在last_buy_pos和n之间
            if (last_buy_pos > -1) {
              for (auto &pivot : pivots) {
                if (pivot.start > last_buy_pos && pivot.end < n) {
                  is_buy_signal = true;
                }
              }
            } else {
              is_buy_signal = true;
            }
            if (is_buy_signal) {
              inner_result[n] =
                  pivots_num * 100 +
                  static_cast<int>(EntrypointType::ENTRYPOINT_BUY_OPEN_1);
            }
          }
        }
      }
    }
  }

  void find_sell_signals(int origin_pos) {
    int i = -1;
    int j = origin_pos;
    for (int x = origin_pos - 1; x >= 0; x--) {
      // 这是寻找向上线段的起点
      if (stretch_sigs[x] == -1.0) {
        i = x;
        break;
      }
    }
    if (i >= 0) {
      std::vector<Pivot> pivots = locate_pivots(wave_sigs, high, low, 1, i, j);
      int pivots_num = static_cast<int>(pivots.size());
      std::unordered_map<float, int> values_num =
          count_values_float(wave_sigs, {-1.0, 1.0}, i, j, false);
      int total_count = 0;
      for (const auto &pair : values_num) {
        if (pair.first == -1.0 || pair.first == 1.0) {
          total_count += pair.second;
        }
      }
      if (total_count >= 4 && pivots_num > 0) {
        Pivot last_pivot = pivots[pivots_num - 1];
        int enter_pivot_wave_start = -1;
        for (int x = last_pivot.start - 1; x >= 0; x--) {
          if (wave_sigs[x] == -1.0) {
            enter_pivot_wave_start = x;
            break;
          }
        }
        int enter_pivot_wave_end = last_pivot.start;
        for (int x = last_pivot.start; x < last_pivot.end; x++) {
          enter_pivot_wave_end = x;
          if (macd[x - 1] >= 0 && macd[x] < 0) {
            break;
          }
        }
        float dif_a = 0.0f;
        float macd_acc_a = 0.0f;
        if (enter_pivot_wave_start > -1) {
          for (int x = enter_pivot_wave_start; x <= enter_pivot_wave_end; x++) {
            if (dif_a == 0.0f || dif[x] > dif_a) {
              dif_a = dif[x];
            }
            if (macd[x] > 0) {
              macd_acc_a += macd[x];
            }
          }
        }
        float dif_b = 0.0f;
        float macd_acc_b = 0.0f;
        int n = -1;
        int meet_bi = 0;
        int meet_break = 0;
        float most_high = 0.0f;
        for (int x = last_pivot.end + 1; x < length; x++) {
          if (most_high == 0.0f || high[x] > most_high) {
            most_high = high[x];
          }
          if (dif_b == 0.0f || dif[x] > dif_b) {
            dif_b = dif[x];
          }
          if (macd[x] > 0) {
            macd_acc_b += macd[x];
          }
          if (high[x] > last_pivot.gg) {
            meet_break = 1;
          }
          if (wave_sigs[x] == 0.5 || wave_sigs[x] == 1.0) {
            meet_bi = 1;
          }
          if (macd[x - 1] >= 0 && macd[x] < 0) {
            if (meet_bi == 1 && meet_break == 1) {
              n = x;
              break;
            }
          }
          if (stretch_sigs[x] == -0.5 || stretch_sigs[x] == -1) {
            break;
          }
        }

        // n是离开中枢的死叉位置
        if (n > -1 && dif[n] > 0.0 && (dif_b < dif_a || macd_acc_b < macd_acc_a)) {
          // 这里还要判断有没有发生MACD失真的情况（涨跌停的时候会发生MACD失真）
          int distortion = 0;
          if (close[n] == most_high) {
            distortion = 1;
          }
          if (distortion == 0) {
            int last_sell_pos = -1;
            // 找到上一次的卖点位置，保存在last_sell_pos中
            for (int x = n - 1; x >= 0; x--) {
              if (stretch_sigs[x] == -1.0) {
                break;
              }
              if (inner_result[x] < 0) {
                last_sell_pos = x;
                break;
              }
            }
            bool is_sell_signal = false;
            // 存在一个中枢，他的起点在last_sell_pos和n之间
            if (last_sell_pos > -1) {
              for (auto &pivot : pivots) {
                if (pivot.start > last_sell_pos && pivot.end < n) {
                  is_sell_signal = true;
                }
              }
            } else {
              is_sell_signal = true;
            }
            if (is_sell_signal) {
              inner_result[n] =
                  -pivots_num * 100 +
                  static_cast<int>(EntrypointType::ENTRYPOINT_SELL_OPEN_1);
            }
          }
        }
      }
    }
  }

public:
  S0008_Calculator(const std::vector<float> &high,
                   const std::vector<float> &low,
                   const std::vector<float> &open,
                   const std::vector<float> &close,
                   const std::vector<float> &vol, int switch_opt,
                   const ChanOptions &options)
      : BaseCalculator(high, low, open, close, vol, switch_opt, options) {
    calculate();
  }
};

std::vector<int> F_S0008(const std::vector<float> &high,
                         const std::vector<float> &low,
                         const std::vector<float> &open,
                         const std::vector<float> &close,
                         const std::vector<float> &vol, int switch_opt,
                         const ChanOptions &options) {
  S0008_Calculator calculator(high, low, open, close, vol, switch_opt, options);
  return calculator.result();
}

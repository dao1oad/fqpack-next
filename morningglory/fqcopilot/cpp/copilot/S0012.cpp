#include "../chanlun/czsc.h"
#include "base_calculator.h"
#include "copilot.h"

// V反信号
// V反就是一笔突破未完备中枢的高点/低点
// 线段中有2个中枢（可以是未完备中枢）
class S0012_Calculator : public BaseCalculator {
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
    int i = -1;
    int j = origin_pos;
    for (int x = origin_pos - 1; x >= 0; x--) {
      if (stretch_sigs[x] == 1.0) {
        i = x;
        break;
      }
    }

    if (i >= 0) {
      std::vector<Pivot> pivots = locate_pivots(wave_sigs, high, low, -1, i, j);
      int pivots_num = static_cast<int>(pivots.size());
      if (pivots_num > 1 && pivots.back().is_comprehensive == false) {
        float river_price = pivots.back().zg;
        float support_price = low[j];
        bool reatched = false;
        int last_x = j + 1;
        for (int x = j + 1; x < length; x++) {
          if (high[x] > river_price) {
            reatched = true;
          }
          last_x = x;
          if (x - j >= 3 && close[x] > river_price &&
              close[x - 1] > river_price && close[x - 2] > river_price &&
              low[x - 3] <= river_price) {
            inner_result[x] =
                100 + static_cast<int>(EntrypointType::ENTRYPOINT_BUY_OPEN_1);
            break;
          }
          // 向上笔完成了就可以退出了
          if (wave_sigs[x] == 1.0) {
            break;
          }
        }
        if (reatched) {
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
                EntrypointType signal =
                    SignalUtils::is_buy_signal(n, high, low, open, close, vol,
                                               wave_sigs, std_bars, ma5, macd);

                if (signal != EntrypointType::ENTRYPOINT_UNKNOWN) {
                  inner_result[n] = 100 + static_cast<int>(signal);
                  break;
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

  void find_sell_signals(int origin_pos) {
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
      if (pivots_num > 1 && pivots.back().is_comprehensive == false) {
        float river_price = pivots.back().zd;
        float resistance_price = high[j];
        bool reatched = false;
        int last_x = j + 1;
        for (int x = j + 1; x < length; x++) {
          if (low[x] < river_price) {
            reatched = true;
          }
          last_x = x;
          if (x - j >= 3 && close[x] < river_price &&
              close[x - 1] < river_price && close[x - 2] < river_price &&
              high[x - 3] >= river_price) {
            inner_result[x] =
                -100 + static_cast<int>(EntrypointType::ENTRYPOINT_SELL_OPEN_1);
            break;
          }
          // 向下笔完成了就可以退出了
          if (wave_sigs[x] == -1.0) {
            break;
          }
        }
        if (reatched) {
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
                EntrypointType signal =
                    SignalUtils::is_sell_signal(n, high, low, open, close, vol,
                                                wave_sigs, std_bars, ma5, macd);

                if (signal != EntrypointType::ENTRYPOINT_UNKNOWN) {
                  inner_result[n] = -100 + static_cast<int>(signal);
                  break;
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

public:
  S0012_Calculator(const std::vector<float> &high,
                   const std::vector<float> &low,
                   const std::vector<float> &open,
                   const std::vector<float> &close,
                   const std::vector<float> &vol, int switch_opt,
                   const ChanOptions &options)
      : BaseCalculator(high, low, open, close, vol, switch_opt, options) {
    calculate();
  }
};

std::vector<int> F_S0012(const std::vector<float> &high,
                         const std::vector<float> &low,
                         const std::vector<float> &open,
                         const std::vector<float> &close,
                         const std::vector<float> &vol, int switch_opt,
                         const ChanOptions &options) {
  S0012_Calculator calculator(high, low, open, close, vol, switch_opt, options);
  return calculator.result();
}

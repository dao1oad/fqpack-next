#include "../chanlun/czsc.h"
#include "base_calculator.h"
#include "copilot.h"

// 声明S0008的外部函数
std::vector<int> F_S0008(const std::vector<float> &high,
                         const std::vector<float> &low,
                         const std::vector<float> &open,
                         const std::vector<float> &close,
                         const std::vector<float> &vol, int switch_opt,
                         const ChanOptions &options);

std::vector<int> F_S0008_ctx(const std::vector<float> &high,
                             const std::vector<float> &low,
                             const std::vector<float> &open,
                             const std::vector<float> &close,
                             const std::vector<float> &vol, int switch_opt,
                             const ChanOptions &options,
                             const ChanContext &ctx);

/**
 * @brief S0014_Calculator - 缠论线段中枢上方/下方信号计算器
 *
 * 基于S0008的背驰信号，进一步验证收盘价是否在最后一个线段中枢的上方（买入）或下方（卖出）。
 *
 * 核心逻辑：
 * 1. 首先使用S0008识别背驰信号
 * 2. 对于每个S0008信号，找到对应线段中的最后一个中枢
 * 3. 根据收盘价与最后一个中枢的关系，决定是否保留信号
 *
 * 信号过滤规则：
 * - 买点：收盘价必须高于最后一个线段中枢的zg（中枢上沿），否则取消信号
 * - 卖点：收盘价必须低于最后一个线段中枢的zd（中枢下沿），否则取消信号
 *
 * 注意：S0014是S0008的子集，只保留满足线段中枢上方/下方条件的信号
 */
class S0014_Calculator : public BaseCalculator {
private:
  std::vector<int> s0008_cache;
  bool use_ctx = false;

  // 将 S0008 信号重编码为 S0014（model_id 8 → 14，保留 occurrence 和 entrypoint）
  int reencode(int original_signal) {
    int abs_val = std::abs(original_signal);
    int occurrence = (abs_val % 1000) / 100;
    int ep_abs = abs_val % 100;
    auto ep = (original_signal > 0)
                  ? static_cast<EntrypointType>(ep_abs)
                  : static_cast<EntrypointType>(-ep_abs);
    return encode_signal(14, occurrence, ep);
  }

  void calculate() {
    // 先使用S0008计算背驰信号
    std::vector<int> s0008_results;
    if (use_ctx) {
        s0008_results = s0008_cache;
    } else {
        s0008_results = F_S0008(high, low, open, close, vol, switch_opt, options);
    }

    // 遍历S0008的信号，进行过滤
    for (int i = 0; i < length; i++) {
      if (s0008_results[i] > 0) {
        // S0008买入信号，验证是否满足条件
        validate_buy_signal(i, s0008_results[i]);
      } else if (s0008_results[i] < 0) {
        // S0008卖出信号，验证是否满足条件
        validate_sell_signal(i, s0008_results[i]);
      }
    }
  }

  void validate_buy_signal(int signal_pos, int original_signal) {
    // 找到最后一个trend的结束点和起点
    int trend_end = -1;
    int trend_start = -1;
    float trend_direction = 0;

    // 先找最后一个trend的结束点
    for (int x = signal_pos; x >= 0; x--) {
      if (trend_sigs[x] == -0.5 || trend_sigs[x] == -1.0 ||
          trend_sigs[x] == 0.5 || trend_sigs[x] == 1.0) {
        trend_end = x;
        trend_direction = trend_sigs[x];
        break;
      }
    }

    if (trend_end < 0) {
      inner_result[signal_pos] = 0;
      return;
    }

    // 找这个trend的起点
    float opposite_direction = (trend_direction > 0) ? -1.0 : 1.0;
    for (int x = trend_end - 1; x >= 0; x--) {
      if ((opposite_direction > 0 && (trend_sigs[x] == 0.5 || trend_sigs[x] == 1.0)) ||
          (opposite_direction < 0 && (trend_sigs[x] == -0.5 || trend_sigs[x] == -1.0))) {
        trend_start = x;
        break;
      }
    }

    if (trend_start < 0) {
      inner_result[signal_pos] = 0;
      return;
    }

    // 在trend中找中枢，使用线段信号
    std::vector<Pivot> pivots = locate_pivots(stretch_sigs, high, low, trend_direction, trend_start, trend_end);
    int pivots_num = static_cast<int>(pivots.size());

    if (pivots_num == 0) {
      inner_result[signal_pos] = 0;
      return;
    }

    // 获取最后一个中枢
    Pivot last_pivot = pivots[pivots_num - 1];

    // 买入信号：收盘价必须在中枢上方
    if (close[signal_pos] > last_pivot.zg) {
      inner_result[signal_pos] = reencode(original_signal);
    } else {
      inner_result[signal_pos] = 0;
    }
  }

  void validate_sell_signal(int signal_pos, int original_signal) {
    // 找到最后一个trend的结束点和起点
    int trend_end = -1;
    int trend_start = -1;
    float trend_direction = 0;

    // 先找最后一个trend的结束点
    for (int x = signal_pos; x >= 0; x--) {
      if (trend_sigs[x] == -0.5 || trend_sigs[x] == -1.0 ||
          trend_sigs[x] == 0.5 || trend_sigs[x] == 1.0) {
        trend_end = x;
        trend_direction = trend_sigs[x];
        break;
      }
    }

    if (trend_end < 0) {
      inner_result[signal_pos] = 0;
      return;
    }

    // 找这个trend的起点
    float opposite_direction = (trend_direction > 0) ? -1.0 : 1.0;
    for (int x = trend_end - 1; x >= 0; x--) {
      if ((opposite_direction > 0 && (trend_sigs[x] == 0.5 || trend_sigs[x] == 1.0)) ||
          (opposite_direction < 0 && (trend_sigs[x] == -0.5 || trend_sigs[x] == -1.0))) {
        trend_start = x;
        break;
      }
    }

    if (trend_start < 0) {
      inner_result[signal_pos] = 0;
      return;
    }

    // 在trend中找中枢，使用线段信号
    std::vector<Pivot> pivots = locate_pivots(stretch_sigs, high, low, trend_direction, trend_start, trend_end);
    int pivots_num = static_cast<int>(pivots.size());

    if (pivots_num == 0) {
      inner_result[signal_pos] = 0;
      return;
    }

    // 获取最后一个中枢
    Pivot last_pivot = pivots[pivots_num - 1];

    // 卖出信号：收盘价必须在中枢下方
    if (close[signal_pos] < last_pivot.zd) {
      inner_result[signal_pos] = reencode(original_signal);
    } else {
      inner_result[signal_pos] = 0;
    }
  }

public:
  S0014_Calculator(const std::vector<float> &high,
                   const std::vector<float> &low,
                   const std::vector<float> &open,
                   const std::vector<float> &close,
                   const std::vector<float> &vol, int switch_opt,
                   const ChanOptions &options)
      : BaseCalculator(high, low, open, close, vol, switch_opt, options) {
    calculate();
  }

  S0014_Calculator(
      const std::vector<float> &high, const std::vector<float> &low,
      const std::vector<float> &open, const std::vector<float> &close,
      const std::vector<float> &vol, int switch_opt,
      const ChanOptions &options,
      const ChanContext &ctx) : BaseCalculator(high, low, open, close, vol, switch_opt, options, ctx)
  {
    s0008_cache = F_S0008_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    use_ctx = true;
    calculate();
  }
};

std::vector<int> F_S0014(const std::vector<float> &high,
                         const std::vector<float> &low,
                         const std::vector<float> &open,
                         const std::vector<float> &close,
                         const std::vector<float> &vol, int switch_opt,
                         const ChanOptions &options) {
  S0014_Calculator calculator(high, low, open, close, vol, switch_opt, options);
  return calculator.result();
}

REGISTER_CALC(14, F_S0014)

std::vector<int> F_S0014_ctx(
    const std::vector<float> &high, const std::vector<float> &low,
    const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt,
    const ChanOptions &options, const ChanContext &ctx)
{
    return S0014_Calculator(high, low, open, close, vol, switch_opt, options, ctx).result();
}

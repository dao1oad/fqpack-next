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
 * @brief S0013_Calculator - 缠论二买信号计算器
 *
 * 基于S0008的背驰信号，进一步验证是否满足二买/二卖条件。
 *
 * 核心逻辑：
 * 1. 首先使用S0008识别背驰信号
 * 2. 对于每个S0008信号，验证trend结束点和倒数第二个stretch结束点是否重合
 * 3. 根据收盘价与trend结束点价格的关系，决定是否保留信号
 *
 * 信号过滤规则：
 * - 买点：收盘价必须高于trend结束点最低价，否则取消信号
 * - 卖点：收盘价必须低于trend结束点最高价，否则取消信号
 *
 * 注意：S0013是S0008的子集，只保留满足二买/二卖条件的信号
 */
class S0013_Calculator : public BaseCalculator {
private:
  std::vector<int> s0008_cache;
  bool use_ctx = false;

  // 将 S0008 信号重编码为 S0013（model_id 8 → 13，保留 occurrence 和 entrypoint）
  int reencode(int original_signal) {
    return reencode_signal_for_model(original_signal, 8, 13);
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
    // 找到最后一个向下trend的结束点
    int downtrend_end = -1;
    for (int x = signal_pos; x >= 0; x--) {
      if (trend_sigs[x] == -0.5 || trend_sigs[x] == -1.0) {
        downtrend_end = x;
        break;
      }
    }

    if (downtrend_end < 0) {
      inner_result[signal_pos] = 0;  // 取消信号
      return;
    }

    // 找倒数第二个向下stretch的结束点
    int down_stretch_count = 0;
    int down_stretch_end = -1;
    for (int x = signal_pos; x >= 0; x--) {
      if (stretch_sigs[x] == -0.5 || stretch_sigs[x] == -1.0) {
        down_stretch_count++;
        if (down_stretch_count == 2) {
          down_stretch_end = x;
          break;
        }
      }
    }

    if (down_stretch_end < 0) {
      inner_result[signal_pos] = 0;  // 取消信号
      return;
    }

    // 检查向下trend结束点和倒数第二个向下stretch结束点是否重合
    if (downtrend_end != down_stretch_end) {
      inner_result[signal_pos] = 0;  // 不重合，取消信号
      return;
    }

    // 计算trend结束点的最低价
    float trend_end_low = low[downtrend_end];

    // 如果收盘价高于trend结束点最低价，保留原信号；否则取消信号
    if (close[signal_pos] > trend_end_low) {
      inner_result[signal_pos] = reencode(original_signal);
    } else {
      inner_result[signal_pos] = 0;  // 不满足条件，取消信号
    }
  }

  void validate_sell_signal(int signal_pos, int original_signal) {
    // 找到最后一个向上trend的结束点
    int uptrend_end = -1;
    for (int x = signal_pos; x >= 0; x--) {
      if (trend_sigs[x] == 0.5 || trend_sigs[x] == 1.0) {
        uptrend_end = x;
        break;
      }
    }

    if (uptrend_end < 0) {
      inner_result[signal_pos] = 0;  // 取消信号
      return;
    }

    // 找倒数第二个向上stretch的结束点
    int up_stretch_count = 0;
    int up_stretch_end = -1;
    for (int x = signal_pos; x >= 0; x--) {
      if (stretch_sigs[x] == 0.5 || stretch_sigs[x] == 1.0) {
        up_stretch_count++;
        if (up_stretch_count == 2) {
          up_stretch_end = x;
          break;
        }
      }
    }

    if (up_stretch_end < 0) {
      inner_result[signal_pos] = 0;  // 取消信号
      return;
    }

    // 检查向上trend结束点和倒数第二个向上stretch结束点是否重合
    if (uptrend_end != up_stretch_end) {
      inner_result[signal_pos] = 0;  // 不重合，取消信号
      return;
    }

    // 计算trend结束点的最高价
    float trend_end_high = high[uptrend_end];

    // 如果收盘价低于trend结束点最高价，保留原信号；否则取消信号
    if (close[signal_pos] < trend_end_high) {
      inner_result[signal_pos] = reencode(original_signal);
    } else {
      inner_result[signal_pos] = 0;  // 不满足条件，取消信号
    }
  }

public:
  S0013_Calculator(const std::vector<float> &high,
                   const std::vector<float> &low,
                   const std::vector<float> &open,
                   const std::vector<float> &close,
                   const std::vector<float> &vol, int switch_opt,
                   const ChanOptions &options)
      : BaseCalculator(high, low, open, close, vol, switch_opt, options) {
    calculate();
  }

  S0013_Calculator(
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

std::vector<int> F_S0013(const std::vector<float> &high,
                         const std::vector<float> &low,
                         const std::vector<float> &open,
                         const std::vector<float> &close,
                         const std::vector<float> &vol, int switch_opt,
                         const ChanOptions &options) {
  S0013_Calculator calculator(high, low, open, close, vol, switch_opt, options);
  return calculator.result();
}

REGISTER_CALC(13, F_S0013)

std::vector<int> F_S0013_ctx(
    const std::vector<float> &high, const std::vector<float> &low,
    const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt,
    const ChanOptions &options, const ChanContext &ctx)
{
    return S0013_Calculator(high, low, open, close, vol, switch_opt, options, ctx).result();
}

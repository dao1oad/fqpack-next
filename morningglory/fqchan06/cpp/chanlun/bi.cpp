#include "czsc.h"
#include <cmath>

std::vector<float> recognise_bi(int length, std::vector<float> &high,
                                std::vector<float> &low, ChanOptions &options) {
  std::vector<float> bi(length, 0.0f);
  if (length == 0) {
    return bi;
  }
  if (is_expired()) {
    return bi;
  }

  const int lookback = 5;
  int last_low_vertex_pos = -1;
  int last_high_vertex_pos = -1;
  int temp_low_vertex_pos = 0;
  int temp_high_vertex_pos = 0;

  // 优化：引入增量统计变量，避免重复循环，将复杂度从O(N^2)降为O(N)
  int monitor_start_idx = -1;
  int monitor_end_idx = -1;
  int idx_min_high = -1;
  int idx_max_low = -1;
  float val_min_high = 0.0f;
  float val_max_low = 0.0f;

  for (int i = 1; i < length; i++) {
    // Update temp_low_vertex_pos if current low is lower than temp or is a
    // 5-day low
    bool update_low = false;
    if (low[i] < low[temp_low_vertex_pos]) {
      update_low = true;
    } else if (i >= 4) {
      bool is_min_5 = true;
      for (int k = 1; k <= 4; k++) {
        if (low[i - k] <= low[i]) {
          is_min_5 = false;
          break;
        }
      }
      if (is_min_5) {
        update_low = true;
      }
    }
    if (update_low) {
      temp_low_vertex_pos = i;
    }

    // Update temp_high_vertex_pos if current high is higher than temp or is a
    // 5-day high
    bool update_high = false;
    if (high[i] > high[temp_high_vertex_pos]) {
      update_high = true;
    } else if (i >= 4) {
      bool is_max_5 = true;
      for (int k = 1; k <= 4; k++) {
        if (high[i - k] >= high[i]) {
          is_max_5 = false;
          break;
        }
      }
      if (is_max_5) {
        update_high = true;
      }
    }
    if (update_high) {
      temp_high_vertex_pos = i;
    }

    // 确定当前的候选笔方向和区间 [current_start, current_end]
    int current_start;
    int current_end;
    bool is_upward_candidate;
    if (temp_low_vertex_pos < temp_high_vertex_pos) {
      current_start = temp_low_vertex_pos;
      current_end = temp_high_vertex_pos;
      is_upward_candidate = true;
    } else {
      current_start = temp_high_vertex_pos;
      current_end = temp_low_vertex_pos;
      is_upward_candidate = false;
    }

    // 如果起始锚点改变（或者首次运行），重置统计状态以匹配新区间
    if (current_start != monitor_start_idx) {
      monitor_start_idx = current_start;
      monitor_end_idx = current_start;
      idx_min_high = current_start;
      idx_max_low = current_start;
      val_min_high = high[current_start];
      val_max_low = low[current_start];
    }

    // 如果区间向右延伸，增量更新统计信息
    if (current_end > monitor_end_idx) {
      for (int k = monitor_end_idx + 1; k <= current_end; k++) {
        if (high[k] < val_min_high) {
          val_min_high = high[k];
          idx_min_high = k;
        }
        if (low[k] > val_max_low) {
          val_max_low = low[k];
          idx_max_low = k;
        }
      }
      monitor_end_idx = current_end;
    }

    if (std::abs(temp_low_vertex_pos - temp_high_vertex_pos) >= lookback - 1) {
      if (is_upward_candidate) {
        // 确认是不是向上笔：要求 min_high (a) 出现在 max_low (b) 之前，且
        // min_high < max_low
        if (idx_min_high < idx_max_low && val_min_high < val_max_low) {
          last_low_vertex_pos = temp_low_vertex_pos;
          last_high_vertex_pos = temp_high_vertex_pos;
          break;
        }
      } else {
        // 确认是不是向下笔：要求 max_low (a) 出现在 min_high (b) 之前，且
        // max_low > min_high
        if (idx_max_low < idx_min_high && val_max_low > val_min_high) {
          last_high_vertex_pos = temp_high_vertex_pos;
          last_low_vertex_pos = temp_low_vertex_pos;
          break;
        }
      }
    }
  }
  if (last_high_vertex_pos == -1 || last_low_vertex_pos == -1) {
    return bi; // 如果没找到初始笔，直接返回
  }
  bi[last_high_vertex_pos] = 1;
  bi[last_low_vertex_pos] = -1;
  while (true) {
    if (last_high_vertex_pos > last_low_vertex_pos) {
      // 最后一笔是向上的，那么我们要寻找向下笔的成立
      temp_low_vertex_pos = last_high_vertex_pos;

      // 优化：增量维护 min_high / max_low，避免重复循环
      int a = last_high_vertex_pos;
      int b = last_high_vertex_pos;
      float max_low = low[a];
      float min_high = high[b];

      int i = last_high_vertex_pos + 1;
      for (; i < length; i++) {
        // 如果出现新高，更新 last_high 并重新开始寻找
        if (high[i] > high[last_high_vertex_pos]) {
          bi[last_high_vertex_pos] = 0;
          bi[i] = 1;
          last_high_vertex_pos = i;
          break;
        }

        // 增量更新区间的 range low/high 极值
        if (low[i] > max_low) {
          max_low = low[i];
          a = i;
        }
        if (high[i] < min_high) {
          min_high = high[i];
          b = i;
        }

        bool update_low = false;
        if (low[i] < low[temp_low_vertex_pos]) {
          update_low = true;
        } else if (i - last_high_vertex_pos >= 4) {
          bool is_min_5 = true;
          for (int k = 1; k <= 4; k++) {
            if (low[i - k] <= low[i]) {
              is_min_5 = false;
              break;
            }
          }
          if (is_min_5) {
            update_low = true;
          }
        }

        if (update_low) {
          temp_low_vertex_pos = i;
          // 寻找是不是可以成立新的向下笔
          if (temp_low_vertex_pos - last_high_vertex_pos >= lookback - 1) {
            // 利用增量维护的统计值直接判断
            if (a < b && max_low > min_high) {
              bi[temp_low_vertex_pos] = -1;
              last_low_vertex_pos = temp_low_vertex_pos;
              break;
            }
          }
        }
      }
      if (i == length) {
        break;
      }
    } else {
      temp_high_vertex_pos = last_low_vertex_pos;

      // 优化：增量维护 min_high / max_low
      int a = last_low_vertex_pos;
      int b = last_low_vertex_pos;
      float min_high = high[a];
      float max_low = low[b];

      int i = last_low_vertex_pos + 1;
      for (; i < length; i++) {
        // 如果出现新低，更新 last_low 并重新开始寻找
        if (low[i] < low[last_low_vertex_pos]) {
          bi[last_low_vertex_pos] = 0;
          bi[i] = -1;
          last_low_vertex_pos = i;
          break;
        }

        // 增量更新区间的 range low/high 极值
        if (high[i] < min_high) {
          min_high = high[i];
          a = i;
        }
        if (low[i] > max_low) {
          max_low = low[i];
          b = i;
        }

        bool update_high = false;
        if (high[i] > high[temp_high_vertex_pos]) {
          update_high = true;
        } else if (i - last_low_vertex_pos >= 4) {
          bool is_max_5 = true;
          for (int k = 1; k <= 4; k++) {
            if (high[i - k] >= high[i]) {
              is_max_5 = false;
              break;
            }
          }
          if (is_max_5) {
            update_high = true;
          }
        }

        if (update_high) {
          temp_high_vertex_pos = i;
          // 寻找是不是可以成立新的向上笔
          if (temp_high_vertex_pos - last_low_vertex_pos >= lookback - 1) {
            // 利用增量维护的统计值直接判断
            if (a < b && min_high < max_low) {
              bi[temp_high_vertex_pos] = 1;
              last_high_vertex_pos = temp_high_vertex_pos;
              break;
            }
          }
        }
      }
      if (i == length) {
        break;
      }
    }
  }
  // 把第一个非0的笔信号设置为-3，表示此信号序列是笔信号
  for (int i = 0; i < length; i++) {
    if (bi[i] == 0) {
      bi[i] = -3;
      break;
    }
  }
  return bi;
}

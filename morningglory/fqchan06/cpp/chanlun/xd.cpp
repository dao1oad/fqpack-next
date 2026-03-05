#include "czsc.h"

// ========================================
// 特征序列处理
// ========================================

namespace FeatureSequence {

// 提取单个特征序列元素
// 以 vertex_idx 为起点，到下一个反向顶点构成一个特征序列元素
FeatureElement extract_one(const std::vector<Vertex> &vertexes, int vertex_idx,
                           const std::vector<float> &high,
                           const std::vector<float> &low, int length) {
  FeatureElement elem{-1, -1, -1, -1, 0, 0, Direction::UP};

  if (vertex_idx < 0 || vertex_idx >= vertexes.size() - 1) {
    return elem;
  }

  // 起点顶点类型决定线段方向
  int start_type = vertexes[vertex_idx].type;
  elem.dir = (start_type == 1) ? Direction::UP : Direction::DOWN;
  elem.start_pos = vertexes[vertex_idx].pos;
  elem.start_vertex_idx = vertex_idx;

  // 检查 start_pos 是否在范围内
  if (elem.start_pos < 0 || elem.start_pos >= length) {
    return elem;
  }

  // 查找下一个反向顶点（对手笔）
  int opponent_type = -start_type;
  for (int i = vertex_idx + 1; i < vertexes.size(); ++i) {
    if (vertexes[i].type == opponent_type) {
      // 检查 end_pos 是否在范围内
      if (vertexes[i].pos < 0 || vertexes[i].pos >= length) {
        return elem;
      }

      elem.end_pos = vertexes[i].pos;
      elem.end_vertex_idx = i;

      // 根据方向提取 high/low
      if (elem.dir == Direction::UP) {
        // 向上线段特征序列（向下笔）：起点顶点取HIGH，终点底点取LOW
        elem.high = high[elem.start_pos];
        elem.low = low[elem.end_pos];
      } else {
        // 向下线段特征序列（向上笔）：起点底点取LOW，终点顶点取HIGH
        elem.high = high[elem.end_pos];
        elem.low = low[elem.start_pos];
      }
      break;
    }
  }

  return elem;
}

// 合并包含关系（K线包含）
// 包含关系：合并后取极值，不丢弃任何特征序列元素
// 向上线段：high 取更高，low 取更高（向上包含）
// 向下线段：high 取更低，low 取更低（向下包含）
void merge_include(std::vector<FeatureElement> &seq, Direction dir) {
  if (seq.size() < 2)
    return;

  std::vector<FeatureElement> merged;
  merged.push_back(seq[0]);

  for (size_t i = 1; i < seq.size(); ++i) {
    FeatureElement &prev = merged.back();
    FeatureElement &curr = seq[i];

    // 判断包含关系：通过 high/low 范围
    bool has_include = (curr.high <= prev.high && curr.low >= prev.low) ||
                       (prev.high <= curr.high && prev.low >= curr.low);

    if (has_include) {
      // 有包含关系：合并取极值，end_pos 延伸到后者的结束位置
      if (dir == Direction::UP) {
        // 向上线段：取更高的 high 和更高的 low
        prev.high = std::max(prev.high, curr.high);
        prev.low = std::max(prev.low, curr.low);
      } else {
        // 向下线段：取更低的 high 和更低的 low
        prev.high = std::min(prev.high, curr.high);
        prev.low = std::min(prev.low, curr.low);
      }
      prev.end_pos = curr.end_pos;
    } else {
      // 无包含关系，直接加入
      merged.push_back(curr);
    }
  }

  seq = std::move(merged);
}

} // namespace FeatureSequence

// 提取笔顶点
static std::vector<Vertex> extract_vertices(const std::vector<float> &bi) {
  std::vector<Vertex> vertexes;
  for (int i = 0; i < bi.size(); ++i) {
    if (bi[i] == 1 || bi[i] == -1) {
      Vertex v;
      v.pos = i;
      v.type = static_cast<int>(bi[i]);
      v.logicPos = static_cast<int>(vertexes.size());
      vertexes.push_back(v);
    }
  }
  return vertexes;
}

// 判断两个特征序列元素的关系类型
// 返回值：前包含后 / 后包含前 / 单调递增 / 单调递减 / 无关系
static FeatureRelation check_feature_relation(const FeatureElement &front,
                                              const FeatureElement &back) {
  // 前包含后：前者的高 >= 后者的高，且前者的低 <= 后者的低
  if (front.high >= back.high && front.low <= back.low) {
    return FeatureRelation::FRONT_INCLUDES_BACK;
  }

  // 后包含前：后者的高 >= 前者的高，且后者的低 <= 前者的低
  if (back.high >= front.high && back.low <= front.low) {
    return FeatureRelation::BACK_INCLUDES_FRONT;
  }

  // 单调递增：后者的高和低都高于前者（向上抬高）
  if (back.high > front.high && back.low > front.low) {
    return FeatureRelation::MONOTONIC_RISING;
  }

  // 单调递减：后者的高和低都低于前者（向下降低）
  if (back.high < front.high && back.low < front.low) {
    return FeatureRelation::MONOTONIC_FALLING;
  }

  // 其他情况（交叉、一高一低等）属于无关系
  return FeatureRelation::NONE;
}

// 查找第一线段
// 返回值：pair<SegmentState, bool>，bool 表示是否找到
static std::pair<SegmentState, bool>
find_first_segment(const std::vector<Vertex> &vertexes,
                   const std::vector<float> &high,
                   const std::vector<float> &low, int length) {
  for (int i = 0; i < vertexes.size(); ++i) {
    FeatureElement elem =
        FeatureSequence::extract_one(vertexes, i, high, low, length);

    // 检查 elem 有效性（必须找到反向顶点）
    if (elem.end_vertex_idx < 0) {
      break;
    }

    for (int j = elem.end_vertex_idx + 1; j < vertexes.size(); ++j) {
      FeatureElement next_elem =
          FeatureSequence::extract_one(vertexes, j, high, low, length);

      // 检查 next_elem 有效性
      if (next_elem.end_vertex_idx < 0) {
        break;
      }

      // 判断包含关系：next_elem 包含 elem
      bool elem_included =
          (next_elem.high >= elem.high && next_elem.low <= elem.low);
      // 判断包含关系：next_elem 被 elem 包含
      bool next_included =
          (elem.high >= next_elem.high && elem.low <= next_elem.low);

      if (elem_included) {
        break; // 跳出 j 循环，回到 i 循环继续寻找
      }

      if (next_included) {
        // 合并：根据方向取极值，end_pos 延伸
        if (elem.dir == Direction::UP) {
          elem.high = std::max(elem.high, next_elem.high);
          elem.low = std::max(elem.low, next_elem.low);
        } else {
          elem.high = std::min(elem.high, next_elem.high);
          elem.low = std::min(elem.low, next_elem.low);
        }
        elem.end_pos = next_elem.end_pos;
        elem.end_vertex_idx = next_elem.end_vertex_idx;
        continue; // 继续 j 循环，寻找下一个
      }

      // 无包含关系：判断抬高/降低
      bool is_raising =
          (next_elem.high > elem.high && next_elem.low > elem.low);
      bool is_lowering =
          (next_elem.high < elem.high && next_elem.low < elem.low);

      if (elem.dir == Direction::UP && is_lowering) {
        // 找到第一个向下线段
        SegmentState seg{elem.start_vertex_idx, next_elem.end_vertex_idx,
                         elem.start_pos,        next_elem.end_pos,
                         Direction::DOWN,       true};
        return {seg, true};
      }

      if (elem.dir == Direction::DOWN && is_raising) {
        // 找到第一个向上线段
        SegmentState seg{elem.start_vertex_idx, next_elem.end_vertex_idx,
                         elem.start_pos,        next_elem.end_pos,
                         Direction::UP,         true};
        return {seg, true};
      }

      // 其他情况（UP+抬高 或 DOWN+降低）：跳出 j 循环
      break;
    }
  }
  return {SegmentState{}, false};
}

// ========================================
// 单调特征序列查找
// ========================================

// 从指定顶点开始查找单调特征序列
// 起点为低点（type=-1）：查找单调递增序列，后续 LOW 不能低于起点
// 起点为高点（type=1）：查找单调递减序列，后续 HIGH 不能高于起点
// 返回值：pair<SegmentState, bool>，bool 表示是否找到
std::pair<SegmentState, bool> find_monotonic_feature_sequence(
    const std::vector<Vertex> &vertexes, int start_vertex_idx,
    const std::vector<float> &high, const std::vector<float> &low, int length) {
  // 参数校验
  if (start_vertex_idx < 0 || start_vertex_idx >= vertexes.size()) {
    return {SegmentState{}, false};
  }

  int start_type = vertexes[start_vertex_idx].type;
  int start_pos = vertexes[start_vertex_idx].pos;

  // 起点价格限制
  float start_price = (start_type == 1) ? high[start_pos] : low[start_pos];

  // 确定目标方向和检查函数
  bool looking_for_rising = (start_type == -1); // 低点起点找递增
  Direction target_dir = looking_for_rising ? Direction::UP : Direction::DOWN;

  // 边收集边合并边检查单调性
  std::vector<FeatureElement> features;
  for (int i = start_vertex_idx; i < vertexes.size(); ++i) {
    FeatureElement elem =
        FeatureSequence::extract_one(vertexes, i, high, low, length);

    if (elem.end_vertex_idx < 0) {
      break; // 无效元素，结束
    }

    // 检查是否违反起点限制
    if (start_type == -1) {
      // 低点起点：后续 LOW 不能低于起点
      if (elem.low < start_price) {
        return {SegmentState{}, false}; // 寻找失败
      }
    } else {
      // 高点起点：后续 HIGH 不能高于起点
      if (elem.high > start_price) {
        return {SegmentState{}, false}; // 寻找失败
      }
    }

    // 添加到特征序列
    features.push_back(elem);

    // 合并包含关系
    FeatureSequence::merge_include(features, target_dir);

    // 检查是否有足够的特征序列且满足单调性
    if (features.size() >= 2) {
      // 检查最后一对是否满足单调关系
      FeatureRelation relation = check_feature_relation(
          features[features.size() - 2], features.back());

      bool is_valid_monotonic =
          looking_for_rising ? (relation == FeatureRelation::MONOTONIC_RISING)
                             : (relation == FeatureRelation::MONOTONIC_FALLING);

      if (is_valid_monotonic) {
        // 找到满足条件的单调序列，构造并返回
        SegmentState seg{start_vertex_idx, features.back().end_vertex_idx,
                         start_pos,        features.back().end_pos,
                         target_dir,       true};
        return {seg, true};
      }
    }

    // 跳过已处理的顶点
    i = elem.end_vertex_idx;
  }

  // 未找到满足条件的单调序列
  return {SegmentState{}, false};
}

// 查找下一个线段（递归）
// 从最后一个线段的结束顶点之后继续搜索，找到下一个线段后递归继续查找
static void find_subsequent_segments(std::vector<SegmentState> &segments,
                                     const std::vector<Vertex> &vertexes,
                                     const std::vector<float> &high,
                                     const std::vector<float> &low,
                                     int length) {
  if (segments.empty())
    return;

  int search_start = segments.back().vertex_end;
  if (search_start >= vertexes.size())
    return;

  std::vector<FeatureElement> temp_seq;
  for (int i = search_start; i < vertexes.size(); i = i + 2) {
    FeatureElement elem =
        FeatureSequence::extract_one(vertexes, i, high, low, length);

    // 没有找到特征序列，就结束了。
    if (elem.end_vertex_idx < 0) {
      return;
    }

    // 将 elem 加入 temp_seq
    temp_seq.push_back(elem);

    // 对 temp_seq 做包含合并
    FeatureSequence::merge_include(temp_seq, segments.back().dir);

    // 检查最后两个元素的单调性（至少需要 2 个元素）
    if (temp_seq.size() >= 2) {
      FeatureRelation relation = check_feature_relation(
          temp_seq[temp_seq.size() - 2], temp_seq.back());

      // 当前线段向上：检测到单调递减 → 形成新向下线段
      if (segments.back().dir == Direction::UP &&
          relation == FeatureRelation::MONOTONIC_FALLING) {
        // 检查封闭缺口：第二个特征序列的 LOW < 前向上线段的 extreme price
        float prev_extreme = get_segment_extreme_price(
            segments.back(), vertexes, high, low, length);
        if (temp_seq.back().low < prev_extreme) {
          // 已有 2 个单调递减的特征序列，形成新向下线段
          SegmentState new_seg{temp_seq.front().start_vertex_idx,
                               temp_seq.back().end_vertex_idx,
                               temp_seq.front().start_pos,
                               temp_seq.back().end_pos,
                               Direction::DOWN,
                               true};
          segments.push_back(new_seg);
          temp_seq.clear();
          // 递归查找下一个线段
          find_subsequent_segments(segments, vertexes, high, low, length);
          return;
        }
        // 未封闭缺口：查找反向递增特征序列
        auto reverse_result = find_monotonic_feature_sequence(
            vertexes, elem.end_vertex_idx, high, low, length);
        if (reverse_result.second) {
          const SegmentState &reverse_seg = reverse_result.first;
          // 检查反向线段结束点是否高于前向上线段的高点
          int prev_high_pos = segments.back().end_pos;
          if (high[reverse_seg.end_pos] > high[prev_high_pos]) {
            // 前向上线段延续
            segments.back().vertex_end = reverse_seg.vertex_end;
            segments.back().end_pos = reverse_seg.end_pos;
            find_subsequent_segments(segments, vertexes, high, low, length);
            return;
          } else {
            // 形成两个新线段
            // 第一个：temp_seq 形成的向下线段
            SegmentState down_seg{temp_seq.front().start_vertex_idx,
                                  temp_seq.back().end_vertex_idx,
                                  temp_seq.front().start_pos,
                                  temp_seq.back().end_pos,
                                  Direction::DOWN,
                                  true};
            segments.push_back(down_seg);
            // 第二个：find_monotonic_feature_sequence 找到的向上线段
            segments.push_back(reverse_seg);
            temp_seq.clear();
            find_subsequent_segments(segments, vertexes, high, low, length);
            return;
          }
        }
        // 未找到反向序列，继续收集
      }

      // 当前线段向下：检测到单调递增 → 形成新向上线段
      if (segments.back().dir == Direction::DOWN &&
          relation == FeatureRelation::MONOTONIC_RISING) {
        // 检查封闭缺口：第二个特征序列的 HIGH > 前向下线段的 extreme price
        float prev_extreme = get_segment_extreme_price(
            segments.back(), vertexes, high, low, length);
        if (temp_seq.back().high > prev_extreme) {
          // 已有 2 个单调递增的特征序列，形成新向上线段
          SegmentState new_seg{temp_seq.front().start_vertex_idx,
                               temp_seq.back().end_vertex_idx,
                               temp_seq.front().start_pos,
                               temp_seq.back().end_pos,
                               Direction::UP,
                               true};
          segments.push_back(new_seg);
          temp_seq.clear();
          // 递归查找下一个线段
          find_subsequent_segments(segments, vertexes, high, low, length);
          return;
        }
        // 未封闭缺口：查找反向递减特征序列
        auto reverse_result = find_monotonic_feature_sequence(
            vertexes, elem.end_vertex_idx, high, low, length);
        if (reverse_result.second) {
          const SegmentState &reverse_seg = reverse_result.first;
          // 检查反向线段结束点是否低于前向下线段的低点
          int prev_low_pos = segments.back().end_pos;
          if (low[reverse_seg.end_pos] < low[prev_low_pos]) {
            // 前向下线段延续
            segments.back().vertex_end = reverse_seg.vertex_end;
            segments.back().end_pos = reverse_seg.end_pos;
            find_subsequent_segments(segments, vertexes, high, low, length);
            return;
          } else {
            // 形成两个新线段
            // 第一个：temp_seq 形成的向上线段
            SegmentState up_seg{temp_seq.front().start_vertex_idx,
                                temp_seq.back().end_vertex_idx,
                                temp_seq.front().start_pos,
                                temp_seq.back().end_pos,
                                Direction::UP,
                                true};
            segments.push_back(up_seg);
            // 第二个：find_monotonic_feature_sequence 找到的向下线段
            segments.push_back(reverse_seg);
            temp_seq.clear();
            find_subsequent_segments(segments, vertexes, high, low, length);
            return;
          }
        }
        // 未找到反向序列，继续收集
      }
    }
    if (elem.end_vertex_idx + 1 < vertexes.size()) {
      if (segments.back().dir == Direction::UP) {
        if (high[vertexes[elem.end_vertex_idx + 1].pos] >
            high[segments.back().end_pos]) {
          segments.back().vertex_end = elem.end_vertex_idx + 1;
          segments.back().end_pos = vertexes[elem.end_vertex_idx + 1].pos;
          find_subsequent_segments(segments, vertexes, high, low, length);
          return;
        }
      } else if (segments.back().dir == Direction::DOWN) {
        if (low[vertexes[elem.end_vertex_idx + 1].pos] <
            low[segments.back().end_pos]) {
          segments.back().vertex_end = elem.end_vertex_idx + 1;
          segments.back().end_pos = vertexes[elem.end_vertex_idx + 1].pos;
          find_subsequent_segments(segments, vertexes, high, low, length);
          return;
        }
      }
    }
  }

  return;
}

// 生成标记数组
static std::vector<float>
mark_segments(const std::vector<SegmentState> &segments,
              const std::vector<Vertex> &vertexes,
              const std::vector<float> &high, const std::vector<float> &low,
              int length) {
  std::vector<float> duan(length, 0);

  for (size_t i = 0; i < segments.size(); ++i) {
    const auto &seg = segments[i];
    int start_kline = seg.start_pos;
    int end_kline = seg.end_pos;

    if (seg.dir == Direction::UP) {
      if (i == 0) {
        duan[start_kline] = -1; // 第一个线段标记起点
      }
      // 标记中间高点
      float max_high = high[end_kline];
      duan[end_kline] = 0.5;
      for (int j = seg.vertex_start; j <= seg.vertex_end; ++j) {
        if (vertexes[j].type == 1 && high[vertexes[j].pos] >= max_high) {
          max_high = high[vertexes[j].pos];
          duan[vertexes[j].pos] = 0.5;
        }
      }
      duan[end_kline] = 1;
    } else {
      if (i == 0) {
        duan[start_kline] = 1;
      }
      // 标记中间低点
      float min_low = low[end_kline];
      duan[end_kline] = -0.5;
      for (int j = seg.vertex_start; j <= seg.vertex_end; ++j) {
        if (vertexes[j].type == -1 && low[vertexes[j].pos] <= min_low) {
          min_low = low[vertexes[j].pos];
          duan[vertexes[j].pos] = -0.5;
        }
      }
      duan[end_kline] = -1;
    }
  }

  // 标记第一处非线段区域（用于可视化）
  for (int i = 0; i < length; ++i) {
    if (duan[i] == 0) {
      duan[i] = -4;
      break;
    }
  }

  return duan;
}

// ========================================
// xd_v2: 线段极值获取
// ========================================

// 获取线段特征序列的极值价格
// 向上线段：返回特征序列的 MAX(high)
// 向下线段：返回特征序列的 MIN(low)
float get_segment_extreme_price(const SegmentState &seg,
                                const std::vector<Vertex> &vertexes,
                                const std::vector<float> &high,
                                const std::vector<float> &low, int length) {
  // 参数校验
  if (seg.vertex_start < 0 || seg.vertex_start >= vertexes.size() ||
      seg.vertex_end < 0 || seg.vertex_end >= vertexes.size() ||
      seg.vertex_start >= seg.vertex_end) {
    return 0.0f;
  }

  // 提取线段的特征序列
  // 特征序列从 vertex_start + 1 开始（第一个对手笔）
  std::vector<FeatureElement> features;
  for (int i = seg.vertex_start + 1; i <= seg.vertex_end; ++i) {
    FeatureElement elem =
        FeatureSequence::extract_one(vertexes, i, high, low, length);

    // 跳过无效元素（未找到反向顶点）
    if (elem.end_vertex_idx < 0) {
      break;
    }

    // 确保特征序列元素在线段范围内
    if (elem.end_vertex_idx > seg.vertex_end) {
      break;
    }

    features.push_back(elem);

    // 跳过已处理的顶点，每个特征序列跨越两个顶点
    i = elem.end_vertex_idx;
  }

  if (features.empty()) {
    return 0.0f;
  }

  // 合并包含关系
  FeatureSequence::merge_include(features, seg.dir);

  if (features.empty()) {
    return 0.0f;
  }

  // 根据线段方向返回极值
  if (seg.dir == Direction::UP) {
    // 向上线段：返回特征序列的最大 HIGH
    float max_high = features[0].high;
    for (const auto &f : features) {
      max_high = std::max(max_high, f.high);
    }
    return max_high;
  } else {
    // 向下线段：返回特征序列的最小 LOW
    float min_low = features[0].low;
    for (const auto &f : features) {
      min_low = std::min(min_low, f.low);
    }
    return min_low;
  }
}

// ========================================
// 主函数
// ========================================

std::vector<float> recognise_duan(int length, std::vector<float> &bi,
                                  std::vector<float> &high,
                                  std::vector<float> &low) {
  std::vector<float> duan(length, 0);
  if (length == 0 || is_expired())
    return duan;

  std::vector<Vertex> vertexes = extract_vertices(bi);
  if (vertexes.empty())
    return duan;

  // 查找第一线段
  auto first_result = find_first_segment(vertexes, high, low, length);
  if (!first_result.second)
    return duan;

  std::vector<SegmentState> segments;
  segments.push_back(first_result.first);

  // 查找后续线段
  find_subsequent_segments(segments, vertexes, high, low, length);

  return mark_segments(segments, vertexes, high, low, length);
}

#include "czsc.h"

int check_gap(std::vector<Bar> &raw_bars, StdBar &s_bar, StdBar &e_bar, int dir)
{
    int gap_count = 0;
    if (gapCountAsOneBar)
    {
        if (dir == 1)
        {
            for (int i = s_bar.low_vertex_raw_pos; i < e_bar.high_vertex_raw_pos; i++)
            {
                if (raw_bars.at(i + 1).low > raw_bars.at(i).high)
                {
                    Bar &hb = *std::max_element(
                        raw_bars.begin() + s_bar.low_vertex_raw_pos,
                        raw_bars.begin() + i + 1,
                        [](Bar a, Bar b)
                        { return a.high < b.high; });
                    Bar &lb = *std::min_element(
                        raw_bars.begin() + i + 1,
                        raw_bars.begin() + e_bar.high_vertex_raw_pos + 1,
                        [](Bar a, Bar b)
                        { return a.low < b.low; });
                    if (lb.low > hb.high)
                    {
                        gap_count = 1;
                        break;
                    }
                }
            }
        }
        else if (dir == -1)
        {
            for (int i = s_bar.high_vertex_raw_pos; i < e_bar.low_vertex_raw_pos; i++)
            {
                if (raw_bars.at(i + 1).high < raw_bars.at(i).low)
                {
                    Bar &lb = *std::min_element(
                        raw_bars.begin() + s_bar.high_vertex_raw_pos,
                        raw_bars.begin() + i + 1,
                        [](Bar a, Bar b)
                        { return a.low < b.low; });
                    Bar &hb = *std::max_element(
                        raw_bars.begin() + i + 1,
                        raw_bars.begin() + e_bar.low_vertex_raw_pos + 1,
                        [](Bar a, Bar b)
                        { return a.high < b.high; });
                    if (hb.high < lb.low)
                    {
                        gap_count = 1;
                        break;
                    }
                }
            }
        }
    }
    return gap_count;
}

/**
 * @brief 判断两个合并K线之间是否成立一笔
 *
 * 该函数用于检查从索引s到e之间的标准化K线是否构成有效的笔结构。
 * 根据缠中说禅理论，笔是由至少5根K线组成的，包含顶分型和底分型。
 *
 * @param raw_bars 原始K线数据向量
 * @param bars 标准化K线数据向量
 * @param factors 笔的端点分型
 * @param s 起始索引（标准化K线中的位置）
 * @param e 结束索引（标准化K线中的位置）
 * @param options 缠论配置选项，包含笔模式等参数
 *
 * @return bool 返回true表示成立一笔，false表示不成立一笔
 *
 * @note 函数会根据不同的笔模式（bi_mode）采用不同的判断标准：
 *        - 模式4：最少4根K线，非严格模式
 *        - 模式5：最少5根K线，非严格模式
 *        - 模式6：最少5根K线，严格模式
 *
 * 算法逻辑：
 * 1. 根据配置确定最小K线数量和严格模式
 * 2. 检查向上笔或向下笔的成立条件
 * 3. 验证价格关系（新高/新低）
 * 4. 检查分型是否满足重叠条件
 * 5. 处理缺口情况并计数
 * 6. 特殊情况下允许非完备笔成立
 * 7. 处理跳空缺口破位情况
 */
bool check_bi(std::vector<Bar> &raw_bars, std::vector<StdBar> &bars,
              std::vector<StdBar> &factors, size_t s, size_t e,
              ChanOptions &options) {
  float bi_min_stick_count = 5;
  bool bi_special_strict_mode = true;
  if (options.bi_mode == 4) {
    bi_min_stick_count = 4;
    bi_special_strict_mode = false;
  } else if (options.bi_mode == 5) {
    bi_min_stick_count = 5;
    bi_special_strict_mode = false;
  } else if (options.bi_mode == 6) {
    bi_min_stick_count = 5;
    bi_special_strict_mode = true;
  }

  if (e > s) {
    StdBar &bar1 = bars.at(s);
    StdBar &bar2 = bars.at(e);
    if (bar2.direction == 1 && bar1.factor == -1) {
      // 检查是不是向上笔
      // 起笔不限K线数量
      if (factors.size() == 1) {
        return true;
      }
      // 结束K是从起点K以来最高的
      StdBar hb = bars.at(s + 1);
      for (size_t i = s + 2; i < e; i++) {
        if (bars.at(i).high_high > hb.high_high) {
          hb = bars.at(i);
        }
      }
      if (bar2.high_high <= hb.high_high) {
        return false;
      }
      // 前一笔不够标准的时候
      if (factors.size() >= 4) {
        StdBar &f1 = factors.at(factors.size() - 4);
        StdBar &f3 = factors.at(factors.size() - 2);
        StdBar &f4 = factors.at(factors.size() - 1);
        int gapCount = check_gap(raw_bars, f3, f4, -1);
        if (f4.low_vertex_raw_pos - f3.high_vertex_raw_pos + gapCount <
                bi_min_stick_count - 1 &&
            bar2.pos - bar1.pos < 8 && f1.high_high > f3.high_high &&
            bar2.high_high < f3.high_high) {
          return false;
        }
      }

      // 找到bar1之后的第一个bar.factor=1的bar
      int first_top_factor_pos = -1;
      for (size_t i = s + 1; i < e; i++) {
        if (bars.at(i).factor == 1) {
          first_top_factor_pos = i;
          break;
        }
      }

      // 计算factor_high
      float factor_high;
      if (first_top_factor_pos != -1) {
        factor_high =
            std::min(bar1.factor_high, bars.at(first_top_factor_pos).high);
      } else {
        factor_high = bar1.factor_high;
      }

      bool fractal_satisfied = false;
      if (bi_special_strict_mode) {
        if (bar2.high > factor_high) {
          // 分型没有重叠，并且有1根独立K线不同时和顶底重叠
          for (size_t j = s + 2; j < e - 1; j++) {
            if (bars.at(j).high > bar1.high && bars.at(j).low < bar2.low) {
              fractal_satisfied = true;
              break;
            }
          }
        }
      } else {
        if (bar2.high > factor_high) {
          fractal_satisfied = true;
        }
      }
      if (fractal_satisfied) {
        // 存在缺口没有回补计数1根K线
        int gapCount = check_gap(raw_bars, bar1, bar2, 1);
        if (bar2.pos - bar1.pos + gapCount >= bi_min_stick_count - 1 &&
            bar2.high_vertex_raw_pos - bar1.low_vertex_raw_pos + gapCount >=
                4) {
          return true;
        } else if (factors.size() > 1 &&
                   bar2.high > factors.at(factors.size() - 2).high &&
                   bar2.pos - bar1.pos > 1) {
          return true;
        }
      }
      int count = 0;
      for (size_t j = s + 1; j < e; j++) {
        if (bars.at(j).factor == 1) {
          count++;
        }
      }
      if (count >= 2) {
        return true;
      }
    } else if (bar2.direction == -1 && bar1.factor == 1) {
      // 检查是不是向下笔
      // 起笔不限K线数量
      if (factors.size() == 1) {
        return true;
      }
      // 结束K是从起点K以来最低的
      StdBar lb = bars.at(s + 1);
      for (size_t i = s + 2; i < e; i++) {
        if (bars.at(i).low_low < lb.low_low) {
          lb = bars.at(i);
        }
      }
      if (bar2.low_low >= lb.low_low) {
        return false;
      }
      // 前一笔不够标准的时候
      if (factors.size() >= 4) {
        StdBar &f1 = factors.at(factors.size() - 4);
        StdBar &f3 = factors.at(factors.size() - 2);
        StdBar &f4 = factors.at(factors.size() - 1);
        int gapCount = check_gap(raw_bars, f3, f4, 1);
        if (f4.high_vertex_raw_pos - f3.low_vertex_raw_pos + gapCount <
                bi_min_stick_count - 1 &&
            bar2.pos - bar1.pos < 8 && f1.low_low < f3.low_low &&
            bar2.low_low > f3.low_low) {
          return false;
        }
      }

      // 找到bar1之后的第一个bar.factor=-1的bar
      int first_bot_factor_pos = -1;
      for (size_t i = s + 1; i < e; i++) {
        if (bars.at(i).factor == -1) {
          first_bot_factor_pos = i;
          break;
        }
      }

      // 计算factor_low
      float factor_low;
      if (first_bot_factor_pos != -1) {
        factor_low =
            std::max(bar1.factor_low, bars.at(first_bot_factor_pos).low);
      } else {
        factor_low = bar1.factor_low;
      }

      bool fractal_satisfied = false;
      if (bi_special_strict_mode) {
        if (bar2.low < factor_low) {
          // 分型没有重叠，并且有1根独立K线不同时和顶底重叠
          for (size_t j = s + 2; j < e - 1; j++) {
            if (bars.at(j).low < bar1.low && bars.at(j).high > bar2.high) {
              fractal_satisfied = true;
              break;
            }
          }
        }
      } else {
        if (bar2.low < factor_low) {
          fractal_satisfied = true;
        }
      }
      if (fractal_satisfied) {
        // 存在缺口没有回补计数1根K线
        int gapCount = check_gap(raw_bars, bar1, bar2, -1);
        if (bar2.pos - bar1.pos + gapCount >= bi_min_stick_count - 1 &&
            bar2.low_vertex_raw_pos - bar1.high_vertex_raw_pos + gapCount >=
                4) {
          return true;
        } else if (factors.size() > 1 &&
                   bar2.low < factors.at(factors.size() - 2).low &&
                   bar2.pos - bar1.pos > 1) {
          return true;
        }
      }
      int count = 0;
      for (size_t j = s + 1; j < e; j++) {
        if (bars.at(j).factor == -1) {
          count++;
        }
      }
      if (count >= 2) {
        return true;
      }
    }
    // 处理特殊缺口, 跳空破高点或者低点
    if (factors.size() > 1) {
      if (factors.back().factor == 1 && bar2.factor == -1) {
        int count = 0;
        for (int i = bar2.pos;
             i < bar2.pos + 5 && i < static_cast<int>(bars.size()); i++) {
          if (bars.at(i).high_high < factors.at(factors.size() - 2).low_low) {
            count++;
          }
        }
        if (count >= 5) {
          return true;
        }
      }
      if (factors.back().factor == -1 && bar2.factor == 1) {
        int count = 0;
        for (int i = bar2.pos;
             i < bar2.pos + 5 && i < static_cast<int>(bars.size()); i++) {
          if (bars.at(i).low_low > factors.at(factors.size() - 2).high_high) {
            count++;
          }
        }
        if (count >= 5) {
          return true;
        }
      }
    }
  }
  return false;
}

// 辅助函数：尝试合并非完备笔（小转大笔）
bool try_merge_non_comprehensive_wave(std::vector<StdBar> &bi_vertices, 
                                      std::vector<Bar> &raw_bars,
                                      std::vector<float> &bi,
                                      int direction, 
                                      float bi_min_stick_count,
                                      ChanOptions &options) {
  if (options.merge_non_complehensive_wave != 1 || bi_vertices.size() <= 3) {
    return false;
  }
  
  StdBar &f1 = bi_vertices.at(bi_vertices.size() - 4);
  StdBar &f2 = bi_vertices.at(bi_vertices.size() - 3);
  StdBar &f3 = bi_vertices.at(bi_vertices.size() - 2);
  StdBar &f4 = bi_vertices.at(bi_vertices.size() - 1);
  int gapCount = check_gap(raw_bars, f3, f4, direction);
  
  bool can_merge = false;
  if (direction == -1) { // 向上笔
    can_merge = (f4.low_vertex_raw_pos - f3.high_vertex_raw_pos + gapCount < bi_min_stick_count - 1) &&
                (f1.high > f3.high && f2.low > f4.low);
    if (can_merge) {
      bi[f4.high_vertex_raw_pos] = -0.5;
    }
  } else { // 向下笔
    can_merge = (f4.high_vertex_raw_pos - f3.low_vertex_raw_pos + gapCount < bi_min_stick_count - 1) &&
                (f1.low < f3.low && f2.high < f4.high);
    if (can_merge) {
      bi[f4.low_vertex_raw_pos] = 0.5;
    }
  }
  
  if (can_merge) {
    bi_vertices.erase(bi_vertices.end() - 3, bi_vertices.end() - 1);
  }
  return can_merge;
}

std::vector<float> recognise_bi(int length, std::vector<float> &high,
                                std::vector<float> &low, ChanOptions &options) {
  std::vector<float> bi(length, 0.0f);
  if (length == 0) {
    return bi;
  }
  if (is_expired()) {
    return bi;
  }
  float bi_min_stick_count = 5;
  if (options.bi_mode == 4) {
    bi_min_stick_count = 4;
  } else if (options.bi_mode == 5) {
    bi_min_stick_count = 5;
  } else if (options.bi_mode == 6) {
    bi_min_stick_count = 5;
  }
  std::vector<Bar> raw_bars = recognise_bars(length, high, low);

  std::vector<StdBar> std_bars = recognise_std_bars(length, high, low);
  std::vector<StdBar> bi_vertices; // 记录笔的端点
  for (int i = 0; i < static_cast<int>(std_bars.size()); i++) {
    if (bi_vertices.size() == 0) {
      if (std_bars.at(i).factor == -1 || std_bars.at(i).factor == 1) {
        bi_vertices.push_back(std_bars.at(i));
      }
      continue;
    }

    if (std_bars.at(i).direction == 1) // 出现向上防线的合并K柱
    {
      if (bi_vertices.back().factor ==
          -1) // 前面有笔底，就要检查是否有成立向上笔的可能
      {
        if (check_bi(raw_bars, std_bars, bi_vertices, bi_vertices.back().pos, i,
                     options)) {
          // 合并小转大笔
          try_merge_non_comprehensive_wave(bi_vertices, raw_bars, bi, -1, bi_min_stick_count, options);
          
          // 满足向上笔条件的，我们把这个笔顶信号值记录为0.5，他不一定是最终的笔顶。
          bi_vertices.push_back(std_bars.at(i));
          bi[std_bars.at(i).high_vertex_raw_pos] = 0.5;
          continue;
        } else if (bi_vertices.size() > 1) {
          // 成立非完备笔，也就是虽然不满足笔的条件，但是他的幅度已经超过了前一笔的幅度
          if (std_bars.at(i).high_high >
              bi_vertices.at(bi_vertices.size() - 2).high_high) {
            // 检查前一笔是否为非完备笔，如果是则判断是否可以合并
            try_merge_non_comprehensive_wave(bi_vertices, raw_bars, bi, -1, bi_min_stick_count, options);
            
            bi_vertices.push_back(std_bars.at(i));
            // 我们不把这种笔顶信号记录为0.5，因为他不是完整笔
            continue;
          }
        }
      } else if (bi_vertices.back().direction == 1) {
        // 笔继续延申
        if (std_bars.at(i).high_high > bi_vertices.back().high_high) {
          bi_vertices.pop_back();
          bi_vertices.push_back(std_bars.at(i));
          auto sz = bi_vertices.size();
          if (check_bi(raw_bars, std_bars, bi_vertices,
                       bi_vertices.at(sz - 2).pos, bi_vertices.at(sz - 1).pos,
                       options)) {
            bi[bi_vertices.back().high_vertex_raw_pos] = 0.5;
          }
          continue;
        }
      }
    } else if (std_bars.at(i).direction == -1) {
      if (bi_vertices.back().factor == 1) {
        if (check_bi(raw_bars, std_bars, bi_vertices, bi_vertices.back().pos, i,
                     options)) {
          // 合并小转大笔
          try_merge_non_comprehensive_wave(bi_vertices, raw_bars, bi, 1, bi_min_stick_count, options);
          
          // 满足向下笔条件的，我们把这个笔底信号值记录为-0.5，他不一定是最终的笔底。
          bi_vertices.push_back(std_bars.at(i));
          bi[std_bars.at(i).low_vertex_raw_pos] = -0.5;
          continue;
        } else if (bi_vertices.size() > 1) {
          // 成立非完备笔，也就是虽然不满足笔的条件，但是他的幅度已经超过了前一笔的幅度
          if (std_bars.at(i).low_low <
              bi_vertices.at(bi_vertices.size() - 2).low_low) {
            // 检查前一笔是否为非完备笔，如果是则判断是否可以合并
            try_merge_non_comprehensive_wave(bi_vertices, raw_bars, bi, 1, bi_min_stick_count, options);
            
            bi_vertices.push_back(std_bars.at(i));
            // 我们不把这种笔底信号记录为-0.5，因为他不是完整笔
            continue;
          }
        }
      } else if (bi_vertices.back().direction == -1) {
        // 笔继续延申
        if (std_bars.at(i).low_low < bi_vertices.back().low_low) {
          bi_vertices.pop_back();
          bi_vertices.push_back(std_bars.at(i));
          auto sz = bi_vertices.size();
          if (check_bi(raw_bars, std_bars, bi_vertices,
                       bi_vertices.at(sz - 2).pos, bi_vertices.at(sz - 1).pos,
                       options)) {
            bi[bi_vertices.back().low_vertex_raw_pos] = -0.5;
          }
          continue;
        }
      }
    }
    // 这里判断是不是可以次高成笔
    if (options.force_wave_stick_count >= 15) {
      if (i - bi_vertices.back().pos >= options.force_wave_stick_count) {
        if (bi_vertices.back().factor == -1 && std_bars.at(i).factor == 1) {
          bool found = false;
          for (int j = bi_vertices.back().pos; j < i; j++) {
            if (std_bars.at(j).factor == -1) {
              if (check_bi(raw_bars, std_bars, bi_vertices, std_bars.at(j).pos,
                           i, options)) {
                found = true;
                break;
              }
            }
          }
          if (found) {
            bi_vertices.push_back(std_bars.at(i));
            continue;
          }
        } else if (bi_vertices.back().factor == 1 &&
                   std_bars.at(i).factor == -1) {
          bool found = false;
          for (int j = bi_vertices.back().pos; j < i; j++) {
            if (std_bars.at(j).factor == 1) {
              if (check_bi(raw_bars, std_bars, bi_vertices, std_bars.at(j).pos,
                           i, options)) {
                found = true;
                break;
              }
            }
          }
          if (found) {
            bi_vertices.push_back(std_bars.at(i));
            continue;
          }
        }
      }
    }
  }
  for (size_t i = 0; i < bi_vertices.size(); i++) {
    if (bi_vertices.at(i).direction == 1) {
      bi[bi_vertices.at(i).high_vertex_raw_pos] = 1;
    } else if (bi_vertices.at(i).direction == -1) {
      bi[bi_vertices.at(i).low_vertex_raw_pos] = -1;
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

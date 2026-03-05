#include "czsc.h"

/**
 * @brief 从笔标记数组中提取顶点
 * @details 遍历 bi 数组，将所有标记为笔的点（值为 1 或 -1）提取为顶点
 *
 * @param bi 笔的标记数组，其中 1 表示向上笔的终点，-1 表示向下笔的终点
 * @return std::vector<Vertex> 返回顶点集合
 */
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

/**
 * @brief 判断两个点之间是否可以构成一个有效的线段
 * @details 根据缠论的规则检查两个点之间是否可以形成一个有效的线段，主要检查：
 *          1. 是否存在缺口（gap）
 *          2. 是否满足高低点关系
 *          3. 是否满足方向性要求
 *
 * @param segments   已确认的线段集合
 * @param vertexes   所有顶点的集合
 * @param bi         笔的标记数组
 * @param pendings   待确认的顶点集合
 * @param start      待检查区间的起始位置
 * @param end        待检查区间的结束位置
 * @param high       K线图的最高价数组
 * @param low        K线图的最低价数组
 * @param direction  线段的方向(1:向上, -1:向下)
 * @return int
 */
int check_duan(std::vector<Segment> &segments, std::vector<Vertex> &vertexes, std::vector<float> &bi, std::vector<Vertex> &pendings,
               int start, int end, std::vector<float> &high, std::vector<float> &low, int direction)
{
    if (pendings.size() % 2 == 1)
    {
        return 0;
    }
    if (segments.size() > 0 && segments.back().vertexPosEnd - segments.back().vertexPosStart >= 3)
    {
        if (direction == -1 && segments.back().direction == 1)
        {
            float h = high[vertexes.at(segments.back().vertexPosStart + 1).pos];
            for (int i = segments.back().vertexPosStart + 1; i < segments.back().vertexPosEnd; i = i + 2)
            {
                if (high[vertexes.at(i).pos] > h)
                {
                    h = high[vertexes.at(i).pos];
                }
            }
            // 存在缺口
            if (low[pendings.at(end).pos] > h)
            {
                if (pendings.size() >= 6 && pendings.size() % 2 == 0 &&
                    low[pendings.at(end).pos] < low[pendings.at(start + 1).pos] && low[pendings.at(end).pos] < low[pendings.at(start + 3).pos])
                {
                    // 有5笔，且高到低分明，也算成段。
                    return end;
                }
                else if (pendings.size() == 8 && low[pendings.at(start + 3).pos] < low[pendings.at(start + 1).pos])
                {
                    return start + 3;
                }
                else
                {
                    return 0;
                }
            }
        }
        else if (direction == 1 && segments.back().direction == -1)
        {
            float l = low[vertexes.at(segments.back().vertexPosStart + 1).pos];
            for (int i = segments.back().vertexPosStart + 1; i < segments.back().vertexPosEnd; i = i + 2)
            {
                if (low[vertexes.at(i).pos] < l)
                {
                    l = low[vertexes.at(i).pos];
                }
            }
            // 存在缺口
            if (high[pendings.at(end).pos] < l)
            {
                if (pendings.size() >= 6 && pendings.size() % 2 == 0 &&
                    high[pendings.at(end).pos] > high[pendings.at(start + 1).pos] && high[pendings.at(end).pos] > high[pendings.at(start + 3).pos])
                {
                    // 有5笔，且低到高分明，也算成段。
                    return end;
                }
                else if (pendings.size() == 8 && high[pendings.at(start + 3).pos] > high[pendings.at(start + 1).pos])
                {
                    return start + 3;
                }
                else
                {
                    return 0;
                }
            }
        }
    }
    if (end - start >= 3 && pendings.at(start).type == -direction && pendings.at(end).type == direction)
    {
        if (direction == 1)
        {
            if (segments.size() > 0)
            {
                if (high[pendings.at(end).pos] > high[segments.back().start])
                {
                    return end;
                }
                auto pivots = locate_pivots(bi, high, low, direction, segments.back().start, segments.back().end);
                if (pivots.size() > 0)
                {
                    if (low[pendings.at(end - 1).pos] > pivots.back().zg)
                    {
                        return end;
                    }
                }
            }
            if (allow_second_high_low_swell)
            {
                for (int i = start + 1; i < end; i = i + 2)
                {
                    if (high[pendings.at(end).pos] > high[pendings.at(i).pos])
                    {
                        return end;
                    }
                }
            }
            else
            {
                if (high[pendings.at(end).pos] > high[pendings.at(start + 1).pos])
                {
                    return end;
                }
            }
        }
        else if (direction == -1)
        {
            if (segments.size() > 0)
            {
                if (low[pendings.at(end).pos] < low[segments.back().start])
                {
                    // 破前面线段的低点是直接算一段的。
                    return end;
                }
                auto pivots = locate_pivots(bi, high, low, direction, segments.back().start, segments.back().end);
                if (pivots.size() > 0)
                {
                    // 有中枢的三卖形态，也是直接就算成段了，这个时候段可能是次高点。
                    if (high[pendings.at(end - 1).pos] < pivots.back().zd)
                    {
                        return end;
                    }
                }
            }
            if (allow_second_high_low_swell)
            {
                // 这个处理方法其实不太好。
                for (int i = start + 1; i < end; i = i + 2)
                {
                    if (low[pendings.at(end).pos] < low[pendings.at(i).pos])
                    {
                        return end;
                    }
                }
            }
            else
            {
                if (low[pendings.at(end).pos] < low[pendings.at(start + 1).pos])
                {
                    return end;
                }
            }
        }
    }

    return 0;
}

/**
 * @brief 识别K线图中的线段
 * @details 根据缠论的规则，从已经标记好的笔中识别出线段。
 *          线段的识别过程包括：
 *          1. 找出所有可能的顶点
 *          2. 确定第一个线段
 *          3. 逐个检查后续点，确定新的线段
 *          4. 处理线段的合并
 *          5. 标记线段的方向和关键点
 *
 * @param length  K线图的长度
 * @param bi      笔的标记数组，其中1表示向上笔的终点，-1表示向下笔的终点
 * @param high    K线图的最高价数组
 * @param low     K线图的最低价数组
 * @return std::vector<float>  返回线段的标记数组，其中：
 *                             0 表示没有特征的普通点
 *                             1 表示向上线段的终点
 *                             -1 表示向下线段的终点
 *                             0.5 表示向上线段中间点
 *                             -0.5 表示向下线段中间点
 *                             -4 表示这是线段
 */
std::vector<float> recognise_duan(int length, std::vector<float> &bi, std::vector<float> &high, std::vector<float> &low)
{
    std::vector<float> duan(length, 0);
    if (length == 0) {
      return duan;
    }
    if (is_expired()) {
      return duan;
    }
    std::vector<Vertex> vertexes = extract_vertices(bi);
    std::vector<Segment> segments;
    std::vector<Vertex> pending;
    int vertexes_num = static_cast<int>(vertexes.size());
    // 第一次循环是找第一个段的成立
    for (int i = 0; i < vertexes_num; i++) {
      if (vertexes.at(i).type == 1) {
        int k = -1;
        for (int j = i - 1; j >= 0; j--) {
          if (vertexes.at(j).type == -1) {
            if (k == -1 || low[vertexes.at(j).pos] < low[vertexes.at(k).pos]) {
              k = j;
            }
          } else if (vertexes.at(j).type == 1) {
            if (high[vertexes.at(j).pos] > high[vertexes.at(i).pos]) {
              break;
            }
          }
        }
        if (k >= 0 && i - k >= 2) {
          Segment d = Segment();
          d.start = vertexes.at(k).pos;
          d.end = vertexes.at(i).pos;
          d.vertexPosStart = k;
          d.vertexPosEnd = i;
          d.comprehensive_pos = d.end;
          d.direction = 1;
          segments.push_back(d);
          pending.push_back(vertexes.at(i));
          break;
        }
      } else if (vertexes.at(i).type == -1) {
        int k = -1;
        for (int j = i - 1; j >= 0; j--) {
          if (vertexes.at(j).type == 1) {
            if (k == -1 ||
                high[vertexes.at(j).pos] > high[vertexes.at(k).pos]) {
              k = j;
            }
          } else if (vertexes.at(j).type == -1) {
            if (low[vertexes.at(j).pos] < low[vertexes.at(i).pos]) {
              break;
            }
          }
        }
        if (k >= 0 && i - k >= 2) {
          Segment d = Segment();
          d.start = vertexes.at(k).pos;
          d.end = vertexes.at(i).pos;
          d.vertexPosStart = k;
          d.vertexPosEnd = i;
          d.comprehensive_pos = d.end;
          d.direction = -1;
          segments.push_back(d);
          pending.push_back(vertexes.at(i));
          break;
        }
      }
    }
    if (segments.size() == 0) {
      return duan;
    }
    for (int i = segments.back().vertexPosEnd + 1; i < vertexes_num; i++)
    {
        // 这里统一处理段是不是需要合并
        if (segments.size() > 2)
        {
            if (!segments.back().confirmed)
            {
                if (segments.back().vertexPosEnd - segments.back().vertexPosStart >= 3)
                {
                    segments.back().confirmed = true;
                }
                else
                {
                    if (segments.back().direction == 1)
                    {
                        bool merge = true;
                        if (!(high[segments.at(segments.size() - 1).end] > high[segments.at(segments.size() - 3).end] &&
                              low[segments.at(segments.size() - 1).start] > low[segments.at(segments.size() - 3).start]))
                        {
                            merge = false;
                        }
                        else
                        {
                            if (segments.at(segments.size() - 2).vertexPosEnd - segments.at(segments.size() - 2).vertexPosStart >= 5)
                            {
                                int pos1 = segments.at(segments.size() - 2).vertexPosStart + 1;
                                int pos3 = segments.at(segments.size() - 2).vertexPosStart + 3;
                                int pos4 = segments.at(segments.size() - 2).vertexPosStart + 4;
                                float p1 = low[vertexes.at(pos1).pos];
                                float p3 = low[vertexes.at(pos3).pos];
                                float p4 = high[vertexes.at(pos4).pos];
                                if (p4 < p1)
                                {
                                    merge = false;
                                }
                                else
                                {
                                    float p = std::max(p1, p3);
                                    for (int j = segments.at(segments.size() - 2).vertexPosEnd - 1; j >= pos4 + 2; j = j - 2)
                                    {
                                        if (high[vertexes.at(j).pos] < p)
                                        {
                                            merge = false;
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                        if (merge)
                        {
                            segments.at(segments.size() - 3).end = segments.back().end;
                            segments.at(segments.size() - 3).vertexPosEnd = segments.back().vertexPosEnd;
                            segments.pop_back();
                            segments.pop_back();
                        }
                        else
                        {
                            segments.back().confirmed = true;
                        }
                    }
                    else if (segments.back().direction == -1)
                    {
                        bool merge = true;
                        if (!(low[segments.at(segments.size() - 1).end] < low[segments.at(segments.size() - 3).end] &&
                              high[segments.at(segments.size() - 1).start] < high[segments.at(segments.size() - 3).start]))
                        {
                            merge = false;
                        }
                        else
                        {
                            if (segments.at(segments.size() - 2).vertexPosEnd - segments.at(segments.size() - 2).vertexPosStart >= 5)
                            {
                                int pos1 = segments.at(segments.size() - 2).vertexPosStart + 1;
                                int pos3 = segments.at(segments.size() - 2).vertexPosStart + 3;
                                int pos4 = segments.at(segments.size() - 2).vertexPosStart + 4;
                                float p1 = high[vertexes.at(pos1).pos];
                                float p3 = high[vertexes.at(pos3).pos];
                                float p4 = low[vertexes.at(pos4).pos];
                                if (p4 > p1)
                                {
                                    merge = false;
                                }
                                else
                                {
                                    float p = std::min(p1, p3);
                                    for (int j = segments.at(segments.size() - 2).vertexPosEnd - 1; j >= pos4 + 2; j = j - 2)
                                    {
                                        if (low[vertexes.at(j).pos] > p)
                                        {
                                            merge = false;
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                        if (merge)
                        {
                            segments.at(segments.size() - 3).end = segments.back().end;
                            segments.at(segments.size() - 3).vertexPosEnd = segments.back().vertexPosEnd;
                            segments.pop_back();
                            segments.pop_back();
                        }
                        else
                        {
                            segments.back().confirmed = true;
                        }
                    }
                }
            }
        }
        Vertex &v = vertexes.at(i);
        if (v.type == 1)
        {
            if (segments.back().direction == 1)
            {
                // 前一段是向上段
                if (high[v.pos] > high[segments.back().end])
                {
                    if (pending.size() > 1)
                    {
                        // 这里实际上发生了一笔成段的处理方法
                        // 以后要考虑要不要这种处理方法
                        size_t pos = 1;
                        for (size_t j = 1; j < pending.size(); j = j + 2)
                        {
                            if (low[pending.at(j).pos] < low[pending.at(pos).pos])
                            {
                                pos = j;
                            }
                        }
                        if (low[pending.at(pos).pos] < low[segments.back().start])
                        {
                            Segment d = Segment();
                            d.start = pending.at(0).pos;
                            d.end = pending.at(pos).pos;
                            d.vertexPosStart = pending.at(0).logicPos;
                            d.vertexPosEnd = pending.at(pos).logicPos;
                            d.comprehensive_pos = d.end;
                            d.direction = -1;
                            segments.push_back(d);
                            i = pending.at(pos).logicPos;
                            Vertex &s = pending.at(pos);
                            pending.clear();
                            pending.push_back(s);
                            continue;
                        }
                    }
                    // 执行到这里是向上线段继续延续。
                    segments.back().end = v.pos;
                    segments.back().vertexPosEnd = v.logicPos;
                    pending.clear();
                    pending.push_back(v);
                    continue;
                }
                // 程序运行到这里的时候，是前一段是向上段，当前的高点没有创新高。
                pending.push_back(v);
                if (!allow_second_high_low_swell)
                {
                    // 这里也会发生一笔成段的划分
                    // 要考虑以后是不是要修改
                    if (pending.size() >= 7 && high[pending.at(2).pos] < low[pending.at(5).pos])
                    {
                        // 强制向下段
                        size_t pos = 1;
                        for (size_t j = 1; j < pending.size(); j = j + 2)
                        {
                            if (low[pending.at(j).pos] <= low[pending.at(pos).pos])
                            {
                                pos = j;
                            }
                        }
                        Segment d = Segment();
                        d.start = pending.at(0).pos;
                        d.end = pending.at(pos).pos;
                        d.vertexPosStart = pending.at(0).logicPos;
                        d.vertexPosEnd = pending.at(pos).logicPos;
                        d.comprehensive_pos = d.end;
                        d.direction = -1;
                        segments.push_back(d);
                        i = pending.at(pos).logicPos;
                        Vertex &s = pending.at(pos);
                        pending.clear();
                        pending.push_back(s);
                    }
                }
            }
            else
            {
                // 前一段是向下段
                pending.push_back(v);
                int form_duan_i = 0;
                if (pending.size() >= 4)
                {
                    form_duan_i = check_duan(segments, vertexes, bi, pending, 0, static_cast<int>(pending.size()) - 1, high, low, 1);
                }
                if (form_duan_i > 0)
                {
                    if (form_duan_i == static_cast<int>(pending.size()) - 1)
                    {
                        Segment d = Segment();
                        d.start = pending.at(0).pos;
                        d.end = pending.back().pos;
                        d.vertexPosStart = pending.at(0).logicPos;
                        d.vertexPosEnd = pending.back().logicPos;
                        d.comprehensive_pos = d.end;
                        d.direction = 1;
                        segments.push_back(d);
                        pending.clear();
                        pending.push_back(v);
                    } else {
                        Segment d = Segment();
                        d.start = pending.at(0).pos;
                        d.end = pending.at(form_duan_i).pos;
                        d.vertexPosStart = pending.at(0).logicPos;
                        d.vertexPosEnd = pending.at(form_duan_i).logicPos;
                        d.comprehensive_pos = d.end;
                        d.direction = 1;
                        segments.push_back(d);
                        pending.erase(pending.begin(), pending.begin() + form_duan_i);
                    }
                }
            }
        }
        else if (v.type == -1)
        {
            if (segments.back().direction == -1)
            {
                // 前一段是向下段
                if (low[v.pos] < low[segments.back().end])
                {
                    if (pending.size() > 1)
                    {
                        size_t pos = 1;
                        for (size_t j = 1; j < pending.size(); j = j + 2)
                        {
                            if (high[pending.at(j).pos] > high[pending.at(pos).pos])
                            {
                                pos = j;
                            }
                        }
                        if (high[pending.at(pos).pos] > high[segments.back().start])
                        {
                            Segment d = Segment();
                            d.start = pending.at(0).pos;
                            d.end = pending.at(pos).pos;
                            d.vertexPosStart = pending.at(0).logicPos;
                            d.vertexPosEnd = pending.at(pos).logicPos;
                            d.comprehensive_pos = d.end;
                            d.direction = 1;
                            segments.push_back(d);
                            i = pending.at(pos).logicPos;
                            Vertex &s = pending.at(pos);
                            pending.clear();
                            pending.push_back(s);
                            continue;
                        }
                    }
                    segments.back().end = v.pos;
                    segments.back().vertexPosEnd = v.logicPos;
                    pending.clear();
                    pending.push_back(v);
                    continue;
                }
                pending.push_back(v);
                if (!allow_second_high_low_swell)
                {
                    if (pending.size() >= 7 && low[pending.at(2).pos] > high[pending.at(5).pos])
                    {
                        // 强制向上段
                        size_t pos = 1;
                        for (size_t j = 1; j < pending.size(); j = j + 2)
                        {
                            if (high[pending.at(j).pos] >= high[pending.at(pos).pos])
                            {
                                pos = j;
                            }
                        }
                        Segment d = Segment();
                        d.start = pending.at(0).pos;
                        d.end = pending.at(pos).pos;
                        d.vertexPosStart = pending.at(0).logicPos;
                        d.vertexPosEnd = pending.at(pos).logicPos;
                        d.comprehensive_pos = d.end;
                        d.direction = 1;
                        segments.push_back(d);
                        i = pending.at(pos).logicPos;
                        Vertex &s = pending.at(pos);
                        pending.clear();
                        pending.push_back(s);
                    }
                }
            }
            else
            {
                // 前一段是向上段
                pending.push_back(v);
                int form_duan_i = 0;
                if (pending.size() >= 4)
                {
                    form_duan_i = check_duan(segments, vertexes, bi, pending, 0, static_cast<int>(pending.size()) - 1, high, low, -1);
                }
                if (form_duan_i > 0)
                {
                    if (form_duan_i == static_cast<int>(pending.size()) - 1)
                    {
                        Segment d = Segment();
                        d.start = pending.at(0).pos;
                        d.end = pending.back().pos;
                        d.vertexPosStart = pending.at(0).logicPos;
                        d.vertexPosEnd = pending.back().logicPos;
                        d.comprehensive_pos = d.end;
                        d.direction = -1;
                        segments.push_back(d);
                        pending.clear();
                        pending.push_back(v);
                    }
                    else
                    {
                        Segment d = Segment();
                        d.start = pending.at(0).pos;
                        d.end = pending.at(form_duan_i).pos;
                        d.vertexPosStart = pending.at(0).logicPos;
                        d.vertexPosEnd = pending.at(form_duan_i).logicPos;
                        d.comprehensive_pos = d.end;
                        d.direction = -1;
                        segments.push_back(d);
                        pending.erase(pending.begin(), pending.begin() + form_duan_i);
                    }
                }
            }
        }
    }

    int size = static_cast<int>(segments.size());
    for (int i = 0; i < size; i++)
    {
        Segment &d = segments.at(i);
        if (d.direction == 1)
        {
            duan[d.comprehensive_pos] = 0.5;
            float hi = high[d.comprehensive_pos];
            for (int x = d.comprehensive_pos + 1; x < d.end; x++)
            {
                if (bi[x] == 1.0 && high[x] >= hi)
                {
                    duan[x] = 0.5;
                    hi = high[x];
                }
            }
            if (i == 0)
            {
                duan[d.start] = -1;
                duan[d.end] = 1;
            }
            else
            {
                duan[d.end] = 1;
            }
        }
        else if (d.direction == -1)
        {
            duan[d.comprehensive_pos] = -0.5;
            float lo = low[d.comprehensive_pos];
            for (int x = d.comprehensive_pos + 1; x < d.end; x++)
            {
                if (bi[x] == -1.0 && low[x] <= lo)
                {
                    duan[x] = -0.5;
                    lo = low[x];
                }
            }
            if (i == 0)
            {
                duan[d.start] = 1;
                duan[d.end] = -1;
            }
            else
            {
                duan[d.end] = -1;
            }
        }
    }
    for (int i = 0; i < length; i++)
    {
        if (duan[i] == 0)
        {
            duan[i] = -4;
            break;
        }
    }
    return duan;
}

#include "Comm.h"

BiData::BiData(int count, std::vector<float> high_list, std::vector<float> low_list)
{
    this->count = count;
    this->high_list = high_list;
    this->low_list = low_list;
    create_bar_list();
    create_bi_list();
}

void BiData::create_bar_list()
{
    for (int i = 0; i < count; i++)
    {
        Bar bar = Bar();
        bar.i = i;
        bar.high = high_list[i];
        bar.low = low_list[i];
        bar_list.push_back(bar);
        float direction = 1;
        size_t size = merged_bar_list.size();
        if (size > 0)
        {
            MergedBar* prev = &merged_bar_list.at(size - 1);
            if (bar.high > prev->high && bar.low > prev->low)
            {
                direction = 1;
            }
            else if (bar.high < prev->high && bar.low < prev->low)
            {
                direction = -1;
            }
            else
            {
                direction = prev->direction;
                if (direction == 1)
                {
                    prev->high = std::max(prev->high, bar.high);
                    prev->high_high = std::max(prev->high_high, bar.high);
                    prev->low = std::max(prev->low, bar.low);
                    prev->low_low = std::min(prev->low_low, bar.low);
                    prev->end = i;
                    continue;
                }
                else if (direction == -1)
                {
                    prev->high = std::min(prev->high, bar.high);
                    prev->high_high = std::max(prev->high_high, bar.high);
                    prev->low = std::min(prev->low, bar.low);
                    prev->low_low = std::min(prev->low_low, bar.low);
                    prev->end = i;
                    continue;
                }
            }
        }
        MergedBar merged_bar = MergedBar();
        merged_bar.start = i;
        merged_bar.end = i;
        merged_bar.high = bar.high;
        merged_bar.high_high = bar.high;
        merged_bar.low = bar.low;
        merged_bar.low_low = bar.low;
        merged_bar.direction = direction;
        merged_bar_list.push_back(merged_bar);
    }
}

void BiData::create_bi_list()
{
    for (int i = 0; i < static_cast<int>(merged_bar_list.size()); i++)
    {
        MergedBar* bar = &merged_bar_list.at(i);
        if (bi_list.empty()) {
            Bi bi = Bi();
            bi.start = i;
            bi.end = i;
            bi.direction = bar->direction;
            bi.identified = true;
            bi_list.push_back(bi);
            continue;
        }
        Bi* cur_bi;
        Bi* pre_bi;
        cur_bi = &bi_list.at(bi_list.size() - 1);
        if (bi_list.size() > 1) {
            pre_bi = &bi_list.at(bi_list.size() - 2);
        }
        if (cur_bi->direction == 1) {
            if (bar->high > merged_bar_list.at(cur_bi->end).high) {
                cur_bi->end = i;
                int idx = cur_bi->start-1 < 0 ? 0 : cur_bi->start-1;
                if (!cur_bi->identified && pre_bi && merged_bar_list.at(cur_bi->end).high > merged_bar_list.at(pre_bi->start).high) {
                    cur_bi->identified = true;
                } else if (!cur_bi->identified && cur_bi->end - cur_bi->start >= 4) {
                    if (merged_bar_list.at(cur_bi->end).high > merged_bar_list.at(idx).high || std::count_if(merged_bar_list.begin() + cur_bi->start, merged_bar_list.begin() + cur_bi->end, [](MergedBar bar) { return bar.direction == -1; }) > 1) {
                        cur_bi->identified = true;
                    }
                }
            } else {
                if (cur_bi->identified) {
                    Bi bi = Bi();
                    bi.start = i - 1;
                    bi.end = i;
                    bi.direction = -1;
                    bi_list.push_back(bi);
                } else {
                    if (pre_bi && bar->low < merged_bar_list.at(cur_bi->start).low) {
                        bi_list.pop_back();
                        pre_bi->end = i;
                    }
                }
            }
        } else {
            if (bar->low < merged_bar_list.at(cur_bi->end).low) {
                cur_bi->end = i;
                int idx = cur_bi->start-1 < 0 ? 0 : cur_bi->start-1;
                if (!cur_bi->identified && pre_bi && merged_bar_list.at(cur_bi->end).low < merged_bar_list.at(pre_bi->start).low) {
                    cur_bi->identified = true;
                } else if (!cur_bi->identified && cur_bi->end - cur_bi->start >= 4) {
                    if (merged_bar_list.at(cur_bi->end).low < merged_bar_list.at(idx).low || std::count_if(merged_bar_list.begin() + cur_bi->start, merged_bar_list.begin() + cur_bi->end, [](MergedBar bar) { return bar.direction == 1; }) > 1) {
                        cur_bi->identified = true;
                    }
                }
            } else {
                if (cur_bi->identified) {
                    Bi bi = Bi();
                    bi.start = i -1;
                    bi.end = i;
                    bi.direction = 1;
                    bi_list.push_back(bi);
                } else {
                    if (pre_bi && bar->high > merged_bar_list.at(cur_bi->start).high) {
                        bi_list.pop_back();
                        pre_bi->end = i;
                    }
                }
            }
        }
    }
    if (!bi_list.empty()) {
        Bi* bi = &bi_list.at(0);
        if (bi->start == bi->end) {
            bi_list.erase(bi_list.begin());
        }
    }
    if (!bi_list.empty()) {
        Bi* bi = &bi_list.back();
        int idx = bi->start-1 < 0 ? 0 : bi->start-1;
        if (bi->direction == 1) {
            if (merged_bar_list.at(bi->end).high <= merged_bar_list.at(idx).high) {
                bi_list.pop_back();
            }
        } else {
            if (merged_bar_list.at(bi->end).low >= merged_bar_list.at(idx).low) {
                bi_list.pop_back();
            }
        }
    }
    // 上面计算的笔的开始和结束是按合并后的K线的，调整为原始K线的开始和结束。
    for (size_t i = 0; i < bi_list.size(); i++)
    {
        Bar b;
        if (bi_list.at(i).direction == 1)
        {
            MergedBar* merged_bar1 = &merged_bar_list.at(bi_list.at(i).start);
            MergedBar* merged_bar2 = &merged_bar_list.at(bi_list.at(i).end);
            b = *std::min_element(
                bar_list.begin() + merged_bar1->start,
                bar_list.begin() + merged_bar1->end + 1,
                [](Bar a, Bar b) { return a.low < b.low; });
            bi_list.at(i).start = b.i;
            b = *std::max_element(
                bar_list.begin() + merged_bar2->start,
                bar_list.begin() + merged_bar2->end + 1,
                [](Bar a, Bar b) { return a.high < b.high; });
            bi_list.at(i).end = b.i;
        }
        else
        {
            MergedBar* merged_bar1 = &merged_bar_list.at(bi_list.at(i).start);
            MergedBar* merged_bar2 = &merged_bar_list.at(bi_list.at(i).end);
            b = *std::max_element(
                bar_list.begin() + merged_bar1->start,
                bar_list.begin() + merged_bar1->end + 1,
                [](Bar a, Bar b) { return a.high < b.high; });
            bi_list.at(i).start = b.i;
            b = *std::min_element(
                bar_list.begin() + merged_bar2->start,
                bar_list.begin() + merged_bar2->end + 1,
                [](Bar a, Bar b) { return a.low < b.low; });
            bi_list.at(i).end = b.i;
        }
    }
}

std::vector<Bi> BiData::get_bi_list()
{
    return bi_list;
}

BiData::~BiData()
{
}

DuanData::DuanData(int count, std::vector<float> bi, std::vector<float> high, std::vector<float> low)
{
    this->count = count;
    this->bi = bi;
    this->high = high;
    this->low = low;

    for (int i = 0; i < count; i++)
    {
        if (bi[i] == 1)
        {
            Vertex vertex = Vertex();
            vertex.i = i;
            vertex.type = 1;
            vertex_list.push_back(vertex);
        }
        else if (bi[i] == -1)
        {
            Vertex vertex = Vertex();
            vertex.i = i;
            vertex.type = -1;
            vertex_list.push_back(vertex);
        }
    }

    std::vector<Vertex> pending;
    for (size_t i = 3; i < vertex_list.size(); i++)
    {
        Vertex& v = vertex_list.at(i);
        if (v.type == 1)
        {
            if (duan_list.size() == 0)
            {
                Vertex& v1 = vertex_list.at(i - 3);
                Vertex& v2 = vertex_list.at(i - 2);
                Vertex& v3 = vertex_list.at(i - 1);
                Vertex& v4 = vertex_list.at(i);
                if (high[v4.i] > high[v2.i] && low[v3.i] > low[v1.i])
                {
                    Duan d = Duan();
                    d.start = v1.i;
                    d.end = v4.i;
                    d.direction = 1;
                    duan_list.push_back(d);
                    pending.clear();
                    pending.push_back(v);
                    continue;
                }
            }
            else
            {
                Duan& prev1 = duan_list.back();
                if (prev1.direction == 1)
                {
                    if (high[v.i] > high[prev1.end])
                    {
                        prev1.end = v.i;
                        pending.clear();
                        pending.push_back(v);
                        continue;
                    }
                    pending.push_back(v);
                    if (pending.size() >= 7)
                    {
                        bool isDuan = true;
                        for (size_t j = 2; j < pending.size(); j = j + 2)
                        {
                            if (high[pending.back().i] < high[pending.at(j).i])
                            {
                                isDuan = false;
                                break;
                            }
                        }
                        if (isDuan)
                        {
                            Duan d1 = Duan();
                            d1.start = pending.at(0).i;
                            d1.end = pending.at(1).i;
                            d1.direction = -1;
                            duan_list.push_back(d1);
                            Duan d2 = Duan();
                            d2.start = pending.at(1).i;
                            d2.end = pending.back().i;
                            d2.direction = 1;
                            duan_list.push_back(d2);
                            pending.clear();
                            pending.push_back(v);
                            continue;
                        }
                    }
                }
                else
                {
                    // prev1->direction == -1
                    pending.push_back(v);
                    if (pending.size() >= 4)
                    {
                        int highestI = pending.back().i;
                        for (int j = static_cast<int>(pending.size()) - 1; j >= 0; j = j - 2)
                        {
                            if (high[pending.at(j).i] > high[highestI])
                            {
                                highestI = j;
                            }
                        }
                        if (highestI == pending.back().i)
                        {
                            Duan d = Duan();
                            d.start = pending.at(0).i;
                            d.end = pending.back().i;
                            d.direction = 1;
                            duan_list.push_back(d);
                            pending.clear();
                            pending.push_back(v);
                            continue;
                        }
                    }
                    else if (pending.size() == 2 && duan_list.size() >= 2)
                    {
                        size_t size = duan_list.size();
                        Duan& last1 = duan_list.at(size - 1);
                        Duan& last2 = duan_list.at(size - 2);
                        bool scenario1 = high[v.i] > high[last1.start] && low[last1.end] < low[last2.start];
                        if (scenario1)
                        {
                            // 特殊情况直接一笔升级成一段
                            Duan d = Duan();
                            d.start = pending.at(0).i;
                            d.end = v.i;
                            d.direction = 1;
                            duan_list.push_back(d);
                            pending.clear();
                            pending.push_back(v);
                            continue;
                        }
                        int count = 0;
                        for (int j = last1.start; j <= last1.end; j++)
                        {
                            if (bi[j] == 1 || bi[j] == -1)
                            {
                                count++;
                            }
                        }
                        bool scenario2 = (count >= 6) && high[v.i] > high[last1.start];
                        if (scenario2)
                        {
                            // 特殊情况直接一笔升级成一段
                            Duan d = Duan();
                            d.start = last1.end;
                            d.end = v.i;
                            d.direction = 1;
                            duan_list.push_back(d);
                            pending.clear();
                            pending.push_back(v);
                            continue;
                        }
                        // 下面是合并到前一段处理
                        if (high[v.i] > high[duan_list.back().start])
                        {
                            duan_list.pop_back();
                            duan_list.back().end = v.i;
                            pending.clear();
                            pending.push_back(v);
                            continue;
                        }
                    }
                }
            }
        }
        else if (v.type == -1)
        {
            if (duan_list.size() == 0)
            {
                Vertex& v1 = vertex_list.at(i - 3);
                Vertex& v2 = vertex_list.at(i - 2);
                Vertex& v3 = vertex_list.at(i - 1);
                Vertex& v4 = vertex_list.at(i);
                if (low[v4.i] < low[v2.i] && high[v3.i] < high[v1.i])
                {
                    Duan d = Duan();
                    d.start = v1.i;
                    d.end = v4.i;
                    d.direction = -1;
                    duan_list.push_back(d);
                    pending.clear();
                    pending.push_back(v);
                    continue;
                }
            }
            else
            {
                Duan& prev1 = duan_list.back();
                if (prev1.direction == -1)
                {
                    if (low[v.i] < low[prev1.end])
                    {
                        prev1.end = v.i;
                        pending.clear();
                        pending.push_back(v);
                        continue;
                    }
                    pending.push_back(v);
                    if (pending.size() >= 7)
                    {
                        bool isDuan = true;
                        for (size_t j = 2; j < pending.size(); j = j + 2)
                        {
                            if (low[pending.back().i] > low[pending.at(j).i])
                            {
                                isDuan = false;
                                break;
                            }
                        }
                        if (isDuan)
                        {
                            Duan d1 = Duan();
                            d1.start = pending.at(0).i;
                            d1.end = pending.at(1).i;
                            d1.direction = 1;
                            duan_list.push_back(d1);
                            Duan d2 = Duan();
                            d2.start = pending.at(1).i;
                            d2.end = pending.back().i;
                            d2.direction = -1;
                            duan_list.push_back(d2);
                            pending.clear();
                            pending.push_back(v);
                            continue;
                        }
                    }
                }
                else
                {
                    pending.push_back(v);
                    if (pending.size() >= 4)
                    {
                        int lowestI = pending.back().i;
                        for (int j = static_cast<int>(pending.size()) - 1; j >= 0; j = j - 2)
                        {
                            if (low[pending.at(j).i] < low[lowestI])
                            {
                                lowestI = j;
                            }
                        }
                        if (lowestI == pending.back().i)
                        {
                            Duan d = Duan();
                            d.start = pending.at(0).i;
                            d.end = pending.back().i;
                            d.direction = -1;
                            duan_list.push_back(d);
                            pending.clear();
                            pending.push_back(v);
                            continue;
                        }
                    }
                    else if (pending.size() == 2 && duan_list.size() >= 2)
                    {
                        size_t size = duan_list.size();
                        Duan& last1 = duan_list.at(size - 1);
                        Duan& last2 = duan_list.at(size - 2);
                        bool scenario1 = low[v.i] < low[last1.start] && high[last1.end] > high[last2.start];
                        if (scenario1)
                        {
                            // 特殊情况直接一笔升级成一段
                            Duan d = Duan();
                            d.start = pending.at(0).i;
                            d.end = v.i;
                            d.direction = -1;
                            duan_list.push_back(d);
                            pending.clear();
                            pending.push_back(v);
                            continue;
                        }
                        int count = 0;
                        for (int j = last1.start; j <= last1.end; j++)
                        {
                            if (bi[j] == 1 || bi[j] == -1)
                            {
                                count++;
                            }
                        }
                        bool scenario2 = (count >= 6) && low[v.i] < low[last1.start];
                        if (scenario2)
                        {
                            // 特殊情况直接一笔升级成一段
                            Duan d = Duan();
                            d.start = last1.end;
                            d.end = v.i;
                            d.direction = -1;
                            duan_list.push_back(d);
                            pending.clear();
                            pending.push_back(v);
                            continue;
                        }
                        if (low[v.i] < low[duan_list.back().start])
                        {
                            duan_list.pop_back();
                            duan_list.back().end = v.i;
                            pending.clear();
                            pending.push_back(v);
                            continue;
                        }
                    }
                }
            }
        }
    }
}

std::vector<Duan> DuanData::get_duan_list()
{
    return duan_list;
}

DuanData::~DuanData()
{
}

PivotData::PivotData(int count, std::vector<float> duan, std::vector<float> bi, std::vector<float> high, std::vector<float> low)
{
    for (int i = 0; i < count; i++)
    {
        if (duan[i] == -1)
        {
            // 在向下线段中计算中枢
            int j = -1;
            for (j = i -1; j >= 0; j--)
            {
                if(duan[j] == 1)
                {
                    break;
                }
            }
            if (j >= 0)
            {
                std::vector<Pivot> down_pivot_list;
                for (int x = j; x <= i; x++)
                {
                    if (bi[x] == -1)
                    {
                        Pivot e;
                        e.start = x;
                        e.zd = low[x];
                        e.dd = low[x];
                        e.direction = -1;
                        e.affirm = false;
                        down_pivot_list.push_back(e);
                    }
                    else if (bi[x] == 1 && down_pivot_list.size() > 0)
                    {
                        down_pivot_list.back().end = x;
                        down_pivot_list.back().zg = high[x];
                        down_pivot_list.back().gg = high[x];
                        if (down_pivot_list.size() > 1)
                        {
                            size_t s = down_pivot_list.size();
                            if (down_pivot_list.at(s - 1).zg >= down_pivot_list.at(s - 2).zd &&
                                down_pivot_list.at(s - 1).zd <= down_pivot_list.at(s - 2).zg)
                            {
                                if (!down_pivot_list.at(s - 2).affirm)
                                {
                                    down_pivot_list.at(s - 2).gg = std::max(down_pivot_list.at(s - 1).gg, down_pivot_list.at(s - 2).gg);
                                    down_pivot_list.at(s - 2).dd = std::min(down_pivot_list.at(s - 1).dd, down_pivot_list.at(s - 2).dd);
                                    down_pivot_list.at(s - 2).zg = std::min(down_pivot_list.at(s - 1).zg, down_pivot_list.at(s - 2).zg);
                                    down_pivot_list.at(s - 2).zd = std::max(down_pivot_list.at(s - 1).zd, down_pivot_list.at(s - 2).zd);
                                    down_pivot_list.at(s - 2).end = down_pivot_list.at(s - 1).end;
                                    down_pivot_list.at(s - 2).affirm = true;
                                }
                                else
                                {
                                    down_pivot_list.at(s - 2).gg = std::max(down_pivot_list.at(s - 1).gg, down_pivot_list.at(s - 2).gg);
                                    down_pivot_list.at(s - 2).dd = std::min(down_pivot_list.at(s - 1).dd, down_pivot_list.at(s - 2).dd);
                                    down_pivot_list.at(s - 2).end = down_pivot_list.at(s - 1).end;
                                }
                                down_pivot_list.pop_back();
                            }
                        }
                    }
                }
                for (size_t x = 0; x < down_pivot_list.size(); x++)
                {
                    if (down_pivot_list.at(x).affirm)
                    {
                        Pivot item = down_pivot_list.at(x);
                        Pivot pivot = Pivot();
                        pivot.affirm = true;
                        pivot.zg = item.zg;
                        pivot.zd = item.zd;
                        pivot.gg = item.gg;
                        pivot.dd = item.dd;
                        pivot.direction = item.direction;
                        pivot.start = item.start;
                        pivot.end = item.end;
                        pivot_list.push_back(pivot);
                    }
                }
            }
        }
        else if (duan[i] == 1)
        {
            // 在向上线段中计算中枢
            int j = -1;
            for (j = i -1; j >= 0; j--)
            {
                if(duan[j] == -1)
                {
                    break;
                }
            }
            if (j >= 0)
            {
                std::vector<Pivot> up_pivot_list;
                for (int x = j; x <= i; x++)
                {
                    if (bi[x] == 1)
                    {
                        Pivot e;
                        e.start = x;
                        e.zg = high[x];
                        e.gg = high[x];
                        e.direction = 1;
                        e.affirm = false;
                        up_pivot_list.push_back(e);
                    }
                    else if (bi[x] == -1 && up_pivot_list.size() > 0)
                    {
                        up_pivot_list.back().end = x;
                        up_pivot_list.back().zd = low[x];
                        up_pivot_list.back().dd = low[x];
                        if (up_pivot_list.size() > 1)
                        {
                            size_t s = up_pivot_list.size();
                            if (up_pivot_list.at(s - 1).zd <= up_pivot_list.at(s - 2).zg &&
                                up_pivot_list.at(s - 1).zg >= up_pivot_list.at(s - 2).zd)
                            {
                                if (!up_pivot_list.at(s - 2).affirm)
                                {
                                    up_pivot_list.at(s - 2).gg = std::max(up_pivot_list.at(s - 1).gg, up_pivot_list.at(s - 2).gg);
                                    up_pivot_list.at(s - 2).dd = std::min(up_pivot_list.at(s - 1).dd, up_pivot_list.at(s - 2).dd);
                                    up_pivot_list.at(s - 2).zg = std::min(up_pivot_list.at(s - 1).zg, up_pivot_list.at(s - 2).zg);
                                    up_pivot_list.at(s - 2).zd = std::max(up_pivot_list.at(s - 1).zd, up_pivot_list.at(s - 2).zd);
                                    up_pivot_list.at(s - 2).end = up_pivot_list.at(s - 1).end;
                                    up_pivot_list.at(s - 2).affirm = true;
                                }
                                else
                                {
                                    up_pivot_list.at(s - 2).gg = std::max(up_pivot_list.at(s - 1).gg, up_pivot_list.at(s - 2).gg);
                                    up_pivot_list.at(s - 2).dd = std::min(up_pivot_list.at(s - 1).dd, up_pivot_list.at(s - 2).dd);
                                    up_pivot_list.at(s - 2).end = up_pivot_list.at(s - 1).end;
                                }
                                up_pivot_list.pop_back();
                            }
                        }
                    }
                }
                for (size_t x = 0; x < up_pivot_list.size(); x++)
                {
                    if (up_pivot_list.at(x).affirm)
                    {
                        Pivot item = up_pivot_list.at(x);
                        Pivot pivot = Pivot();
                        pivot.affirm = true;
                        pivot.zg = item.zg;
                        pivot.zd = item.zd;
                        pivot.gg = item.gg;
                        pivot.dd = item.dd;
                        pivot.direction = item.direction;
                        pivot.start = item.start;
                        pivot.end = item.end;
                        pivot_list.push_back(pivot);
                    }
                }
            }
        }
    }
}

std::vector<Pivot> PivotData::get_pivot_list() {
    return pivot_list;
}

PivotData::~PivotData()
{
}

std::vector<Pivot> recognise_pivots(int count, std::vector<float> duan, std::vector<float> bi, std::vector<float> high, std::vector<float> low) {
    PivotData pivot_data = PivotData(count, duan, bi, high, low);
    return pivot_data.get_pivot_list();
}

std::vector<Bar> recognise_bars(int length, std::vector<float> high, std::vector<float> low)
{
    std::vector<Bar> bars;
    for (int i = 0; i < length; i++)
    {
        Bar bar = Bar();
        bar.i = i;
        bar.high = high[i];
        bar.low = low[i];
        bars.push_back(bar);
    }
    return bars;
}

std::vector<MergedBar> recognise_std_bars(int length, std::vector<float> high, std::vector<float> low)
{
    std::vector<MergedBar> std_bars;
    float direction = 0;
    for (int i = 0; i < length; i++)
    {
        int size = static_cast<int>(std_bars.size());
        if (size > 0)
        {
            int last = size - 1;
            if (high[i] > std_bars.at(last).high && low[i] > std_bars.at(last).low)
            {
                direction = 1;
            }
            else if (high[i] < std_bars.at(last).high && low[i] < std_bars.at(last).low)
            {
                direction = -1;
            }
            else
            {
                direction = std_bars.at(last).direction;
                if (direction == 1)
                {
                    std_bars.at(last).end = i;
                    if (high[i] > std_bars.at(last).high_high)
                    {
                        std_bars.at(last).vertex = i;
                    }
                    std_bars.at(last).high = std::max(std_bars.at(last).high, high[i]);
                    std_bars.at(last).low = std::max(std_bars.at(last).low, low[i]);
                    std_bars.at(last).high_high = std::max(std_bars.at(last).high_high, high[i]);
                    std_bars.at(last).low_low = std::min(std_bars.at(last).low_low, low[i]);
                    continue;
                }
                else if (direction == -1)
                {
                    std_bars.at(last).end = i;
                    if (low[i] < std_bars.at(last).low_low)
                    {
                        std_bars.at(last).vertex = i;
                    }
                    std_bars.at(last).high = std::min(std_bars.at(last).high, high[i]);
                    std_bars.at(last).low = std::min(std_bars.at(last).low, low[i]);
                    std_bars.at(last).high_high = std::max(std_bars.at(last).high_high, high[i]);
                    std_bars.at(last).low_low = std::min(std_bars.at(last).low_low, low[i]);
                    continue;
                }
            }
        }
        MergedBar bar = MergedBar();
        bar.start = i;
        bar.end = i;
        bar.vertex = i;
        bar.high = high[i];
        bar.low = low[i];
        bar.high_high = high[i];
        bar.low_low = low[i];
        bar.direction = direction;
        std_bars.push_back(bar);
    }
    return std_bars;
}

std::vector<float> recognise_swing(int length, std::vector<float> high, std::vector<float> low)
{
    std::vector<MergedBar> std_bars = recognise_std_bars(length, high, low);
    int size = static_cast<int>(std_bars.size());
    std::vector<float> swing(length, 0);
    for (int i = 1; i < size; i++)
    {
        if (std_bars.at(i).direction == 1 && std_bars.at(i - 1).direction == -1)
        {
            swing[std_bars.at(i - 1).vertex] = -1;
        }
        else if (std_bars.at(i).direction == -1 && std_bars.at(i - 1).direction == 1)
        {
            swing[std_bars.at(i - 1).vertex] = 1;
        }
    }
    if (std_bars.at(size - 1).direction == 1)
    {
        swing[std_bars.at(size - 1).vertex] = 1;
    }
    else if (std_bars.at(size - 1).direction == -1)
    {
        swing[std_bars.at(size - 1).vertex] = -1;
    }
    return swing;
}

std::vector<float> recognise_bi(int length, std::vector<float> high, std::vector<float> low)
{
    std::vector<float> out(length, 0);
    BiData biData = BiData(length, high, low);
    std::vector<Bi> biList = biData.get_bi_list();
    for (size_t i = 0; i < biList.size(); i++) {
        Bi& bi = biList.at(i);
        if (bi.direction == 1) {
            out[bi.start] = -1;
            out[bi.end] = 1;
        } else {
            out[bi.start] = 1;
            out[bi.end] = -1;
        }
    }
    return out;
}

std::vector<float> recognise_duan(int length, std::vector<float> bi, std::vector<float> high, std::vector<float> low)
{
    std::vector<float> duan(length, 0);
    DuanData duanData = DuanData(length, bi, high, low);
    std::vector<Duan> duanList = duanData.get_duan_list();
    for (size_t i = 0; i < duanList.size(); i++) {
        Duan& d = duanList.at(i);
        if (d.direction == 1) {
            duan[d.start] = -1;
            duan[d.end] = 1;
        } else {
            duan[d.start] = 1;
            duan[d.end] = -1;
        }
    }
    return duan;
}

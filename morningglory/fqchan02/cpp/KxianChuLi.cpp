#include "KxianChuLi.h"

using namespace std;

void KxianChuLi::add(float gao, float di)
{
    KxianRaw kxianRaw;
    kxianRaw.gao = gao;
    kxianRaw.di = di;
    // 保存原始K线
    this->kxianRawList.push_back(kxianRaw);
    if (this->kxianList.empty())
    {
        // 第一根K线先假设方向为上
        Kxian kxian;
        kxian.gao = gao;
        kxian.di = di;
        kxian.fangXiang = 1;
        kxian.kaiShi = 0;
        kxian.jieShu = 0;
        kxian.zhongJian = 0;
        this->kxianList.push_back(kxian);
    }
    else
    {
        if (gao > this->kxianList.back().gao && di > this->kxianList.back().di)
        {
            // 向上
            Kxian kxian;
            kxian.gao = gao;
            kxian.di = di;
            kxian.fangXiang = 1;
            kxian.kaiShi = this->kxianList.back().jieShu + 1;
            kxian.jieShu = kxian.kaiShi;
            kxian.zhongJian = kxian.kaiShi;
            // 新K线
            this->kxianList.push_back(kxian);
        }
        else if (gao < this->kxianList.back().gao && di < this->kxianList.back().di)
        {
            // 向下
            Kxian kxian;
            kxian.gao = gao;
            kxian.di = di;
            kxian.fangXiang = -1;
            kxian.kaiShi = this->kxianList.back().jieShu + 1;
            kxian.jieShu = kxian.kaiShi;
            kxian.zhongJian = kxian.kaiShi;
            // 新K线
            this->kxianList.push_back(kxian);
        }
        else if (gao <= this->kxianList.back().gao && di >= this->kxianList.back().di)
        {
            // 前包含
            if (this->kxianList.back().fangXiang == 1)
            {
                this->kxianList.back().di = di;
            }
            else
            {
                this->kxianList.back().gao = gao;
            }
            this->kxianList.back().jieShu = this->kxianList.back().jieShu + 1;
        }
        else
        {
            // 后包含
            if (this->kxianList.back().fangXiang == 1)
            {
                this->kxianList.back().gao = gao;
            }
            else
            {
                this->kxianList.back().di = di;
            }
            this->kxianList.back().jieShu = this->kxianList.back().jieShu + 1;
            this->kxianList.back().zhongJian = this->kxianList.back().jieShu;
        }
    }
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

vector<StdBar> recognise_std_bars(int length, vector<float> high, vector<float> low)
{
    vector<StdBar> std_bars;
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
                    std_bars.at(last).high = max(std_bars.at(last).high, high[i]);
                    std_bars.at(last).low = max(std_bars.at(last).low, low[i]);
                    std_bars.at(last).high_high = max(std_bars.at(last).high_high, high[i]);
                    std_bars.at(last).low_low = min(std_bars.at(last).low_low, low[i]);
                    continue;
                }
                else if (direction == -1)
                {
                    std_bars.at(last).end = i;
                    if (low[i] < std_bars.at(last).low_low)
                    {
                        std_bars.at(last).vertex = i;
                    }
                    std_bars.at(last).high = min(std_bars.at(last).high, high[i]);
                    std_bars.at(last).low = min(std_bars.at(last).low, low[i]);
                    std_bars.at(last).high_high = max(std_bars.at(last).high_high, high[i]);
                    std_bars.at(last).low_low = min(std_bars.at(last).low_low, low[i]);
                    continue;
                }
            }
        }
        StdBar bar = StdBar();
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

#include "Chan.h"
#include "Log.h"

thread_local ChanProxy *ChanProxy::instance = NULL;

ChanProxy::ChanProxy()
{
    chan = new Chan();
}

ChanProxy::~ChanProxy()
{
    if (chan)
    {
        delete chan;
        chan = NULL;
    }
    if (instance)
    {
        delete instance;
        instance = NULL;
    }
}

ChanProxy &ChanProxy::GetInstance()
{
    if (!instance)
    {
        instance = new ChanProxy();
    }
    return *instance;
}

void ChanProxy::SetHighs(std::vector<float> &highs)
{
    this->chan->SetHighs(highs);
}

std::vector<float> &ChanProxy::GetHighs()
{
    return this->chan->GetHighs();
}

void ChanProxy::SetLows(std::vector<float> &lows)
{
    this->chan->SetLows(lows);
}

std::vector<float> &ChanProxy::GetLows()
{
    return this->chan->GetLows();
}

void ChanProxy::SetOpens(std::vector<float> &opens)
{
    this->chan->SetOpens(opens);
}

std::vector<float> &ChanProxy::GetOpens()
{
    return this->chan->GetOpens();
}

void ChanProxy::SetCloses(std::vector<float> &closes)
{
    this->chan->SetCloses(closes);
}

std::vector<float> &ChanProxy::GetCloses()
{
    return this->chan->GetCloses();
}

void ChanProxy::SetVolumes(std::vector<float> &volumes)
{
    this->chan->SetVolumes(volumes);
}

std::vector<float> &ChanProxy::GetVolumes()
{
    return this->chan->GetVolumes();
}

void ChanProxy::Append(float high, float low, float open, float close, float volume)
{
    this->chan->Append(high, low, open, close, volume);
}

size_t ChanProxy::Proceed()
{
    return this->chan->Proceed();
}

std::vector<Bar> &ChanProxy::GetBars()
{
    return this->chan->GetBars();
}

std::vector<Swing> &ChanProxy::GetSwings()
{
    return this->chan->GetSwings();
}

std::vector<Wave> &ChanProxy::GetWaves()
{
    return this->chan->GetWaves();
}

std::vector<Stretch> &ChanProxy::GetStretches()
{
    return this->chan->GetStretches();
}

std::vector<Trend> &ChanProxy::GetTrends()
{
    return this->chan->GetTrends();
}

void ChanProxy::Reset()
{
    this->chan->Reset();
}

Chan::Chan()
{
}

Chan::~Chan()
{
}

void Chan::Append(float high, float low, float open, float close, float volume)
{
    this->highs.push_back(high);
    this->lows.push_back(low);
    this->opens.push_back(open);
    this->closes.push_back(close);
    this->volumes.push_back(volume);
}

size_t Chan::Proceed()
{
    // 合成一个Bar
    size_t i = this->bars.size();
    if (i >= this->highs.size() || i >= this->lows.size() || i >= this->opens.size() || i >= this->closes.size() || i >= this->volumes.size())
    {
        return bars.size();
    }
    Bar bar;
    bar.i = static_cast<long>(i);
    bar.No = bar.i + 1;
    bar.high = this->highs[i];
    bar.low = this->lows[i];
    this->OnBar(bar);
    return bars.size();
}

void Chan::OnBar(Bar &bar)
{
    this->bars.push_back(bar);
    if (this->waves.size() == 0)
    {
        if (this->ripple.mergedBars.size() == 0)
        {
            // 第一根Bar的时候
            this->OnBarWhenFirst(bar);
        }
        else
        {
            // 有了Bar但是还没有方向确定的时候
            this->OnBarWhenUnknownDirection(bar);
        }
    }
    else
    {
        // 有了初步运行方向的时候
        this->OnBarWhenKnownDirection(bar);
    }
}

void Chan::OnBarWhenFirst(Bar &bar)
{
    // 清一下ripple的状态
    this->ripple.direction = DirectionType::UNKNOWN;
    this->ripple.mergedBars.clear();

    // 第一根合并Bar
    MergedBar mergedBar;
    mergedBar.No = 1;
    mergedBar.peekPos = bar.i;
    mergedBar.valleyPos = bar.i;
    mergedBar.direction = DirectionType::UNKNOWN;
    mergedBar.start = bar.i;
    mergedBar.end = bar.i;
    mergedBar.high = bar.high;
    mergedBar.low = bar.low;
    mergedBar.top = bar.high;
    mergedBar.bottom = bar.low;

    this->ripple.mergedBars.push_back(mergedBar);
}

void Chan::OnBarWhenUnknownDirection(Bar &bar)
{
    // 已经有Bar了，但是Bar的运行方向还没有确定
    // 起笔宽松处理，只要Bar运行出方向了，就作为第一笔有了
    Wave &ripple = this->ripple;
    MergedBar &lastMergedBar = ripple.mergedBars.back();
    if (bar.high > lastMergedBar.high && bar.low > lastMergedBar.low) // 向上运行方向
    {
        lastMergedBar.direction = DirectionType::DOWN;

        MergedBar mergedBar;
        mergedBar.No = lastMergedBar.No + 1;
        mergedBar.peekPos = bar.i;
        mergedBar.valleyPos = bar.i;
        mergedBar.direction = DirectionType::UP;
        mergedBar.start = bar.i;
        mergedBar.end = bar.i;
        mergedBar.high = bar.high;
        mergedBar.low = bar.low;
        mergedBar.top = bar.high;
        mergedBar.bottom = bar.low;
        ripple.mergedBars.push_back(mergedBar);

        KeyBar startKb;
        startKb.type = ExtremePointType::VALLEY;
        startKb.pos = lastMergedBar.valleyPos;
        startKb.high = this->bars[startKb.pos].high;
        startKb.low = this->bars[startKb.pos].low;
        // 计算颈线
        startKb.neck = startKb.high;
        for (int i = startKb.pos - 1; i >= 0; i--)
        {
            Bar &b = this->bars.at(i);
            if (b.low < startKb.low)
            {
                break;
            }
            if (b.high > startKb.high && b.low > startKb.low)
            {
                startKb.neck = b.high;
                break;
            }
            else
            {
                startKb.high = std::min(b.high, startKb.high);
            }
        }

        KeyBar endKb;
        endKb.type = ExtremePointType::PEAK;
        endKb.pos = mergedBar.peekPos;
        endKb.high = this->bars[endKb.pos].high;
        endKb.low = this->bars[endKb.pos].low;
        // 计算颈线
        endKb.neck = endKb.low;
        for (int i = endKb.pos - 1; i > startKb.pos; i--)
        {
            Bar &b = this->bars.at(i);
            if (b.high > endKb.high)
            {
                break;
            }
            if (b.high < endKb.high && b.low < endKb.low)
            {
                endKb.neck = b.low;
                break;
            }
            else
            {
                endKb.low = std::max(b.low, endKb.low);
            }
        }

        ripple.direction = DirectionType::UP;
        ripple.startKeyBar = startKb; // 笔的起始关键Bar
        ripple.endKeyBar = endKb;     // 笔的结束关键Bar
        ripple.No = 1;
        this->waves.push_back(ripple); // 产生了第一笔

        // 和笔相反的波动是下一个ripple
        Wave nRipple;
        nRipple.direction = DirectionType::DOWN;
        nRipple.startKeyBar = endKb;
        MergedBar nMergedBar;
        nMergedBar.direction = DirectionType::UP;
        nMergedBar.start = bar.i;
        nMergedBar.end = bar.i;
        nMergedBar.high = bar.high;
        nMergedBar.low = bar.low;
        nMergedBar.top = bar.high;
        nMergedBar.bottom = bar.low;
        nMergedBar.peekPos = bar.i;
        nMergedBar.valleyPos = bar.i;
        nMergedBar.No = 1;
        for (int i = bar.i - 1; i > ripple.startKeyBar.pos; i--)
        {
            Bar &b = this->bars.at(i);
            if (b.high < nMergedBar.high && b.low < nMergedBar.low)
            {
                break;
            }
            else
            {
                nMergedBar.low = std::max(b.low, nMergedBar.low);
                nMergedBar.start = i;
                if (b.low < nMergedBar.bottom)
                {
                    nMergedBar.bottom = b.low;
                    nMergedBar.valleyPos = b.i;
                }
                if (b.high > nMergedBar.top)
                {
                    nMergedBar.top = b.high;
                    nMergedBar.peekPos = b.i;
                }
            }
        }
        nRipple.mergedBars.push_back(nMergedBar);
        this->ripple = nRipple;
    }
    else if (bar.high < lastMergedBar.high && bar.low < lastMergedBar.low) // 向下运行方向
    {
        lastMergedBar.direction = DirectionType::UP;

        MergedBar mergedBar;
        mergedBar.No = lastMergedBar.No + 1;
        mergedBar.peekPos = bar.i;
        mergedBar.valleyPos = bar.i;
        mergedBar.direction = DirectionType::DOWN;
        mergedBar.start = bar.i;
        mergedBar.end = bar.i;
        mergedBar.high = bar.high;
        mergedBar.low = bar.low;
        mergedBar.top = bar.high;
        mergedBar.bottom = bar.low;
        ripple.mergedBars.push_back(mergedBar);

        KeyBar startKb;
        startKb.type = ExtremePointType::PEAK;
        startKb.pos = lastMergedBar.peekPos;
        startKb.high = this->bars[startKb.pos].high;
        startKb.low = this->bars[startKb.pos].low;
        // 计算颈线
        startKb.neck = startKb.low;
        for (int i = startKb.pos - 1; i >= 0; i--)
        {
            Bar &b = this->bars.at(i);
            if (b.high > startKb.high)
            {
                break;
            }
            if (b.high < startKb.high && b.low < startKb.low)
            {
                startKb.neck = b.low;
                break;
            }
            else
            {
                startKb.low = std::max(b.low, startKb.low);
            }
        }

        KeyBar endKb;
        endKb.type = ExtremePointType::VALLEY;
        endKb.pos = mergedBar.valleyPos;
        endKb.high = this->bars[endKb.pos].high;
        endKb.low = this->bars[endKb.pos].low;
        // 计算颈线
        endKb.neck = endKb.high;
        for (int i = endKb.pos - 1; i > startKb.pos; i--)
        {
            Bar &b = this->bars.at(i);
            if (b.low < endKb.low)
            {
                break;
            }
            if (b.high > endKb.high && b.low > endKb.low)
            {
                endKb.neck = b.high;
                break;
            }
            else
            {
                endKb.high = std::min(b.high, endKb.high);
            }
        }

        ripple.direction = DirectionType::DOWN;
        ripple.startKeyBar = startKb; // 笔的起始关键Bar
        ripple.endKeyBar = endKb;     // 笔的结束关键Bar
        ripple.No = 1;
        this->waves.push_back(ripple); // 产生了第一笔

        // 和笔相反的波动是下一个ripple
        Wave nRipple;
        nRipple.direction = DirectionType::UP;
        nRipple.startKeyBar = endKb;
        MergedBar nMergedBar;
        nMergedBar.direction = DirectionType::DOWN;
        nMergedBar.start = bar.i;
        nMergedBar.end = bar.i;
        nMergedBar.high = bar.high;
        nMergedBar.low = bar.low;
        nMergedBar.top = bar.high;
        nMergedBar.bottom = bar.low;
        nMergedBar.peekPos = bar.i;
        nMergedBar.valleyPos = bar.i;
        nMergedBar.No = 1;
        for (int i = bar.i - 1; i > ripple.startKeyBar.pos; i--)
        {
            Bar &b = this->bars.at(i);
            if (b.high > nMergedBar.high && b.low > nMergedBar.low)
            {
                break;
            }
            else
            {
                nMergedBar.high = std::min(b.high, nMergedBar.high);
                nMergedBar.start = i;
                if (b.low < nMergedBar.bottom)
                {
                    nMergedBar.bottom = b.low;
                    nMergedBar.valleyPos = b.i;
                }
                if (b.high > nMergedBar.top)
                {
                    nMergedBar.top = b.high;
                    nMergedBar.peekPos = b.i;
                }
            }
        }
        nRipple.mergedBars.push_back(nMergedBar);
        this->ripple = nRipple;
    }
    else
    {
        // 忽略前面的Bar继续找方向
        this->OnBarWhenFirst(bar);
    }
}

void Chan::OnBarWhenKnownDirection(Bar &bar)
{
    Wave &wave = this->waves.back();
    Wave &ripple = this->ripple;
    if (wave.direction == DirectionType::UP) // 最后笔是向上的
    {
        MergedBar &lastMergedBar = wave.mergedBars.back();
        if (bar.high > lastMergedBar.high && bar.low > lastMergedBar.low) // 向上Bar
        {
            MergedBar mergedBar;
            mergedBar.No = lastMergedBar.No + 1;
            mergedBar.peekPos = bar.i;
            mergedBar.valleyPos = bar.i;
            mergedBar.direction = DirectionType::UP;
            mergedBar.start = bar.i;
            mergedBar.end = bar.i;
            mergedBar.high = bar.high;
            mergedBar.low = bar.low;
            mergedBar.top = bar.high;
            mergedBar.bottom = bar.low;
            wave.mergedBars.push_back(mergedBar);
        }
        else if (bar.high < lastMergedBar.high && bar.low < lastMergedBar.low) // 向下Bar
        {
            MergedBar mergedBar;
            mergedBar.No = lastMergedBar.No + 1;
            mergedBar.peekPos = bar.i;
            mergedBar.valleyPos = bar.i;
            mergedBar.direction = DirectionType::DOWN;
            mergedBar.start = bar.i;
            mergedBar.end = bar.i;
            mergedBar.high = bar.high;
            mergedBar.low = bar.low;
            mergedBar.top = bar.high;
            mergedBar.bottom = bar.low;
            wave.mergedBars.push_back(mergedBar);
        }
        else // 包含Bar
        {
            if (lastMergedBar.direction == DirectionType::UP) // 向上包含
            {
                // 向上包含处理
                lastMergedBar.high = std::max(lastMergedBar.high, bar.high);
                lastMergedBar.low = std::max(lastMergedBar.low, bar.low);
                lastMergedBar.end = bar.i;
                if (bar.high > lastMergedBar.top)
                {
                    lastMergedBar.top = bar.high;
                    lastMergedBar.peekPos = bar.i;
                }
                if (bar.low < lastMergedBar.bottom)
                {
                    lastMergedBar.bottom = bar.low;
                    lastMergedBar.valleyPos = bar.i;
                }
            }
            else if (lastMergedBar.direction == DirectionType::DOWN) // 向下包含
            {
                // 向下包含处理
                lastMergedBar.high = std::min(lastMergedBar.high, bar.high);
                lastMergedBar.low = std::min(lastMergedBar.low, bar.low);
                lastMergedBar.end = bar.i;
                if (bar.high > lastMergedBar.top)
                {
                    lastMergedBar.top = bar.high;
                    lastMergedBar.peekPos = bar.i;
                }
                if (bar.low < lastMergedBar.bottom)
                {
                    lastMergedBar.bottom = bar.low;
                    lastMergedBar.valleyPos = bar.i;
                }
            }
        }
        if (bar.high > wave.endKeyBar.high) // 突破创了新高
        {
            // 向上笔要延伸到新的高点
            KeyBar endKb;
            endKb.type = ExtremePointType::PEAK;
            endKb.high = bar.high;
            endKb.low = bar.low;
            endKb.pos = bar.i;
            endKb.neck = bar.low;
            for (int i = endKb.pos - 1; i > wave.startKeyBar.pos; i--)
            {
                Bar &b = this->bars.at(i);
                if (b.high < endKb.high && b.low < endKb.low)
                {
                    endKb.neck = b.low;
                    break;
                }
                else
                {
                    endKb.low = std::max(endKb.low, b.low);
                }
            }
            wave.endKeyBar = endKb;

            Wave nRipple;
            nRipple.direction = DirectionType::DOWN;
            nRipple.startKeyBar = endKb;
            MergedBar nMergedBar;
            nMergedBar.direction = DirectionType::UP;
            nMergedBar.start = bar.i;
            nMergedBar.end = bar.i;
            nMergedBar.high = bar.high;
            nMergedBar.low = bar.low;
            nMergedBar.top = bar.high;
            nMergedBar.bottom = bar.low;
            nMergedBar.peekPos = bar.i;
            nMergedBar.valleyPos = bar.i;
            nMergedBar.No = 1;
            for (int i = bar.i - 1; i > wave.startKeyBar.pos; i--)
            {
                Bar &b = this->bars.at(i);
                if (b.high < nMergedBar.high && b.low < nMergedBar.low)
                {
                    break;
                }
                else
                {
                    nMergedBar.low = std::max(b.low, nMergedBar.low);
                    nMergedBar.start = i;
                    if (b.low < nMergedBar.bottom)
                    {
                        nMergedBar.bottom = b.low;
                        nMergedBar.valleyPos = b.i;
                    }
                    if (b.high > nMergedBar.top)
                    {
                        nMergedBar.top = b.high;
                        nMergedBar.peekPos = b.i;
                    }
                }
            }
            nRipple.mergedBars.push_back(nMergedBar);
            this->ripple = nRipple;
        }
        else // 没有新高，要查看有反向的笔产生吗
        {
            MergedBar &lastMergedBar = ripple.mergedBars.back();
            // 判断是否有新的笔产生
            if (bar.high > lastMergedBar.high && bar.low > lastMergedBar.low)
            {
                MergedBar mergedBar;
                mergedBar.No = lastMergedBar.No + 1;
                mergedBar.peekPos = bar.i;
                mergedBar.valleyPos = bar.i;
                mergedBar.direction = DirectionType::UP;
                mergedBar.start = bar.i;
                mergedBar.end = bar.i;
                mergedBar.high = bar.high;
                mergedBar.low = bar.low;
                mergedBar.top = bar.high;
                mergedBar.bottom = bar.low;
                ripple.mergedBars.push_back(mergedBar);
            }
            else if (bar.high < lastMergedBar.high && bar.low < lastMergedBar.low)
            {
                MergedBar mergedBar;
                mergedBar.No = lastMergedBar.No + 1;
                mergedBar.peekPos = bar.i;
                mergedBar.valleyPos = bar.i;
                mergedBar.direction = DirectionType::DOWN;
                mergedBar.start = bar.i;
                mergedBar.end = bar.i;
                mergedBar.high = bar.high;
                mergedBar.low = bar.low;
                mergedBar.top = bar.high;
                mergedBar.bottom = bar.low;
                ripple.mergedBars.push_back(mergedBar);
            }
            else
            {
                if (lastMergedBar.direction == DirectionType::UP)
                {
                    // 向上包含处理
                    lastMergedBar.high = std::max(lastMergedBar.high, bar.high);
                    lastMergedBar.low = std::max(lastMergedBar.low, bar.low);
                    lastMergedBar.end = bar.i;
                    if (bar.high > lastMergedBar.top)
                    {
                        lastMergedBar.top = bar.high;
                        lastMergedBar.peekPos = bar.i;
                    }
                    if (bar.low < lastMergedBar.bottom)
                    {
                        lastMergedBar.bottom = bar.low;
                        lastMergedBar.valleyPos = bar.i;
                    }
                }
                else if (lastMergedBar.direction == DirectionType::DOWN)
                {
                    // 向下包含处理
                    lastMergedBar.high = std::min(lastMergedBar.high, bar.high);
                    lastMergedBar.low = std::min(lastMergedBar.low, bar.low);
                    lastMergedBar.end = bar.i;
                    if (bar.high > lastMergedBar.top)
                    {
                        lastMergedBar.top = bar.high;
                        lastMergedBar.peekPos = bar.i;
                    }
                    if (bar.low < lastMergedBar.bottom)
                    {
                        lastMergedBar.bottom = bar.low;
                        lastMergedBar.valleyPos = bar.i;
                    }
                }
            }
            if (ripple.mergedBars.size() == 2)
            {
                KeyBar endKb;
                endKb.type = ExtremePointType::VALLEY;
                endKb.pos = bar.i;
                endKb.high = bar.high;
                endKb.low = bar.low;
                endKb.neck = bar.high;
                for (int i = endKb.pos - 1; i > ripple.startKeyBar.pos; i--)
                {
                    Bar &b = this->bars.at(i);
                    if (b.high > endKb.high && b.low > endKb.low)
                    {
                        endKb.neck = b.high;
                        break;
                    }
                    else
                    {
                        endKb.high = std::min(b.high, endKb.high);
                    }
                }
                ripple.endKeyBar = endKb;
            }
            else if (ripple.mergedBars.size() > 2)
            {
                if (bar.low < ripple.endKeyBar.low)
                {
                    KeyBar endKb;
                    endKb.type = ExtremePointType::VALLEY;
                    endKb.pos = bar.i;
                    endKb.high = bar.high;
                    endKb.low = bar.low;
                    endKb.neck = bar.high;
                    for (int i = endKb.pos - 1; i > ripple.startKeyBar.pos; i--)
                    {
                        Bar &b = this->bars.at(i);
                        if (b.high > endKb.high && b.low > endKb.low)
                        {
                            endKb.neck = b.high;
                            break;
                        }
                        else
                        {
                            endKb.high = std::min(b.high, endKb.high);
                        }
                    }
                    ripple.endKeyBar = endKb;
                }
            }
            if (ripple.endKeyBar.pos > 0)
            {
                if ((ripple.mergedBars.size() >= 5 && bar.low < ripple.startKeyBar.neck && bar.low <= ripple.endKeyBar.low) || bar.low < this->waves.back().startKeyBar.low)
                {
                    // 成立新的笔
                    ripple.No = this->waves.back().No + 1;
                    this->waves.push_back(ripple);

                    Wave nRipple;
                    nRipple.direction = DirectionType::UP;
                    KeyBar startKb;
                    startKb.pos = bar.i;
                    startKb.high = bar.high;
                    startKb.low = bar.low;
                    startKb.type = ExtremePointType::VALLEY;
                    startKb.neck = bar.high;
                    for (int i = startKb.pos - 1; i > ripple.startKeyBar.pos; i--)
                    {
                        Bar &b = this->bars.at(i);
                        if (b.high > startKb.high && b.low > startKb.low)
                        {
                            startKb.neck = b.high;
                            break;
                        }
                        else
                        {
                            startKb.high = std::min(b.high, startKb.high);
                        }
                    }
                    nRipple.startKeyBar = startKb;
                    MergedBar nMergedBar;
                    nMergedBar.direction = DirectionType::DOWN;
                    nMergedBar.start = bar.i;
                    nMergedBar.end = bar.i;
                    nMergedBar.high = bar.high;
                    nMergedBar.low = bar.low;
                    nMergedBar.top = bar.high;
                    nMergedBar.bottom = bar.low;
                    nMergedBar.peekPos = bar.i;
                    nMergedBar.valleyPos = bar.i;
                    nMergedBar.No = 1;
                    for (int i = bar.i - 1; i > ripple.startKeyBar.pos; i--)
                    {
                        Bar &b = this->bars.at(i);
                        if (b.high < nMergedBar.high && b.low < nMergedBar.low)
                        {
                            break;
                        }
                        else
                        {
                            nMergedBar.low = std::max(b.low, nMergedBar.low);
                            nMergedBar.start = i;
                            if (b.low < nMergedBar.bottom)
                            {
                                nMergedBar.bottom = b.low;
                                nMergedBar.valleyPos = b.i;
                            }
                            if (b.high > nMergedBar.top)
                            {
                                nMergedBar.top = b.high;
                                nMergedBar.peekPos = b.i;
                            }
                        }
                    }
                    nRipple.mergedBars.push_back(nMergedBar);
                    this->ripple = nRipple;
                }
            }
        }
    }
    else if (wave.direction == DirectionType::DOWN) // 最后笔是向下的
    {
        MergedBar &lastMergedBar = wave.mergedBars.back();
        if (bar.high > lastMergedBar.high && bar.low > lastMergedBar.low) // 向上Bar
        {
            MergedBar mergedBar;
            mergedBar.No = lastMergedBar.No + 1;
            mergedBar.peekPos = bar.i;
            mergedBar.valleyPos = bar.i;
            mergedBar.direction = DirectionType::UP;
            mergedBar.start = bar.i;
            mergedBar.end = bar.i;
            mergedBar.high = bar.high;
            mergedBar.low = bar.low;
            mergedBar.top = bar.high;
            mergedBar.bottom = bar.low;
            wave.mergedBars.push_back(mergedBar);
        }
        else if (bar.high < lastMergedBar.high && bar.low < lastMergedBar.low) // 向下Bar
        {
            MergedBar mergedBar;
            mergedBar.No = lastMergedBar.No + 1;
            mergedBar.peekPos = bar.i;
            mergedBar.valleyPos = bar.i;
            mergedBar.direction = DirectionType::DOWN;
            mergedBar.start = bar.i;
            mergedBar.end = bar.i;
            mergedBar.high = bar.high;
            mergedBar.low = bar.low;
            mergedBar.top = bar.high;
            mergedBar.bottom = bar.low;
            wave.mergedBars.push_back(mergedBar);
        }
        else // 包含Bar
        {
            if (lastMergedBar.direction == DirectionType::UP) // 向上包含
            {
                lastMergedBar.high = std::max(lastMergedBar.high, bar.high);
                lastMergedBar.low = std::max(lastMergedBar.low, bar.low);
                lastMergedBar.end = bar.i;
                if (bar.high > lastMergedBar.top)
                {
                    lastMergedBar.top = bar.high;
                    lastMergedBar.peekPos = bar.i;
                }
                if (bar.low < lastMergedBar.bottom)
                {
                    lastMergedBar.bottom = bar.low;
                    lastMergedBar.valleyPos = bar.i;
                }
            }
            else if (lastMergedBar.direction == DirectionType::DOWN) // 向下包含
            {
                lastMergedBar.high = std::min(lastMergedBar.high, bar.high);
                lastMergedBar.low = std::min(lastMergedBar.low, bar.low);
                lastMergedBar.end = bar.i;
                if (bar.high > lastMergedBar.top)
                {
                    lastMergedBar.top = bar.high;
                    lastMergedBar.peekPos = bar.i;
                }
                if (bar.low < lastMergedBar.bottom)
                {
                    lastMergedBar.bottom = bar.low;
                    lastMergedBar.valleyPos = bar.i;
                }
            }
        }
        if (bar.low < wave.endKeyBar.low) // 跌破创了新低
        {
            KeyBar endKb;
            endKb.type = ExtremePointType::VALLEY;
            endKb.high = bar.high;
            endKb.low = bar.low;
            endKb.pos = bar.i;
            endKb.neck = bar.high;
            for (int i = endKb.pos - 1; i > wave.startKeyBar.pos; i--)
            {
                Bar &b = this->bars.at(i);
                if (b.high > endKb.high && b.low > endKb.low)
                {
                    endKb.neck = b.high;
                    break;
                }
                else
                {
                    endKb.high = std::min(endKb.high, b.high);
                }
            }
            wave.endKeyBar = endKb;

            Wave nRipple;
            nRipple.direction = DirectionType::UP;
            nRipple.startKeyBar = endKb;
            MergedBar nMergedBar;
            nMergedBar.direction = DirectionType::DOWN;
            nMergedBar.start = bar.i;
            nMergedBar.end = bar.i;
            nMergedBar.high = bar.high;
            nMergedBar.low = bar.low;
            nMergedBar.top = bar.high;
            nMergedBar.bottom = bar.low;
            nMergedBar.peekPos = bar.i;
            nMergedBar.valleyPos = bar.i;
            nMergedBar.No = 1;
            for (int i = bar.i - 1; i > wave.startKeyBar.pos; i--)
            {
                Bar &b = this->bars.at(i);
                if (b.high > nMergedBar.high && b.low > nMergedBar.low)
                {
                    break;
                }
                else
                {
                    nMergedBar.high = std::min(b.high, nMergedBar.high);
                    nMergedBar.start = i;
                    if (b.low < nMergedBar.bottom)
                    {
                        nMergedBar.bottom = b.low;
                        nMergedBar.valleyPos = b.i;
                    }
                    if (b.high > nMergedBar.top)
                    {
                        nMergedBar.top = b.high;
                        nMergedBar.peekPos = b.i;
                    }
                }
            }
            nRipple.mergedBars.push_back(nMergedBar);
            this->ripple = nRipple;
        }
        else // 没有新低，要查看有反向的笔产生吗
        {
            MergedBar &lastMergedBar = ripple.mergedBars.back();
            // 向下笔的过程
            if (bar.high > lastMergedBar.high && bar.low > lastMergedBar.low)
            {
                MergedBar mergedBar;
                mergedBar.No = lastMergedBar.No + 1;
                mergedBar.peekPos = bar.i;
                mergedBar.valleyPos = bar.i;
                mergedBar.direction = DirectionType::UP;
                mergedBar.start = bar.i;
                mergedBar.end = bar.i;
                mergedBar.high = bar.high;
                mergedBar.low = bar.low;
                mergedBar.top = bar.high;
                mergedBar.bottom = bar.low;
                ripple.mergedBars.push_back(mergedBar);
            }
            else if (bar.high < lastMergedBar.high && bar.low < lastMergedBar.low)
            {
                MergedBar mergedBar;
                mergedBar.No = lastMergedBar.No + 1;
                mergedBar.peekPos = bar.i;
                mergedBar.valleyPos = bar.i;
                mergedBar.direction = DirectionType::DOWN;
                mergedBar.start = bar.i;
                mergedBar.end = bar.i;
                mergedBar.high = bar.high;
                mergedBar.low = bar.low;
                mergedBar.top = bar.high;
                mergedBar.bottom = bar.low;
                ripple.mergedBars.push_back(mergedBar);
            }
            else
            {
                if (lastMergedBar.direction == DirectionType::UP)
                {
                    // 向上包含处理
                    lastMergedBar.high = std::max(lastMergedBar.high, bar.high);
                    lastMergedBar.low = std::max(lastMergedBar.low, bar.low);
                    lastMergedBar.end = bar.i;
                    if (bar.high > lastMergedBar.top)
                    {
                        lastMergedBar.top = bar.high;
                        lastMergedBar.peekPos = bar.i;
                    }
                    if (bar.low < lastMergedBar.bottom)
                    {
                        lastMergedBar.bottom = bar.low;
                        lastMergedBar.valleyPos = bar.i;
                    }
                }
                else if (lastMergedBar.direction == DirectionType::DOWN)
                {
                    // 向下包含处理
                    lastMergedBar.high = std::min(lastMergedBar.high, bar.high);
                    lastMergedBar.low = std::min(lastMergedBar.low, bar.low);
                    lastMergedBar.end = bar.i;
                    if (bar.high > lastMergedBar.top)
                    {
                        lastMergedBar.top = bar.high;
                        lastMergedBar.peekPos = bar.i;
                    }
                    if (bar.low < lastMergedBar.bottom)
                    {
                        lastMergedBar.bottom = bar.low;
                        lastMergedBar.valleyPos = bar.i;
                    }
                }
            }
            if (ripple.mergedBars.size() == 2)
            {
                KeyBar endKb;
                endKb.type = ExtremePointType::PEAK;
                endKb.pos = bar.i;
                endKb.high = bar.high;
                endKb.low = bar.low;
                endKb.neck = bar.low;
                for (int i = endKb.pos - 1; i > ripple.startKeyBar.pos; i--)
                {
                    Bar &b = this->bars.at(i);
                    if (b.high < endKb.high && b.low < endKb.low)
                    {
                        endKb.neck = b.low;
                        break;
                    }
                    else
                    {
                        endKb.low = std::max(b.low, endKb.low);
                    }
                }
                ripple.endKeyBar = endKb;
            }
            else if (ripple.mergedBars.size() > 2)
            {
                if (bar.high > ripple.endKeyBar.high)
                {
                    KeyBar endKb;
                    endKb.type = ExtremePointType::PEAK;
                    endKb.pos = bar.i;
                    endKb.high = bar.high;
                    endKb.low = bar.low;
                    endKb.neck = bar.low;
                    for (int i = endKb.pos - 1; i > ripple.startKeyBar.pos; i--)
                    {
                        Bar &b = this->bars.at(i);
                        if (b.high < endKb.high && b.low < endKb.low)
                        {
                            endKb.neck = b.low;
                            break;
                        }
                        else
                        {
                            endKb.low = std::max(b.low, endKb.low);
                        }
                    }
                    ripple.endKeyBar = endKb;
                }
            }
            if ((ripple.mergedBars.size() >= 5 && bar.high > ripple.startKeyBar.neck && bar.high >= ripple.endKeyBar.high) || bar.high > this->waves.back().startKeyBar.high)
            {
                // 成立新的笔
                ripple.No = this->waves.back().No + 1;
                this->waves.push_back(ripple);

                Wave nRipple;
                nRipple.direction = DirectionType::DOWN;
                KeyBar startKb;
                startKb.pos = bar.i;
                startKb.high = bar.high;
                startKb.low = bar.low;
                startKb.type = ExtremePointType::PEAK;
                startKb.neck = bar.high;
                for (int i = startKb.pos - 1; i > ripple.startKeyBar.pos; i--)
                {
                    Bar &b = this->bars.at(i);
                    if (b.high < startKb.high && b.low < startKb.low)
                    {
                        startKb.neck = b.low;
                        break;
                    }
                    else
                    {
                        startKb.low = std::max(b.low, startKb.low);
                    }
                }
                nRipple.startKeyBar = startKb;
                MergedBar nMergedBar;
                nMergedBar.direction = DirectionType::UP;
                nMergedBar.start = bar.i;
                nMergedBar.end = bar.i;
                nMergedBar.high = bar.high;
                nMergedBar.low = bar.low;
                nMergedBar.top = bar.high;
                nMergedBar.bottom = bar.low;
                nMergedBar.peekPos = bar.i;
                nMergedBar.valleyPos = bar.i;
                nMergedBar.No = 1;
                for (int i = bar.i - 1; i > ripple.startKeyBar.pos; i--)
                {
                    Bar &b = this->bars.at(i);
                    if (b.high < nMergedBar.high && b.low < nMergedBar.low)
                    {
                        break;
                    }
                    else
                    {
                        nMergedBar.low = std::max(b.low, nMergedBar.low);
                        nMergedBar.start = i;
                        if (b.low < nMergedBar.bottom)
                        {
                            nMergedBar.bottom = b.low;
                            nMergedBar.valleyPos = b.i;
                        }
                        if (b.high > nMergedBar.top)
                        {
                            nMergedBar.top = b.high;
                            nMergedBar.peekPos = b.i;
                        }
                    }
                }
                nRipple.mergedBars.push_back(nMergedBar);
                this->ripple = nRipple;
            }
        }
    }
}

void Chan::SetHighs(std::vector<float> &highs)
{
    this->highs = highs;
}

std::vector<float> &Chan::GetHighs()
{
    return this->highs;
}

void Chan::SetLows(std::vector<float> &lows)
{
    this->lows = lows;
}

std::vector<float> &Chan::GetLows()
{
    return this->lows;
}

void Chan::SetOpens(std::vector<float> &opens)
{
    this->opens = opens;
}

std::vector<float> &Chan::GetOpens()
{
    return this->opens;
}

void Chan::SetCloses(std::vector<float> &closes)
{
    this->closes = closes;
}

std::vector<float> &Chan::GetCloses()
{
    return this->closes;
}

void Chan::SetVolumes(std::vector<float> &volumes)
{
    this->volumes = volumes;
}

std::vector<float> &Chan::GetVolumes()
{
    return this->volumes;
}

std::vector<Bar> &Chan::GetBars()
{
    return this->bars;
}

std::vector<Swing> &Chan::GetSwings()
{
    return this->swings;
}

std::vector<Wave> &Chan::GetWaves()
{
    return this->waves;
}

std::vector<Stretch> &Chan::GetStretches()
{
    return this->stretches;
}

std::vector<Trend> &Chan::GetTrends()
{
    return this->trends;
}

void Chan::Reset()
{
    this->highs.clear();
    this->lows.clear();
    this->opens.clear();
    this->closes.clear();
    this->volumes.clear();
    this->bars.clear();
    this->swings.clear();
    this->waves.clear();
    this->stretches.clear();
    this->trends.clear();
    this->ripple = Wave();
}

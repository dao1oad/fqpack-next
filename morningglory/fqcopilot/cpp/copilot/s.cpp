# include "s.h"
#include "../indicator/indicator.h"

std::vector<Trend> find_trends(std::vector<float> &trend_sigs, int start, int end)
{
    std::vector<Trend> trends;
    for (int i = start; i < end;)
    {
        if (trend_sigs[i] == 1)
        {
            Trend trend;
            trend.No = static_cast<long>(trends.size() + 1);
            trend.direction = DirectionType::DIRECTION_DOWN;
            trend.start = i;
            for (int j = i + 1; j <= end; j++)
            {
                if (trend_sigs[j] == -1)
                {
                    trend.end = j;
                    trends.push_back(trend);
                    i = j;
                    break;
                }
            }
            if (trend.end == -1) {
                break;
            }
        }
        else if (trend_sigs[i] == -1)
        {
            Trend trend;
            trend.No = static_cast<long>(trends.size() + 1);
            trend.direction = DirectionType::DIRECTION_UP;
            trend.start = i;
            for (int j = i + 1; j <= end; j++)
            {
                if (trend_sigs[j] == 1)
                {
                    trend.end = j;
                    trends.push_back(trend);
                    i = j;
                    break;
                }
            }
            if (trend.end == -1) {
                break;
            }
        } else {
            i++;
        }
    }
    return trends;
}

std::vector<Stretch> find_stretches(std::vector<float> &stretch_sigs, int start, int end)
{
    std::vector<Stretch> stretches;
    for (int i = start; i < end;)
    {
        if (stretch_sigs[i] == 1)
        {
            Stretch stretch;
            stretch.No = static_cast<long>(stretches.size() + 1);
            stretch.direction = DirectionType::DIRECTION_DOWN;
            stretch.start = i;
            for (int j = i + 1; j <= end; j++)
            {
                if (stretch_sigs[j] == -1)
                {
                    stretch.end = j;
                    stretches.push_back(stretch);
                    i = j;
                    break;
                }
            }
            if (stretch.end == -1) {
                break;
            }
        }
        else if (stretch_sigs[i] == -1)
        {
            Stretch stretch;
            stretch.No = static_cast<long>(stretches.size() + 1);
            stretch.direction = DirectionType::DIRECTION_UP;
            stretch.start = i;
            for (int j = i + 1; j <= end; j++)
            {
                if (stretch_sigs[j] == 1)
                {
                    stretch.end = j;
                    stretches.push_back(stretch);
                    i = j;
                    break;
                }
            }
            if (stretch.end == -1) {
                break;
            }
        } else {
            i++;
        }
    }
    return stretches;
}

std::vector<Wave> find_waves(std::vector<float> &wave_sigs, int start, int end)
{
    std::vector<Wave> waves;
    for (int i = start; i < end;)
    {
        if (wave_sigs[i] == 1)
        {
            Wave wave;
            wave.No = static_cast<long>(waves.size() + 1);
            wave.direction = DirectionType::DIRECTION_DOWN;
            wave.start = i;
            for (int j = i + 1; j <= end; j++)
            {
                if (wave_sigs[j] == -1)
                {
                    wave.end = j;
                    waves.push_back(wave);
                    i = j;
                    break;
                }
            }
            if (wave.end == -1) {
                break;
            }
        }
        else if (wave_sigs[i] == -1)
        {
            Wave wave;
            wave.No = static_cast<long>(waves.size() + 1);
            wave.direction = DirectionType::DIRECTION_UP;
            wave.start = i;
            for (int j = i + 1; j <= end; j++)
            {
                if (wave_sigs[j] == 1)
                {
                    wave.end = j;
                    waves.push_back(wave);
                    i = j;
                    break;
                }
            }
            if (wave.end == -1) {
                break;
            }
        } else {
            i++;
        }
    }
    return waves;
}

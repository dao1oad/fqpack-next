#include "s.h"

Segs find_segments(std::vector<float> &sigs, int start, int end)
{
    Segs segs;
    for (int i = start; i < end;)
    {
        if (sigs[i] == 1)
        {
            Seg seg;
            seg.No = static_cast<long>(segs.size() + 1);
            seg.direction = DirectionType::DIRECTION_DOWN;
            seg.start = i;
            for (int j = i + 1; j <= end; j++)
            {
                if (sigs[j] == -1)
                {
                    seg.end = j;
                    segs.push_back(seg);
                    i = j;
                    break;
                }
            }
            if (seg.end == -1)
            {
                break;
            }
        }
        else if (sigs[i] == -1)
        {
            Seg seg;
            seg.No = static_cast<long>(segs.size() + 1);
            seg.direction = DirectionType::DIRECTION_UP;
            seg.start = i;
            for (int j = i + 1; j <= end; j++)
            {
                if (sigs[j] == 1)
                {
                    seg.end = j;
                    segs.push_back(seg);
                    i = j;
                    break;
                }
            }
            if (seg.end == -1)
            {
                break;
            }
        }
        else
        {
            i++;
        }
    }
    return segs;
}

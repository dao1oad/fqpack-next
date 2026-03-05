#include "common.h"

bool MustParams(std::vector<std::reference_wrapper<std::vector<float>>> params)
{
    std::size_t count = 0;
    for (std::reference_wrapper<std::vector<float>> ref : params)
    {
        std::vector<float>& param = ref.get();
        if (param.size() == 0)
        {
            return false;
        }
        if (count == 0)
        {
            count = param.size();
        }
        else if (count != param.size())
        {
            return false;
        }
    }
    return true;
}
#pragma once

#include <vector>

#include "types.h"

namespace fullcalc {

// Unified calculation: chanlun structures + CLX signals + stop-loss.
FullCalcResult full_calc(const std::vector<float> &high,
                         const std::vector<float> &low,
                         const std::vector<float> &open,
                         const std::vector<float> &close,
                         const std::vector<float> &vol,
                         int wave_opt,
                         int stretch_opt,
                         int trend_opt,
                         const std::vector<int> &model_ids);

} // namespace fullcalc


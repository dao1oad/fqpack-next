#pragma once

#include <chrono>
#include "expiry_time.h"

// 跳空缺口计数1根K线
#ifdef _GAP_COUNT_AS_ONE_BAR
const bool gapCountAsOneBar = true;
#else
const bool gapCountAsOneBar = false;
#endif

#ifdef _ALLOW_SECOND_HIGH_LOW_SWELL
const bool allow_second_high_low_swell = true;
#else
const bool allow_second_high_low_swell = false;
#endif

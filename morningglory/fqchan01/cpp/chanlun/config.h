#pragma once

#include <chrono>

#define EXPIRY_TIME 1780243199

// 9笔强制成段
#ifdef _FORCE_SWELL_WHEN_9WAVE
const bool forceSwellWhen9Wave = true;
#else
const bool forceSwellWhen9Wave = false;
#endif

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

#pragma once

#include "copilot.h"
#include "../chanlun/czsc.h"

std::vector<Trend> find_trends(std::vector<float> &trend_sigs, int start, int end);
std::vector<Stretch> find_stretches(std::vector<float> &stretch_sigs, int start, int end);
std::vector<Wave> find_waves(std::vector<float> &wave_sigs, int start, int end);

#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>
#include <initializer_list>
#include <functional>

// 公共函数
bool MustParams(std::vector<std::reference_wrapper<std::vector<float>>> params);

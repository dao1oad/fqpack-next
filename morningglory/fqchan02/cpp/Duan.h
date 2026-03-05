#ifndef __DUAN_H__
#define __DUAN_H__

#include <vector>

#pragma pack(push, 1)

std::vector<float> Duan1(int nCount, std::vector<float> pIn, std::vector<float> pHigh, std::vector<float> pLow);
std::vector<float> Duan2(int nCount, std::vector<float> pIn, std::vector<float> pHigh, std::vector<float> pLow);

#pragma pack(pop)

#endif

#ifndef __KXIANCHULI_H__
#define __KXIANCHULI_H__

#include <vector>

using namespace std;

#pragma pack(push, 1)

// 原始K线
struct KxianRaw
{
    float gao;
    float di;
};

// 表示合并后的K线
struct Kxian
{
    float gao;     // K线高
    float di;      // K线低
    int fangXiang; // K线方向
    int kaiShi;    // 开始K线坐标
    int jieShu;    // 结束K线坐标
    int zhongJian;
};

class KxianChuLi
{
public:
    vector<KxianRaw> kxianRawList; // 元素K线表
    vector<Kxian> kxianList;       // 包含处理后的K线表
    void add(float gao, float di); // 添加一根K线高和低进行处理
};

struct Bar {
    int i;
    float high;
    float low;
};

struct StdBar
{
    int start;
    int end;
    int vertex;
    float high;
    float low;
    float high_high;
    float low_low;
    float direction;
};

vector<Bar> recognise_bars(int length, vector<float> high, vector<float> low);
vector<StdBar> recognise_std_bars(int length, vector<float> high, vector<float> low);

#pragma pack(pop)

#endif

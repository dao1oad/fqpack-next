#ifndef __FRESHCZSC_COMM_H__
#define __FRESHCZSC_COMM_H__

#include <iostream>
#include <fstream>
#include <vector>
#include <iterator>
#include <algorithm>

#pragma pack(push, 1)

#pragma pack(pop)

struct Bar
{
    int i;
    float high;
    float low;
};

struct MergedBar
{
    int start;
    int end;
    int vertex;
    float high;
    float low;
    float direction;
    float high_high;
    float low_low;
};

struct Bi
{
    int start;
    int end;
    float direction;
    bool identified;
};

class BiData
{

public:
    BiData(int count, std::vector<float> high_list, std::vector<float> low_list);
    ~BiData();

    std::vector<Bi> get_bi_list();

private:
    int count;
    std::vector<float> high_list;
    std::vector<float> low_list;
    std::vector<Bar> bar_list;
    std::vector<MergedBar> merged_bar_list;
    std::vector<Bi> bi_list;

    void create_bar_list();
    void create_bi_list();
};

struct Vertex
{
    int i;
    int type;
};

struct Duan
{
    int start;
    int end;
    int direction;
};

class DuanData
{

public:
    DuanData(int count, std::vector<float>bi, std::vector<float>high, std::vector<float>low);
    ~DuanData();

    std::vector<Duan> get_duan_list();

private:
    int count;
    std::vector<float>bi;
    std::vector<float>high;
    std::vector<float>low;
    std::vector<Vertex> vertex_list;
    std::vector<Duan> duan_list;
};

struct Pivot
{
    float zg;
    float zd;
    float gg;
    float dd;
    int start;
    int end;
    float direction;
    bool affirm;
};

class PivotData
{
public:
    PivotData(int count, std::vector<float>duan, std::vector<float>bi, std::vector<float>high, std::vector<float>low);
    ~PivotData();
    std::vector<Pivot> get_pivot_list();

private:
    int count;
    std::vector<float>duan;
    std::vector<float>bi;
    std::vector<float>high;
    std::vector<float>low;
    std::vector<Pivot> pivot_list;
};

std::vector<Bar> recognise_bars(int length, std::vector<float> high, std::vector<float> low);
std::vector<MergedBar> recognise_std_bars(int length, std::vector<float> high, std::vector<float> low);
std::vector<float> recognise_swing(int length, std::vector<float> high, std::vector<float> low);
std::vector<float> recognise_bi(int length, std::vector<float> high, std::vector<float> low);
std::vector<float> recognise_duan(int length, std::vector<float> bi, std::vector<float> high, std::vector<float> low);
std::vector<Pivot> recognise_pivots(int count, std::vector<float> duan, std::vector<float> bi, std::vector<float> high, std::vector<float> low);

#endif

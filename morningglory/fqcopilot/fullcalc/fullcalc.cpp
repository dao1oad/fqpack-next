#include "types.h"
#include "fullcalc.h"

#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

#include "chanlun/czsc.h"
#include "../cpp/func_set.h"

namespace fullcalc {

static bool _validate_lengths(const std::vector<float> &h,
                              const std::vector<float> &l,
                              const std::vector<float> &o,
                              const std::vector<float> &c,
                              const std::vector<float> &v,
                              std::string &err) {
    size_t n = h.size();
    if (n == 0) {
        err = "empty input";
        return false;
    }
    if (l.size() != n || o.size() != n || c.size() != n || v.size() != n) {
        err = "length mismatch";
        return false;
    }
    if (n < 10) {
        err = "too few bars (<10)";
        return false;
    }
    return true;
}

static float _compute_stop_loss(const std::vector<int> &bi,
                                const std::vector<float> &low,
                                const std::vector<float> &high,
                                bool is_buy) {
    for (int i = static_cast<int>(bi.size()) - 1; i >= 0; --i) {
        if (is_buy && bi[i] == -1) {
            return i < static_cast<int>(low.size()) ? low[i] : 0.0f;
        }
        if (!is_buy && bi[i] == 1) {
            return i < static_cast<int>(high.size()) ? high[i] : 0.0f;
        }
    }
    return 0.0f;
}

static bool _is_valid_model_id(int model) {
    return model >= 10001 && model <= 10012;
}

FullCalcResult full_calc(const std::vector<float> &high,
                         const std::vector<float> &low,
                         const std::vector<float> &open,
                         const std::vector<float> &close,
                         const std::vector<float> &vol,
                         int wave_opt,
                         int stretch_opt,
                         int trend_opt,
                         const std::vector<int> &model_ids) {
    FullCalcResult res;
    std::string err;
    if (!_validate_lengths(high, low, open, close, vol, err)) {
        res.error = err;
        return res;
    }

    // Work on local copies because downstream APIs expect non-const references.
    std::vector<float> h = high;
    std::vector<float> l = low;
    std::vector<float> o = open;
    std::vector<float> c = close;
    std::vector<float> v = vol;

    const int length = static_cast<int>(h.size());

    // Build chan options based on wave_opt (same rule as copilot).
    ChanOptions options;
    options.bi_mode = wave_opt / 10 % 10;
    options.force_wave_stick_count = wave_opt / 100 % 100;
    options.merge_non_complehensive_wave = wave_opt / 10000 % 10;

    // --- Chanlun structures ---
    auto bi_raw = recognise_bi(length, h, l, options);
    std::vector<int> bi;
    bi.reserve(bi_raw.size());
    // Chanlun().analysis 只保留精确的 ±1 作为顶/底，其余值（0.5/-0.5 等过渡标记）不计入顶底
    for (float vbi : bi_raw) {
        if (vbi == 1.0f) {
            bi.push_back(1);
        } else if (vbi == -1.0f) {
            bi.push_back(-1);
        } else {
            bi.push_back(0);
        }
    }

    auto duan_raw = recognise_duan(length, bi_raw, h, l);
    std::vector<int> duan;
    duan.reserve(duan_raw.size());
    for (float vd : duan_raw) {
        if (vd == 1.0f) {
            duan.push_back(1);
        } else if (vd == -1.0f) {
            duan.push_back(-1);
        } else {
            duan.push_back(0);
        }
    }

    // 高阶段：在段信号上再次识别，保持与 Python Chanlun 相同的链路
    auto duan_high_raw = recognise_duan(length, duan_raw, h, l);
    std::vector<int> duan_high;
    duan_high.reserve(duan_high_raw.size());
    for (float vd : duan_high_raw) {
        if (vd == 1.0f) {
            duan_high.push_back(1);
        } else if (vd == -1.0f) {
            duan_high.push_back(-1);
        } else {
            duan_high.push_back(0);
        }
    }

    // 基础中枢（与 Python entanglement_list 对齐）
    auto pivots_raw = recognise_pivots(length, duan_raw, bi_raw, h, l, options);
    std::vector<PivotOut> pivots;
    pivots.reserve(pivots_raw.size());
    for (const auto &p : pivots_raw) {
        PivotOut out;
        out.start = p.start;
        out.end = p.end;
        out.zg = p.zg;
        out.zd = p.zd;
        out.gg = p.gg;
        out.dd = p.dd;
        out.direction = static_cast<int>(p.direction);
        pivots.push_back(out);
    }

    // 高阶中枢：在高段上识别，再传入上一层段信号，保持 Python high_entanglement_list 的路径
    auto pivots_high_raw = recognise_pivots(length, duan_high_raw, duan_raw, h, l, options);
    std::vector<PivotOut> pivots_high;
    pivots_high.reserve(pivots_high_raw.size());
    for (const auto &p : pivots_high_raw) {
        PivotOut out;
        out.start = p.start;
        out.end = p.end;
        out.zg = p.zg;
        out.zd = p.zd;
        out.gg = p.gg;
        out.dd = p.dd;
        out.direction = static_cast<int>(p.direction);
        pivots_high.push_back(out);
    }

    // --- CLX signals ---
    // 结构-only：model_ids 为空则不跑 CLX
    std::vector<int> models;
    models.reserve(model_ids.size());
    for (int m : model_ids) {
        if (_is_valid_model_id(m)) {
            models.push_back(m);
        }
    }

    std::vector<ClxSignalOut> signals;
    signals.reserve(models.size());
    for (int model : models) {
        auto sigs = clxs(length, h, l, o, c, v, wave_opt, stretch_opt, trend_opt, model);
        if (sigs.empty()) {
            continue;
        }
        int entry = static_cast<int>(sigs.back());
        if (entry == 0) {
            continue;
        }
        ClxSignalOut s;
        s.model = model;
        s.index = length - 1;
        s.signal = entry;
        s.close = c.back();
        s.stop_loss = _compute_stop_loss(bi, l, h, entry > 0);
        signals.push_back(s);
    }

    res.ok = true;
    res.bi = std::move(bi);
    res.duan = std::move(duan);
    res.duan_high = std::move(duan_high);
    res.pivots = std::move(pivots);
    res.pivots_high = std::move(pivots_high);
    res.signals = std::move(signals);
    return res;
}

} // namespace fullcalc

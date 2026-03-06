#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "fullcalc.h"
#include "types.h"

namespace py = pybind11;

static py::dict to_dict(const FullCalcResult &r) {
    py::dict d;
    d["ok"] = r.ok;
    d["error"] = r.error;
    d["bi"] = r.bi;
    d["duan"] = r.duan;
    d["duan_high"] = r.duan_high;

    py::list pivots;
    for (const auto &p : r.pivots) {
        py::dict item;
        item["start"] = p.start;
        item["end"] = p.end;
        item["zg"] = p.zg;
        item["zd"] = p.zd;
        item["gg"] = p.gg;
        item["dd"] = p.dd;
        item["direction"] = p.direction;
        pivots.append(item);
    }
    d["pivots"] = pivots;

    py::list pivots_high;
    for (const auto &p : r.pivots_high) {
        py::dict item;
        item["start"] = p.start;
        item["end"] = p.end;
        item["zg"] = p.zg;
        item["zd"] = p.zd;
        item["gg"] = p.gg;
        item["dd"] = p.dd;
        item["direction"] = p.direction;
        pivots_high.append(item);
    }
    d["pivots_high"] = pivots_high;

    py::list sigs;
    for (const auto &s : r.signals) {
        py::dict item;
        item["model"] = s.model;
        item["index"] = s.index;
        item["signal"] = s.signal;
        item["close"] = s.close;
        item["stop_loss"] = s.stop_loss;
        sigs.append(item);
    }
    d["signals"] = sigs;
    return d;
}

static py::dict full_calc_py(const std::vector<float> &high,
                             const std::vector<float> &low,
                             const std::vector<float> &open,
                             const std::vector<float> &close,
                             const std::vector<float> &vol,
                             int wave_opt = 1560,
                             int stretch_opt = 0,
                             int trend_opt = 1,
                             const std::vector<int> &model_ids = {}) {
    auto res = fullcalc::full_calc(high, low, open, close, vol, wave_opt, stretch_opt, trend_opt, model_ids);
    return to_dict(res);
}

PYBIND11_MODULE(fullcalc, m) {
    m.doc() = "Full calculation (chanlun + CLX signals + stop-loss)";
    m.def("full_calc", &full_calc_py,
          py::arg("high"),
          py::arg("low"),
          py::arg("open"),
          py::arg("close"),
          py::arg("vol"),
          py::arg("wave_opt") = 1560,
          py::arg("stretch_opt") = 0,
          py::arg("trend_opt") = 1,
          py::arg("model_ids") = std::vector<int>{},
          "Compute chanlun structures and CLX signals in one pass.");
}

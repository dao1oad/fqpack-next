import pandas as pd

from freshquant.data.etf_adj import apply_qfq_to_bars, compute_etf_qfq_adj


def test_compute_etf_qfq_adj_split_category11_makes_prices_continuous():
    day = pd.DataFrame(
        [
            {"date": "2025-08-01", "open": 1.12, "high": 1.15, "low": 1.11, "close": 1.138},
            {"date": "2025-08-04", "open": 0.57, "high": 0.58, "low": 0.56, "close": 0.572},
        ]
    )
    xdxr = pd.DataFrame(
        [
            {"date": "2025-08-04", "category": 11, "suogu": 2.0},
        ]
    )

    adj = compute_etf_qfq_adj(day, xdxr)
    out = apply_qfq_to_bars(day, adj, date_col="date")

    # 事件日前一日价格应被缩放约 0.5，接近事件日价格（连续）
    assert abs(out.loc[out["date"] == "2025-08-01", "close"].iloc[0] - 0.569) < 0.01
    assert abs(out.loc[out["date"] == "2025-08-04", "close"].iloc[0] - 0.572) < 1e-6


def test_compute_etf_preclose_dividend_category1_uses_stock_formula():
    day = pd.DataFrame(
        [
            {"date": "2025-12-16", "open": 3.10, "high": 3.11, "low": 3.08, "close": 3.103},
            {"date": "2025-12-17", "open": 3.025, "high": 3.05, "low": 3.00, "close": 3.030},
        ]
    )
    xdxr = pd.DataFrame(
        [
            {
                "date": "2025-12-17",
                "category": 1,
                "fenhong": 0.8,
                "peigu": 0.0,
                "peigujia": 0.0,
                "songzhuangu": 0.0,
            },
        ]
    )

    adj = compute_etf_qfq_adj(day, xdxr)
    out = apply_qfq_to_bars(day, adj, date_col="date")

    # 除息参考价：(prev_close*10 - fenhong) / 10 = prev_close - fenhong/10
    expected_preclose = 3.103 - 0.8 / 10
    # 事件日前一日 qfq 收盘应接近 expected_preclose（连续）
    assert abs(out.loc[out["date"] == "2025-12-16", "close"].iloc[0] - expected_preclose) < 0.02


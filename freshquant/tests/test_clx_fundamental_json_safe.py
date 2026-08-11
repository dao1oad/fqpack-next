"""发布产物 JSON 合法性与非有限浮点清洗测试。

前端使用严格 ``JSON.parse``；Python ``json.dumps`` 默认把 NaN/Infinity 写成
非法 JSON 文本，会导致整份 ranking/stats 产物解析失败（2026-08-11 线上事故）。
"""

from __future__ import annotations

import json

from freshquant.clx_daily_selection.fundamental.contracts import (
    json_dumps_safe,
    sanitize_json_value,
)
from freshquant.clx_daily_selection.fundamental.quick_rank import (
    write_ranking_csv,
    write_ranking_json,
)


def test_sanitize_json_value_flat():
    assert sanitize_json_value(float("nan")) is None
    assert sanitize_json_value(float("inf")) is None
    assert sanitize_json_value(float("-inf")) is None
    assert sanitize_json_value(1.5) == 1.5
    assert sanitize_json_value("nan") == "nan"
    assert sanitize_json_value(None) is None


def test_sanitize_json_value_nested():
    payload = {
        "ok": True,
        "price": float("nan"),
        "rows": [{"pe": float("inf"), "roe": 3.2}, {"pe": None}],
    }
    cleaned = sanitize_json_value(payload)
    assert cleaned["price"] is None
    assert cleaned["rows"][0]["pe"] is None
    assert cleaned["rows"][0]["roe"] == 3.2
    assert cleaned["rows"][1]["pe"] is None
    assert "nan" not in json.dumps(cleaned)


def test_json_dumps_safe_never_emits_nan():
    text = json_dumps_safe(
        {"rows": [{"p_pe": float("nan"), "p_roe": float("-inf")}]},
        sort_keys=True,
    )
    assert "NaN" not in text
    assert "Infinity" not in text
    parsed = json.loads(text)
    assert parsed["rows"][0]["p_pe"] is None
    assert parsed["rows"][0]["p_roe"] is None


def test_write_ranking_json_produces_parseable_output(tmp_path):
    payload = {
        "tradeDate": "2026-08-11",
        "rows": [
            {
                "symbol": "600001",
                "p_pe": float("nan"),
                "p_roe": 12.5,
                "dimension_scores": {"growth": float("nan")},
            }
        ],
    }
    path = tmp_path / "clx-fundamental-ranking.json"
    write_ranking_json(path, payload)
    text = path.read_text(encoding="utf-8")
    assert "NaN" not in text
    parsed = json.loads(text)  # 严格解析，抛错即失败
    assert parsed["rows"][0]["p_pe"] is None
    assert parsed["rows"][0]["dimension_scores"]["growth"] is None


def test_write_ranking_csv_never_contains_nan(tmp_path):
    rows = [
        {
            "symbol": "600001",
            "name": "测试A",
            "pe": float("nan"),
            "composite_grade": "good",
        }
    ]
    path = tmp_path / "clx-fundamental-ranking.csv"
    write_ranking_csv(path, rows)
    content = path.read_text(encoding="utf-8-sig")
    data_rows = content.splitlines()[1:]  # 表头含 financial_report_date，跳过
    assert "nan" not in "\n".join(data_rows).lower()
    assert "600001" in content

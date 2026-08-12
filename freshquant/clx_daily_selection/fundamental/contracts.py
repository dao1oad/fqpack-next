"""CLX 基本面评价数据合同。

定义快排、深析、快照与统计产物的字段、枚举与确定性排序键口径。所有产物
字段名保持稳定，前端与统计脚本只消费本模块声明的字段。
"""

from __future__ import annotations

import json
import math
from typing import Any, Final


def sanitize_json_value(value: Any) -> Any:
    """递归把非有限浮点（NaN/Infinity）归一为 None，保证 JSON 产物合法。

    前端使用严格 ``JSON.parse``，裸 ``NaN``/``Infinity`` 会让整个产物解析失败
    （Python ``json.dumps`` 默认会把 NaN 序列化成非法 JSON 文本）。本函数在
    发布前统一清洗；清洗后 null 由前端按"无数据"渲染（如 `-`）。
    """
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, dict):
        return {key: sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_json_value(item) for item in value]
    return value


def json_dumps_safe(payload: Any, **kwargs: Any) -> str:
    """NaN/Infinity 清洗后的 JSON 序列化（allow_nan=False 兜底防再泄漏）。"""
    return json.dumps(sanitize_json_value(payload), allow_nan=False, **kwargs)


# ---------------------------------------------------------------------------
# 等级口径（与 a-share-fundamental-analysis 评分框架一致）
# ---------------------------------------------------------------------------

#: 六维离散等级，升序即越差；evidence_gap 表示证据覆盖不足（不参与排序比较）。
GRADES: Final[tuple[str, ...]] = (
    "strong",
    "good",
    "neutral",
    "watch",
    "weak",
    "evidence_gap",
)

GRADE_ORDER: Final[dict[str, int]] = {
    value: index for index, value in enumerate(GRADES)
}

#: 六维评分权重（商业质量/成长/盈利质量/资产负债/行业能力/估值）。
DIMENSION_WEIGHTS: Final[dict[str, float]] = {
    "business_quality": 0.20,
    "growth": 0.20,
    "profitability": 0.15,
    "balance_sheet": 0.20,
    "industry_capability": 0.15,
    "valuation": 0.10,
}

#: 六维字段顺序（同时是排序键的字典序口径）。
SIX_DIMENSIONS: Final[tuple[str, ...]] = (
    "business_quality",
    "growth",
    "profitability",
    "balance_sheet",
    "industry_capability",
    "valuation",
)

#: 深析/初评分层。
TIER_DEEP: Final[str] = "deep"
TIER_SNAPSHOT: Final[str] = "snapshot"

#: 快排前 N 只进入标准单股深析（#601 全量深析：默认 200，当日不足 200 时全量）。
DEEP_TIER_LIMIT: Final[int] = 200

#: 等级来源。
GRADE_SOURCE_QUICK: Final[str] = "quick"
GRADE_SOURCE_DEEP: Final[str] = "deep"

#: 证据等级（A/B/C/D，降序）。
EVIDENCE_GRADE_ORDER: Final[dict[str, int]] = {"A": 0, "B": 1, "C": 2, "D": 3}

#: 证据等级阈值（D 级数量超过该值时批次质量门给出琥珀提示）。
EVIDENCE_D_THRESHOLD: Final[int] = 10

#: 质量门阈值。
QUALITY_GATE_DEEP_COMPLETION_RATE: Final[float] = 1.0
QUALITY_GATE_EVIDENCE_AB_SHARE: Final[float] = 0.8
QUALITY_GATE_COLLECTION_COMPLETENESS: Final[float] = 0.95
QUALITY_GATE_RERUN_CONSISTENCY: Final[float] = 0.95

# ---------------------------------------------------------------------------
# 产物 schema 版本
# ---------------------------------------------------------------------------

RANKING_SCHEMA_VERSION: Final[str] = "clx-fundamental-ranking.v1"
ANALYSIS_SCHEMA_VERSION: Final[str] = "fundamental-analysis.v1"
SNAPSHOT_SCHEMA_VERSION: Final[str] = "fundamental-snapshot.v1"
STATS_SCHEMA_VERSION: Final[str] = "fundamental-stats.v1"
INPUT_SCHEMA_VERSION: Final[str] = "clx-fundamental-input.v1"
LATEST_SCHEMA_VERSION: Final[str] = "clx-eval-latest.v2"

#: 数字输出精度（排序键与 CSV 字节级一致性的固定舍入口径）。
SCORE_PRECISION: Final[int] = 6
METRIC_PRECISION: Final[int] = 4

# ---------------------------------------------------------------------------
# 文件命名
# ---------------------------------------------------------------------------

RANKING_CSV_NAME: Final[str] = "clx-fundamental-ranking.csv"
RANKING_JSON_NAME: Final[str] = "clx-fundamental-ranking.json"
STATS_JSON_NAME: Final[str] = "fundamental-stats.json"
ANALYSIS_DIR_NAME: Final[str] = "fundamental-analysis"
SNAPSHOT_DIR_NAME: Final[str] = "fundamental-snapshot"
SPEC_DIR_NAME: Final[str] = "fundamental-analysis-spec"
INPUT_JSON_NAME: Final[str] = "clx-fundamental-input.json"
VALIDATION_JSON_NAME: Final[str] = "fundamental-validation.json"


def rank_grade(score: float | None) -> str:
    """把 0..1 的确定性得分映射为六维等级；缺失返回 evidence_gap。"""
    if score is None:
        return "evidence_gap"
    if score >= 0.80:
        return "strong"
    if score >= 0.60:
        return "good"
    if score >= 0.40:
        return "neutral"
    if score >= 0.20:
        return "watch"
    return "weak"

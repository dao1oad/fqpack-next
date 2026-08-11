"""CLX 基本面驱动评价管线（Issue #570）。

将 CLX pure-buy 全量标的按确定性规则做基本面快排，前 100 只进入标准单股
深析（a-share-fundamental-analysis），其余输出本期初评快照；排序、统计与
质量门均由确定性脚本完成，LLM 只输出六维离散等级与依据。
"""

from __future__ import annotations

from .contracts import (  # noqa: F401
    DEEP_TIER_LIMIT,
    EVIDENCE_GRADE_ORDER,
    GRADE_ORDER,
    GRADES,
    RANKING_SCHEMA_VERSION,
    SIX_DIMENSIONS,
    STATS_SCHEMA_VERSION,
    TIER_DEEP,
    TIER_SNAPSHOT,
)

__all__ = [
    "DEEP_TIER_LIMIT",
    "EVIDENCE_GRADE_ORDER",
    "GRADE_ORDER",
    "GRADES",
    "RANKING_SCHEMA_VERSION",
    "SIX_DIMENSIONS",
    "STATS_SCHEMA_VERSION",
    "TIER_DEEP",
    "TIER_SNAPSHOT",
]

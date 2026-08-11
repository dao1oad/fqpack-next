"""跨日连续入选次数（近 5 个已发布运行）。

确定性规则：按数据目录中已发布 runs 的 tradeDate 倒序，统计截至当前
交易日连续入选（含当日）的天数；只读取已发布产物，不读未来数据。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any


def load_previous_runs(
    data_dir: pathlib.Path, current_trade_date: str
) -> list[dict[str, Any]]:
    """读取数据目录索引，返回 tradeDate < 当前日的已发布 runs（倒序）。"""
    index_path = data_dir / "index.json"
    if not index_path.is_file():
        return []
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    runs = [
        entry
        for entry in (index.get("runs") or [])
        if str(entry.get("tradeDate") or "") < current_trade_date
        and str(entry.get("status") or "") == "published"
        and entry.get("fundamentalRankingHref")
    ]
    runs.sort(key=lambda entry: str(entry.get("tradeDate") or ""), reverse=True)
    return runs


def _ranking_symbols(data_dir: pathlib.Path, href: str) -> set[str]:
    """从已发布 ranking href 读取符号集合；href 以 /data/ 开头时映射到数据目录。"""
    relative = href
    if relative.startswith("/data/clx-evaluator/"):
        relative = relative[len("/data/clx-evaluator/") :]
    path = data_dir / relative
    if not path.is_file():
        path = data_dir / "runs" / relative
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return {str(row.get("symbol")) for row in (payload.get("rows") or [])}


def consecutive_selection_days(
    data_dir: pathlib.Path,
    symbol: str,
    current_trade_date: str,
    window: int = 5,
) -> int:
    """近 window 个已发布交易日连续入选天数（含当日，至少为 1）。"""
    previous = load_previous_runs(data_dir, current_trade_date)[:window]
    count = 1
    for entry in previous:
        href = str(entry.get("fundamentalRankingHref") or "")
        if not href:
            break
        if symbol in _ranking_symbols(data_dir, href):
            count += 1
        else:
            break
    return count


def apply_consecutive_counts(
    rows: list[dict[str, Any]], data_dir: pathlib.Path, current_trade_date: str
) -> list[dict[str, Any]]:
    for row in rows:
        row["consecutive_selection_days"] = consecutive_selection_days(
            data_dir, str(row.get("symbol") or ""), current_trade_date
        )
    return rows

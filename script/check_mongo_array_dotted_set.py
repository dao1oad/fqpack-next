# -*- coding: utf-8 -*-
"""Issue #656 CI 静态检查：禁止对数组字段使用点路径写入（Mongo 点路径写
缺失字段会创建嵌套对象而非数组，导致读取端形状漂移——512000 事故根因）。

规则：
- 数组字段：buy_line_armed / buy_active / buy_enabled / max_position_amounts；
- 命中模式：``f"<字段>.{`` 或 ``"<字段>.<数字>"`` 的字面量出现；
- 豁免：同行带 ``# noqa: guarded-array-dotted`` 的受守卫写入（必须由
  ``$type: "array"`` 查询守卫 + 集成测试覆盖，见 guardian_ladder.py）；
- 扫描范围：freshquant/ 下的 *.py（不含 tests/ 的测试文件不豁免，同样受检）。

用法：python script/check_mongo_array_dotted_set.py [root]
退出码：0 = 通过；1 = 存在违规。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ARRAY_FIELDS = (
    "buy_line_armed",
    "buy_active",
    "buy_enabled",
    "max_position_amounts",
)
ALLOW_MARKERS = (
    "noqa: guarded-array-dotted",  # 受 $type:'array' 守卫的点路径写
    "noqa: array-dotted-query",  # 只读查询（find 条件，不产生形状漂移）
)
FIELD_GROUP = "|".join(ARRAY_FIELDS)
PATTERN = re.compile(rf'f?"({FIELD_GROUP})\.(?:\d+|\{{)')


def scan_root(root: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if PATTERN.search(line) and not any(
                marker in line for marker in ALLOW_MARKERS
            ):
                violations.append(
                    f"{path.as_posix()}:{line_number}: {line.strip()[:140]}"
                )
    return violations


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("freshquant")
    violations = scan_root(root)
    if violations:
        print("数组字段点路径写入违规（缺少形状守卫）：")
        for item in violations:
            print(item)
        print(
            "数组字段禁止使用 f\"field.N\" 点路径 $set；如需保留点路径写，"
            "写入必须由 $type:'array' 查询守卫并同行标注 "
            f"# {ALLOW_MARKERS[0]}；只读查询标注 # {ALLOW_MARKERS[1]}"
        )
        return 1
    print("mongo-array-dotted 静态检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

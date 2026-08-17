# -*- coding: utf-8 -*-
"""Issue #656 脚本层测试：静态扫描 + 数据修复脚本（纯逻辑，不依赖 Mongo）。"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

sys.modules.setdefault("freshquant.message", types.ModuleType("freshquant.message"))

import pytest

sys.modules.pop("freshquant.message", None)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace(".", "_"),
        REPO_ROOT / "script" / f"{name}.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fix_mod = _load_script("fix_buy_line_armed_shapes")
scan_mod = _load_script("check_mongo_array_dotted_set")


class TestFixScriptLogic:
    def test_normalize_armed_object_by_value(self):
        assert fix_mod._normalize_armed({"0": False}) == (
            [False, True, True],
            "object->array",
        )
        assert fix_mod._normalize_armed({"0": False, "1": False, "2": False}) == (
            [False, False, False],
            "object->array",
        )

    def test_normalize_armed_missing_defaults_armed(self):
        assert fix_mod._normalize_armed(None) == (
            [True, True, True],
            "missing->default_armed",
        )

    def test_normalize_armed_array_untouched(self):
        assert fix_mod._normalize_armed([False, True, True]) == (
            [False, True, True],
            "",
        )

    def test_plan_documents_only_flags_abnormal(self):
        plans = fix_mod._plan_documents(
            [
                {"_id": 1, "code": "512000", "buy_line_armed": {"0": False}},
                {
                    "_id": 2,
                    "code": "600104",
                    "buy_line_armed": [True, True, True],
                    "buy_active": [False, False, False],
                },
                {"_id": 3, "code": "600271"},
            ]
        )
        assert [item["code"] for item in plans] == ["512000", "600271"]
        assert plans[0]["sets"]["buy_line_armed"] == [False, True, True]
        assert plans[1]["sets"]["buy_line_armed"] == [True, True, True]
        assert plans[1]["sets"]["buy_active"] == [False, False, False]


class TestScanScriptLogic:
    def _scan_text(self, content: str, tmp_path: Path) -> list[str]:
        source = tmp_path / "sample.py"
        source.write_text(content, encoding="utf-8")
        return scan_mod.scan_root(tmp_path)

    def test_flags_unguarded_dotted_write(self, tmp_path):
        violations = self._scan_text(
            '{"$set": {"buy_line_armed.0": False}}\n',
            tmp_path,
        )
        assert len(violations) == 1

    def test_flags_fstring_dotted_write(self, tmp_path):
        violations = self._scan_text(
            'closures = {f"buy_line_armed.{i}": False for i in range(2)}\n',
            tmp_path,
        )
        assert len(violations) == 1

    def test_allows_guarded_marker(self, tmp_path):
        violations = self._scan_text(
            'f"buy_line_armed.{index}": True,  # noqa: guarded-array-dotted\n',
            tmp_path,
        )
        assert violations == []

    def test_allows_query_marker(self, tmp_path):
        violations = self._scan_text(
            '{"buy_enabled.0": True},  # noqa: array-dotted-query\n',
            tmp_path,
        )
        assert violations == []

    def test_ignores_other_fields(self, tmp_path):
        violations = self._scan_text(
            '{"$set": {"armed_levels.1": False}}\n',
            tmp_path,
        )
        assert violations == []

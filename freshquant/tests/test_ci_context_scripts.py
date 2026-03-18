from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path(sys.executable)
COLLECT_CONTEXT_SCRIPT = REPO_ROOT / "script" / "ci" / "collect_ci_context.py"
SELECT_SHARD_SCRIPT = REPO_ROOT / "script" / "ci" / "select_pytest_shard.py"


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_collect_ci_context_script_exists() -> None:
    assert COLLECT_CONTEXT_SCRIPT.exists()


def test_select_pytest_shard_script_exists() -> None:
    assert SELECT_SHARD_SCRIPT.exists()


def test_collect_ci_context_detects_docs_only_changes() -> None:
    module = _load_module(COLLECT_CONTEXT_SCRIPT, "collect_ci_context")

    context = module.build_context(
        changed_files=["docs/current/runtime.md", "README.md"],
        deployment_required=False,
    )

    assert context["docs_only"] is True
    assert context["deployment_required"] is False


def test_collect_ci_context_marks_code_changes_as_not_docs_only() -> None:
    module = _load_module(COLLECT_CONTEXT_SCRIPT, "collect_ci_context")

    context = module.build_context(
        changed_files=["freshquant/rear/api_server.py"],
        deployment_required=True,
    )

    assert context["docs_only"] is False
    assert context["deployment_required"] is True


def test_collect_ci_context_can_import_deploy_plan_module() -> None:
    module = _load_module(COLLECT_CONTEXT_SCRIPT, "collect_ci_context")

    deploy_plan_module = module.load_deploy_plan_module()

    assert hasattr(deploy_plan_module, "build_deploy_plan")


def test_collect_ci_context_preserves_leading_dot_paths() -> None:
    module = _load_module(COLLECT_CONTEXT_SCRIPT, "collect_ci_context")

    context = module.build_context(
        changed_files=[
            "./.github/workflows/ci.yml",
            ".githooks/pre-push",
            ".codex/memory/workflow-rules.md",
        ],
        deployment_required=False,
    )

    assert ".github/workflows/ci.yml" in context["changed_files"]
    assert ".githooks/pre-push" in context["changed_files"]
    assert ".codex/memory/workflow-rules.md" in context["changed_files"]


def test_select_pytest_shard_is_deterministic_and_disjoint() -> None:
    module = _load_module(SELECT_SHARD_SCRIPT, "select_pytest_shard")

    test_files = [
        "freshquant/tests/test_a.py",
        "freshquant/tests/test_b.py",
        "freshquant/tests/test_c.py",
        "freshquant/tests/test_d.py",
        "freshquant/tests/test_e.py",
    ]

    shard_0 = module.select_shard(test_files, shard_index=0, shard_count=3)
    shard_1 = module.select_shard(test_files, shard_index=1, shard_count=3)
    shard_2 = module.select_shard(test_files, shard_index=2, shard_count=3)

    assert shard_0 == module.select_shard(test_files, shard_index=0, shard_count=3)
    assert set(shard_0).isdisjoint(shard_1)
    assert set(shard_0).isdisjoint(shard_2)
    assert set(shard_1).isdisjoint(shard_2)
    assert set(shard_0 + shard_1 + shard_2) == set(test_files)


def test_select_pytest_shard_lists_recursive_tests(tmp_path: Path) -> None:
    module = _load_module(SELECT_SHARD_SCRIPT, "select_pytest_shard")
    nested = tmp_path / "assets"
    nested.mkdir()
    (tmp_path / "test_root.py").write_text("", encoding="utf-8")
    (nested / "test_nested.py").write_text("", encoding="utf-8")

    discovered = module.list_test_files(tmp_path)

    assert (tmp_path / "test_root.py").as_posix() in discovered
    assert (nested / "test_nested.py").as_posix() in discovered


def test_select_pytest_shard_cli_outputs_json(tmp_path: Path) -> None:
    test_list_path = tmp_path / "tests.json"
    test_list_path.write_text(
        json.dumps(
            [
                "freshquant/tests/test_a.py",
                "freshquant/tests/test_b.py",
                "freshquant/tests/test_c.py",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            str(PYTHON),
            str(SELECT_SHARD_SCRIPT),
            "--test-list-json",
            str(test_list_path),
            "--shard-index",
            "1",
            "--shard-count",
            "2",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "selected" in payload

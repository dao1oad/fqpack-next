"""每日跑批脚本回归：模块调用、无全局 skill 依赖、ASCII 注释、PS 5.1 可解析。"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PS1_PATH = REPO_ROOT / "script" / "clx_eval_daily.ps1"


def _ps1_text() -> str:
    return PS1_PATH.read_text(encoding="utf-8-sig")


def test_ps1_invokes_runner_as_module_from_repo() -> None:
    source = _ps1_text()
    assert '$module = "freshquant.clx_daily_selection.fundamental.runner"' in source
    assert "& $py -m $module" in source


def test_ps1_has_no_global_skill_dependency() -> None:
    source = _ps1_text()
    assert "clx-market-context-evaluator" not in source
    assert ".codex/skills" not in source
    assert "$skill" not in source
    assert "clx_run.py" not in source


def test_ps1_comments_are_ascii() -> None:
    source = _ps1_text()
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            assert all(
                ord(char) < 128 for char in line
            ), f"non-ASCII comment at line {line_number}: {line}"
    assert all(ord(char) < 128 for char in source), "ps1 must be pure ASCII"


def test_ps1_keeps_deep_run_closed_loop_steps() -> None:
    source = _ps1_text()
    assert "bootstrap --run-dir" in source
    assert '"deep-run"' in source
    assert '"--run-dir", $RunDir' in source
    assert "Invoke-Runner \"rank --run-dir $RunDir\"" in source
    assert "--allow-incomplete-deep" in source


def test_runner_module_help_invocation_from_repo_cwd() -> None:
    """P0 回归：必须以 `-m` 模块方式调用，直接跑脚本会相对导入失败。"""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "freshquant.clx_daily_selection.fundamental.runner",
            "--help",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "bootstrap" in result.stdout
    assert "deep-run" in result.stdout
    assert "publish" in result.stdout


@pytest.mark.skipif(
    shutil.which("powershell.exe") is None,
    reason="Windows PowerShell 5.1 not available on this host",
)
def test_ps1_parses_under_windows_powershell_5_1(tmp_path: pathlib.Path) -> None:
    """用真实 Windows PowerShell 5.1 解析器验证脚本可解析。"""
    checker = tmp_path / "check_ps51.ps1"
    checker.write_text(
        textwrap.dedent(
            f"""
            $target = '{str(PS1_PATH)}'
            $tokens = $null
            $errors = $null
            $null = [System.Management.Automation.Language.Parser]::ParseFile(
                $target, [ref]$tokens, [ref]$errors)
            if ($errors.Count -gt 0) {{
                foreach ($err in $errors) {{ Write-Output ('ERR: ' + $err.Message) }}
                exit 1
            }}
            Write-Output 'PS51_PARSE_OK'
            """
        ),
        encoding="ascii",
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(checker),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "PS51_PARSE_OK" in result.stdout


def test_runner_importable_without_global_skill_paths() -> None:
    """runner / deep_executor / agent_run 模块不引用全局 skill 路径。"""
    for module in (
        "freshquant.clx_daily_selection.fundamental.runner",
        "freshquant.clx_daily_selection.fundamental.deep_executor",
        "freshquant.clx_daily_selection.fundamental.agent_run",
    ):
        import importlib

        imported = importlib.import_module(module)
        module_path = imported.__file__ or ""
        source = pathlib.Path(module_path).read_text(encoding="utf-8")
        assert "clx-market-context-evaluator" not in source


def test_deep_agent_prompt_forbids_market_replay(tmp_path: pathlib.Path) -> None:
    """agent 提示词必须显式禁止 a-share-market-replay，只保留基本面分析。"""
    from freshquant.clx_daily_selection.fundamental.agent_run import build_prompt

    spec = tmp_path / "spec.md"
    spec.write_text("规格内容", encoding="utf-8")
    prompt = build_prompt(
        "600993",
        spec,
        pathlib.Path(tmp_path / "skill"),
        pathlib.Path(tmp_path / "out.json"),
    )
    assert "a-share-market-replay" in prompt
    assert "禁止调用/读取 a-share-market-replay" in prompt
    assert "只保留基本面分析引擎" in prompt

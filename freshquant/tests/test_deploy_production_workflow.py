from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_deploy_workflow_uses_single_production_entrypoint() -> None:
    text = Path(".github/workflows/deploy-production.yml").read_text(encoding="utf-8")

    assert "script/ci/run_production_deploy.ps1" in text
    assert "py -3.12 -m uv sync --frozen" not in text
    assert "py -3.12 script/ci/run_formal_deploy.py" not in text


def test_run_production_deploy_help_exits_zero() -> None:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "script/ci/run_production_deploy.ps1",
            "-Help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Run production deploy" in result.stdout

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from freshquant.runtime.python_env import xmake_python_env


class BuildPlan(TypedDict):
    workdir: Path
    commands: list[list[str]]
    env: dict[str, str]


def build_fullcalc_plan(
    repo_root: str | Path,
    *,
    target: str | None = None,
    xmake_bin: str = "xmake",
) -> BuildPlan:
    root = Path(repo_root)
    return {
        "workdir": root / "morningglory" / "fqcopilot",
        "commands": [
            [xmake_bin, "f", "-m", "release"],
            [xmake_bin, "build", "-v", "fullcalc_py"],
        ],
        "env": xmake_python_env(root / ".venv", target=target),
    }

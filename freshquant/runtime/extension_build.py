from __future__ import annotations

from pathlib import Path

from freshquant.runtime.python_env import xmake_python_env


def build_fullcalc_plan(
    repo_root: str | Path,
    *,
    target: str | None = None,
    xmake_bin: str = "xmake",
) -> dict[str, object]:
    root = Path(repo_root)
    return {
        "workdir": root / "morningglory" / "fqcopilot",
        "commands": [
            [xmake_bin, "f", "-m", "release"],
            [xmake_bin, "build", "-v", "fullcalc_py"],
        ],
        "env": xmake_python_env(root / ".venv", target=target),
    }

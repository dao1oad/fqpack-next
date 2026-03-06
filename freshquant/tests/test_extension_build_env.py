import tomllib
from pathlib import Path

from freshquant.runtime.extension_build import build_fullcalc_plan


def test_pyproject_includes_pybind11_for_fullcalc_build() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependency_names = {
        item.split("[")[0].split(">=")[0].split("==")[0]
        for item in data["project"]["dependencies"]
    }
    assert "pybind11" in dependency_names


def test_fullcalc_build_plan_uses_repo_venv() -> None:
    plan = build_fullcalc_plan(
        "D:/fqpack/freshquant-2026.2.23",
        target="windows",
        xmake_bin="xmake.exe",
    )

    workdir = Path(plan["workdir"])
    assert workdir.parts[-2:] == ("morningglory", "fqcopilot")
    assert plan["commands"] == [
        ["xmake.exe", "f", "-m", "release"],
        ["xmake.exe", "build", "-v", "fullcalc_py"],
    ]
    assert plan["env"]["FQ_PY_LIB"] == "python312"
    pybind_include = Path(plan["env"]["FQ_PYBIND_INC"])
    assert pybind_include.parts[-5:] == (
        ".venv",
        "Lib",
        "site-packages",
        "pybind11",
        "include",
    )

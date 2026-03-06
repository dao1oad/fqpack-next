import tomllib
from pathlib import Path


def load_root_pyproject() -> dict:
    return tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))


def test_project_python_is_312_only() -> None:
    data = load_root_pyproject()
    assert data["project"]["requires-python"] == ">=3.12,<3.13"


def test_tool_uv_sources_contains_local_runtime_packages() -> None:
    data = load_root_pyproject()
    dependency_names = {
        item.split("[")[0].split(">=")[0].split("==")[0]
        for item in data["project"]["dependencies"]
    }
    sources = data["tool"]["uv"]["sources"]
    assert "fqchan01" in dependency_names
    assert "fqchan02" in dependency_names
    assert "fqchan03" in dependency_names
    assert "fqchan04" in dependency_names
    assert "fqchan06" in dependency_names
    assert "fqcopilot" in dependency_names
    assert "fqxtrade" in dependency_names
    assert "fqdagster" in dependency_names
    assert "xtquant" in dependency_names
    assert "pytdx" in dependency_names
    assert "backtrader" in dependency_names
    assert "quantaxis" in dependency_names
    assert sources["fqchan01"]["path"] == "morningglory/fqchan01/python"
    assert sources["fqchan02"]["path"] == "morningglory/fqchan02/python"
    assert sources["fqchan03"]["path"] == "morningglory/fqchan03/python"
    assert sources["fqchan04"]["path"] == "morningglory/fqchan04/python"
    assert sources["fqchan06"]["path"] == "morningglory/fqchan06/python"
    assert sources["fqcopilot"]["path"] == "morningglory/fqcopilot/python"
    assert sources["fqxtrade"]["path"] == "morningglory/fqxtrade"
    assert sources["fqdagster"]["path"] == "morningglory/fqdagster"
    assert sources["xtquant"]["path"] == "sunflower/xtquant"
    assert sources["pytdx"]["path"] == "sunflower/pytdx"
    assert sources["backtrader"]["path"] == "sunflower/backtrader"
    assert sources["quantaxis"]["path"] == "sunflower/QUANTAXIS"


def test_uv_lock_is_not_gitignored() -> None:
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "\nuv.lock\n" not in f"\n{gitignore}\n"


def test_root_runtime_dependencies_cover_deployment_tools() -> None:
    data = load_root_pyproject()
    dependencies = data["project"]["dependencies"]
    dependency_names = {
        item.split("[")[0].split(">=")[0].split("==")[0].lower()
        for item in dependencies
    }
    assert "jupyterlab" in dependency_names
    assert "ta-lib" in dependency_names


def test_talib_dependency_uses_binary_wheel_release() -> None:
    data = load_root_pyproject()
    talib_dependency = next(
        item
        for item in data["project"]["dependencies"]
        if item.lower().startswith("ta-lib")
    )
    assert talib_dependency == "TA-Lib==0.6.8"

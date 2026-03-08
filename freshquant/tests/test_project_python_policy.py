import runpy
import sys
import tomllib
import types
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


def test_local_extension_packages_require_python312() -> None:
    package_paths = {
        "fqdagster": Path("morningglory/fqdagster/pyproject.toml"),
        "fqchan01": Path("morningglory/fqchan01/python/pyproject.toml"),
        "fqchan04": Path("morningglory/fqchan04/python/pyproject.toml"),
        "fqchan06": Path("morningglory/fqchan06/python/pyproject.toml"),
        "fqcopilot": Path("morningglory/fqcopilot/python/pyproject.toml"),
        "fqxtrade": Path("morningglory/fqxtrade/pyproject.toml"),
    }

    for package_name, path in package_paths.items():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        assert data["project"]["requires-python"] == ">=3.12,<3.13", package_name


def test_fqcopilot_build_system_includes_pybind11() -> None:
    data = tomllib.loads(
        Path("morningglory/fqcopilot/python/pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    requires = {
        item.split("[")[0].split(">=")[0].split("==")[0].lower()
        for item in data["build-system"]["requires"]
    }
    assert "pybind11" in requires


def test_fqcopilot_setup_declares_fullcalc_extension(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_setup(**kwargs):
        captured.update(kwargs)

    class DummyBuildExt:
        def build_extensions(self):
            return None

    class DummyExtension:
        def __init__(self, name, sources, **kwargs):
            self.name = name
            self.sources = sources
            for key, value in kwargs.items():
                setattr(self, key, value)

    cython_build = types.SimpleNamespace(cythonize=lambda exts: exts)
    setuptools_module = types.SimpleNamespace(setup=fake_setup, Extension=DummyExtension)
    setuptools_command = types.SimpleNamespace(build_ext=types.SimpleNamespace(build_ext=DummyBuildExt))
    setuptools_extension = types.SimpleNamespace(Extension=DummyExtension)
    monkeypatch.setitem(sys.modules, "setuptools", setuptools_module)
    monkeypatch.setitem(sys.modules, "setuptools.command", setuptools_command)
    monkeypatch.setitem(
        sys.modules,
        "setuptools.command.build_ext",
        types.SimpleNamespace(build_ext=DummyBuildExt),
    )
    monkeypatch.setitem(sys.modules, "setuptools.extension", setuptools_extension)
    monkeypatch.setitem(sys.modules, "Cython", types.SimpleNamespace(Build=cython_build))
    monkeypatch.setitem(sys.modules, "Cython.Build", cython_build)
    monkeypatch.setitem(
        sys.modules,
        "pybind11",
        types.SimpleNamespace(setup_helpers=types.SimpleNamespace(Pybind11Extension=DummyExtension)),
    )
    monkeypatch.setitem(
        sys.modules,
        "pybind11.setup_helpers",
        types.SimpleNamespace(Pybind11Extension=DummyExtension),
    )

    runpy.run_path("morningglory/fqcopilot/python/setup.py", run_name="__main__")

    ext_modules = captured.get("ext_modules")
    assert ext_modules is not None
    ext_names = {ext.name for ext in ext_modules}
    assert "fullcalc" in ext_names
    fullcalc_ext = next(ext for ext in ext_modules if ext.name == "fullcalc")
    assert any(
        source.replace("\\", "/").endswith("fqchan04/cpp/chanlun/czsc.cpp")
        for source in fullcalc_ext.sources
    )
    assert any(
        source.replace("\\", "/").endswith("cpp/func_set.cpp")
        for source in fullcalc_ext.sources
    )

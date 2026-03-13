from pathlib import Path

from freshquant.runtime.python_env import project_python, xmake_python_env


def test_project_python_points_to_repo_venv_for_windows() -> None:
    path = project_python("D:/fqpack/freshquant-2026.2.23", target="windows")
    assert str(path).endswith(".venv\\Scripts\\python.exe")


def test_project_python_points_to_repo_venv_for_posix() -> None:
    path = project_python("/app/freshquant", target="posix")
    assert str(path).endswith(".venv/bin/python")


def test_xmake_python_env_resolves_base_python_from_pyvenv_cfg(tmp_path: Path) -> None:
    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    (venv_dir / "pyvenv.cfg").write_text(
        "home = C:\\Python312\nversion = 3.12.12\n",
        encoding="utf-8",
    )

    env = xmake_python_env(venv_dir, target="windows")

    assert env["FQ_PY_BASE"] == "C:\\Python312"
    assert env["FQ_PY_INC"].endswith("Python312\\Include")
    assert env["FQ_PY_LIBDIR"].endswith("Python312\\libs")
    assert env["FQ_PY_LIB"] == "python312"
    assert env["FQ_PYBIND_INC"].endswith(".venv\\Lib\\site-packages\\pybind11\\include")


def test_install_bat_prepares_runtime_prerequisites_before_uv_sync() -> None:
    text = Path("install.bat").read_text(encoding="utf-8")
    prereq_index = text.index("install.py --skip-env --runtime-prereqs-only")
    sync_index = text.index("\"%UV_BIN%\" sync --frozen")
    assert prereq_index < sync_index


def test_install_bat_refreshes_fqchan01_before_runtime_install() -> None:
    text = Path("install.bat").read_text(encoding="utf-8")
    sync_line = next(
        line for line in text.splitlines() if '"%UV_BIN%" sync --frozen' in line
    )

    assert "--refresh-package fqchan01" in sync_line
    assert "--reinstall-package fqchan01" in sync_line


def test_install_bat_cleans_fqchan01_build_artifacts_before_uv_sync() -> None:
    text = Path("install.bat").read_text(encoding="utf-8")
    clean_index = text.index('rmdir /s /q "morningglory\\fqchan01\\python\\build"')
    sync_index = text.index('"%UV_BIN%" sync --frozen')
    assert clean_index < sync_index


def test_install_bat_aborts_when_fqchan01_build_cleanup_fails() -> None:
    text = Path("install.bat").read_text(encoding="utf-8")
    assert (
        'rmdir /s /q "morningglory\\fqchan01\\python\\build" || exit /b 1' in text
    )


def test_create_venv_bat_checks_python_version_without_expanding_errorlevel_early() -> (
    None
):
    text = Path("create_venv.bat").read_text(encoding="utf-8")
    assert "if not errorlevel 1 exit /b 0" in text
    assert "if %errorlevel% equ 0 exit /b 0" not in text


def test_create_venv_bat_resolves_uv_without_expanding_errorlevel_early() -> None:
    text = Path("create_venv.bat").read_text(encoding="utf-8")
    assert "where uv >nul 2>nul\nif not errorlevel 1 (" in text
    assert "if %errorlevel% equ 0 (" not in text


def test_install_py_does_not_require_chardet_before_uv_sync() -> None:
    text = Path("install.py").read_text(encoding="utf-8")
    assert "try:\n    import chardet" in text
    assert "except ImportError:\n    chardet = None" in text

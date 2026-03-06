from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath


def _normalize_target(target: str | None) -> str:
    if target:
        normalized = target.lower()
        if normalized in {"windows", "win"}:
            return "windows"
        if normalized in {"posix", "linux"}:
            return "posix"
        raise ValueError(f"unsupported target: {target}")
    return "windows" if os.name == "nt" else "posix"


def _read_pyvenv_cfg(venv_root: Path) -> dict[str, str]:
    cfg_path = venv_root / "pyvenv.cfg"
    if not cfg_path.exists():
        return {}
    data: dict[str, str] = {}
    for line in cfg_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip().lower()] = value.strip()
    return data


def project_python(
    repo_root: str | Path,
    *,
    target: str | None = None,
) -> PureWindowsPath | PurePosixPath:
    normalized_target = _normalize_target(target)
    if normalized_target == "windows":
        return PureWindowsPath(str(repo_root)) / ".venv" / "Scripts" / "python.exe"
    return PurePosixPath(str(repo_root)) / ".venv" / "bin" / "python"


def xmake_python_env(
    venv_root: str | Path,
    *,
    target: str | None = None,
) -> dict[str, str]:
    normalized_target = _normalize_target(target)
    venv_path = Path(venv_root)
    pyvenv_cfg = _read_pyvenv_cfg(venv_path)
    version = pyvenv_cfg.get("version", "3.12")
    version_parts = version.split(".")
    major = version_parts[0] if version_parts else "3"
    minor = version_parts[1] if len(version_parts) > 1 else "12"
    python_lib = f"python{major}{minor}"

    if normalized_target == "windows":
        windows_base = PureWindowsPath(pyvenv_cfg.get("home") or str(venv_path))
        windows_pybind_inc = (
            PureWindowsPath(str(venv_root))
            / "Lib"
            / "site-packages"
            / "pybind11"
            / "include"
        )
        return {
            "FQ_PY_BASE": str(windows_base),
            "FQ_PY_INC": str(windows_base / "Include"),
            "FQ_PY_LIBDIR": str(windows_base / "libs"),
            "FQ_PY_LIB": python_lib,
            "FQ_PYBIND_INC": str(windows_pybind_inc),
        }

    posix_base = PurePosixPath(pyvenv_cfg.get("home") or str(venv_path))
    posix_pybind_inc = (
        PurePosixPath(str(venv_root))
        / "lib"
        / f"python{major}.{minor}"
        / "site-packages"
        / "pybind11"
        / "include"
    )
    return {
        "FQ_PY_BASE": str(posix_base),
        "FQ_PY_INC": str(posix_base / "include" / f"python{major}.{minor}"),
        "FQ_PY_LIBDIR": str(posix_base / "lib"),
        "FQ_PY_LIB": python_lib,
        "FQ_PYBIND_INC": str(posix_pybind_inc),
    }

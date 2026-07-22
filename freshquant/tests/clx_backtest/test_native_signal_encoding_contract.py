from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_SOURCE = Path(__file__).with_name("native_signal_encoding_contract.cpp")
INCLUDE_DIR = REPO_ROOT / "morningglory" / "fqcopilot" / "cpp" / "copilot"


def test_native_signal_encoding_contract(tmp_path: Path) -> None:
    compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("a C++14 compiler is required for the native encoding contract")
    assert compiler is not None

    executable = tmp_path / "native_signal_encoding_contract"
    subprocess.run(
        [
            compiler,
            "-std=c++14",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(INCLUDE_DIR),
            str(CONTRACT_SOURCE),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [str(executable)],
        check=True,
        capture_output=True,
        text=True,
    )

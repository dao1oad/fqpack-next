from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_RUN_ROOT = REPO_ROOT / "codex_run"
WRAPPER_SCRIPT = CODEX_RUN_ROOT / "start_freshquant_codex.ps1"
CLI_BAT = CODEX_RUN_ROOT / "start_codex_cli.bat"
APP_SERVER_BAT = CODEX_RUN_ROOT / "start_codex_app_server.bat"


def test_codex_run_entrypoints_exist() -> None:
    assert WRAPPER_SCRIPT.exists()
    assert CLI_BAT.exists()
    assert APP_SERVER_BAT.exists()


def test_shared_codex_wrapper_bootstraps_memory_before_launch() -> None:
    content = WRAPPER_SCRIPT.read_text(encoding="utf-8")

    assert "bootstrap_freshquant_memory.py" in content
    assert "FQ_MEMORY_CONTEXT_PATH" in content
    assert "FQ_MEMORY_CONTEXT_ROLE" in content
    assert "FQ_MEMORY_ISSUE_IDENTIFIER" in content
    assert "codex" in content
    assert "app-server" in content


def test_app_server_wrapper_prints_foreground_status_guidance() -> None:
    content = WRAPPER_SCRIPT.read_text(encoding="utf-8")

    assert "stdio://" in content
    assert "context_pack_path" in content
    assert "Close this window to stop the server." in content
    assert "app-server runs in the foreground." in content
    assert "Ctrl+C" in content


def test_cli_bat_calls_wrapper_in_cli_mode() -> None:
    content = CLI_BAT.read_text(encoding="utf-8")

    assert "start_freshquant_codex.ps1" in content
    assert "-Mode cli" in content
    assert 'if "%~1"==""' in content
    assert "%*" in content
    assert any(
        "-Mode cli" in line and "-CodexArgs" not in line
        for line in content.splitlines()
    )
    assert any(
        "-Mode cli" in line and "-CodexArgs %*" in line for line in content.splitlines()
    )


def test_app_server_bat_calls_wrapper_in_app_server_mode() -> None:
    content = APP_SERVER_BAT.read_text(encoding="utf-8")

    assert "start_freshquant_codex.ps1" in content
    assert "-Mode app-server" in content
    assert 'if "%~1"==""' in content
    assert "%*" in content
    assert any(
        "-Mode app-server" in line and "-CodexArgs" not in line
        for line in content.splitlines()
    )
    assert any(
        "-Mode app-server" in line and "-CodexArgs %*" in line
        for line in content.splitlines()
    )

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GITATTRIBUTES_PATH = REPO_ROOT / ".gitattributes"
PRE_COMMIT_CONFIG_PATH = REPO_ROOT / ".pre-commit-config.yaml"


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_gitattributes_declares_repository_line_endings() -> None:
    lines = _read_lines(GITATTRIBUTES_PATH)

    expected_entries = {
        "/.gitattributes text eol=lf",
        "/.gitignore text eol=lf",
        "/.editorconfig text eol=lf",
        "/.dockerignore text eol=lf",
        "*.py text eol=lf",
        "*.js text eol=lf",
        "*.html text eol=lf",
        "*.md text eol=lf",
        "*.yml text eol=lf",
        "*.yaml text eol=lf",
        "*.ps1 text eol=lf",
        "*.sh text eol=lf",
        "Dockerfile* text eol=lf",
        "*.bat text eol=crlf",
        "*.cmd text eol=crlf",
    }

    assert expected_entries.issubset(set(lines))


def test_pre_commit_guards_mixed_line_endings_without_autofix() -> None:
    content = _read_text(PRE_COMMIT_CONFIG_PATH)
    match = re.search(
        r"(?ms)^\s*-\s+id:\s+mixed-line-ending\s*$.*?^\s*args:\s+\[--fix=no\]\s*$",
        content,
    )

    assert match is not None

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GITATTRIBUTES_PATH = REPO_ROOT / ".gitattributes"
PRE_COMMIT_CONFIG_PATH = REPO_ROOT / ".pre-commit-config.yaml"


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _load_pre_commit_repos() -> list[dict]:
    payload = yaml.safe_load(PRE_COMMIT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    repos = payload.get("repos")
    assert isinstance(repos, list)
    return repos


def test_gitattributes_declares_repository_line_endings() -> None:
    lines = _read_lines(GITATTRIBUTES_PATH)

    expected_entries = {
        ".gitattributes text eol=lf",
        ".gitignore text eol=lf",
        ".editorconfig text eol=lf",
        ".dockerignore text eol=lf",
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
    repos = _load_pre_commit_repos()

    mixed_line_ending_hook: dict | None = None
    for repo in repos:
        hooks = repo.get("hooks", [])
        if not isinstance(hooks, list):
            continue
        for hook in hooks:
            if hook.get("id") == "mixed-line-ending":
                mixed_line_ending_hook = hook
                break
        if mixed_line_ending_hook is not None:
            break

    assert mixed_line_ending_hook is not None
    assert mixed_line_ending_hook.get("args") == ["--fix=no"]

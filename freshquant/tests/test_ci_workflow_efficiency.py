from __future__ import annotations

from pathlib import Path


def test_ci_workflow_uses_changed_files_job_and_cache() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "changes:" in text
    assert "actions/cache@v4" in text
    assert "collect_ci_context.py" in text


def test_ci_workflow_reduces_redundant_uv_sync_steps() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert text.count("uv sync --frozen") == 1


def test_ci_workflow_shards_pytest_with_matrix() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "matrix:" in text
    assert "select_pytest_shard.py" in text
    assert "strategy:" in text
    assert "name: pytest-shard (${{ matrix.shard }})" in text
    assert "\n  pytest:\n" in text


def test_ci_workflow_does_not_expand_large_changed_file_lists_into_processes() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "--base-ref origin/${{ github.base_ref || 'main' }} --head-ref HEAD" in text
    assert "--from-ref origin/${{ github.base_ref || 'main' }} --to-ref HEAD" in text
    assert "CHANGED_FILES_JSON:" not in text
    assert (
        "--changed-files-json '${{ needs.changes.outputs.changed_files_json }}'"
        not in text
    )

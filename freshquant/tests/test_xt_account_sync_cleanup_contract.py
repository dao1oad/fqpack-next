from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_split_worker_entrypoints_are_removed() -> None:
    assert not (REPO_ROOT / "freshquant/position_management/worker.py").exists()
    assert not (
        REPO_ROOT / "freshquant/order_management/credit_subjects/worker.py"
    ).exists()


def test_repo_entrypoints_only_reference_xt_account_sync_worker() -> None:
    docs_index = (REPO_ROOT / "docs/index.md").read_text(encoding="utf-8")
    claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "freshquant.position_management.worker" not in docs_index
    assert "freshquant.position_management.worker" not in claude
    assert "position_management.worker" not in agents
    assert "freshquant.xt_account_sync.worker" in docs_index
    assert "freshquant.xt_account_sync.worker" in claude

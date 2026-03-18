from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEW_THREAD_CHECK_SCRIPT = REPO_ROOT / "script" / "ci" / "check_pr_review_threads.py"


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_review_thread_check_parses_pr_view_payload() -> None:
    module = _load_module(REVIEW_THREAD_CHECK_SCRIPT, "check_pr_review_threads_parse")

    assert module.parse_pr_view({"number": 223, "url": "https://example/pr/223"}) == {
        "number": 223,
        "url": "https://example/pr/223",
    }
    assert (
        module.parse_pr_view({"number": "223", "url": "https://example/pr/223"}) is None
    )


def test_review_thread_check_counts_only_unresolved_threads() -> None:
    module = _load_module(REVIEW_THREAD_CHECK_SCRIPT, "check_pr_review_threads_count")
    first_page = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {"isResolved": True},
                            {"isResolved": False},
                        ],
                        "pageInfo": {
                            "hasNextPage": True,
                            "endCursor": "cursor_1",
                        },
                    }
                }
            }
        }
    }
    second_page = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {"isResolved": False},
                            {"isResolved": False},
                        ],
                        "pageInfo": {
                            "hasNextPage": False,
                            "endCursor": None,
                        },
                    }
                }
            }
        }
    }

    nodes, has_next_page, cursor = module.extract_review_thread_page(first_page)

    assert len(nodes) == 2
    assert has_next_page is True
    assert cursor == "cursor_1"
    assert module.count_unresolved_threads([first_page, second_page]) == 3


def test_review_thread_check_rejects_missing_pull_request_payload() -> None:
    module = _load_module(
        REVIEW_THREAD_CHECK_SCRIPT, "check_pr_review_threads_fail_closed"
    )

    try:
        module.extract_review_thread_page({"data": {"repository": {}}})
    except RuntimeError as exc:
        assert "pullRequest" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for missing GraphQL pullRequest")

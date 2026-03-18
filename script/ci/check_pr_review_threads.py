#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REVIEW_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        nodes {
          isResolved
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
"""


def parse_pr_view(payload: dict) -> dict | None:
    if not isinstance(payload, dict):
        return None
    number = payload.get("number")
    url = str(payload.get("url") or "").strip()
    if not isinstance(number, int) or number <= 0:
        return None
    return {"number": number, "url": url or None}


def extract_review_thread_page(payload: dict) -> tuple[list[dict], bool, str | None]:
    data = _require_dict(payload.get("data"), "GraphQL response missing data")
    repository = _require_dict(
        data.get("repository"), "GraphQL response missing repository"
    )
    pull_request = _require_dict(
        repository.get("pullRequest"),
        "GraphQL response missing pullRequest",
    )
    review_threads = _require_dict(
        pull_request.get("reviewThreads"),
        "GraphQL response missing reviewThreads",
    )
    nodes = _require_list(
        review_threads.get("nodes"),
        "GraphQL response missing reviewThreads.nodes",
    )
    page_info = _require_dict(
        review_threads.get("pageInfo"),
        "GraphQL response missing reviewThreads.pageInfo",
    )
    return (
        [node for node in nodes if isinstance(node, dict)],
        bool(page_info.get("hasNextPage")),
        _text(page_info.get("endCursor")) or None,
    )


def count_unresolved_threads(pages: list[dict]) -> int:
    count = 0
    for payload in pages:
        nodes, _, _ = extract_review_thread_page(payload)
        count += sum(1 for node in nodes if not bool(node.get("isResolved")))
    return count


def _gh_path() -> str | None:
    candidate = shutil.which("gh")
    return str(candidate) if candidate else None


def _run_gh_json(gh_path: str, repo_root: Path, args: list[str]) -> dict:
    result = subprocess.run(
        [gh_path, *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or result.stdout.strip() or "gh failed"
        )
    return json.loads(result.stdout)


def _is_no_pull_request_error(message: str) -> bool:
    text = str(message or "").lower()
    return "no pull requests found" in text or "no pull requests match" in text


def _fetch_unresolved_threads(
    gh_path: str, repo_root: Path, owner: str, name: str, number: int
) -> int:
    pages = []
    cursor = None
    while True:
        command = [
            "api",
            "graphql",
            "-f",
            f"query={REVIEW_THREADS_QUERY}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={number}",
        ]
        if cursor:
            command.extend(["-F", f"after={cursor}"])
        payload = _run_gh_json(gh_path, repo_root, command)
        pages.append(payload)
        _, has_next_page, cursor = extract_review_thread_page(payload)
        if not has_next_page:
            break
    return count_unresolved_threads(pages)


def _print_payload(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _require_dict(value, message: str) -> dict:
    if isinstance(value, dict):
        return value
    raise RuntimeError(message)


def _require_list(value, message: str) -> list:
    if isinstance(value, list):
        return value
    raise RuntimeError(message)


def _text(value) -> str:
    return str(value or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail when the current branch PR still has unresolved review threads."
    )
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    gh_path = _gh_path()
    if gh_path is None:
        return _print_payload({"status": "skipped", "reason": "gh_unavailable"})

    auth = subprocess.run(
        [gh_path, "auth", "status", "--hostname", "github.com"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if auth.returncode != 0:
        return _print_payload({"status": "skipped", "reason": "gh_unauthenticated"})

    pr_view = subprocess.run(
        [gh_path, "pr", "view", "--json", "number,url"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if pr_view.returncode != 0:
        if _is_no_pull_request_error(pr_view.stderr):
            return _print_payload({"status": "skipped", "reason": "no_pull_request"})
        print(
            pr_view.stderr.strip() or pr_view.stdout.strip() or "gh pr view failed",
            file=sys.stderr,
        )
        return 1

    pr_payload = parse_pr_view(json.loads(pr_view.stdout))
    if pr_payload is None:
        return _print_payload({"status": "skipped", "reason": "invalid_pr_payload"})

    repo_payload = _run_gh_json(
        gh_path,
        repo_root,
        ["repo", "view", "--json", "owner,name"],
    )
    owner = _text(_as_dict(repo_payload.get("owner")).get("login"))
    name = _text(repo_payload.get("name"))
    if not owner or not name:
        print("Unable to resolve GitHub repository owner/name.", file=sys.stderr)
        return 1

    unresolved = _fetch_unresolved_threads(
        gh_path,
        repo_root,
        owner=owner,
        name=name,
        number=int(pr_payload["number"]),
    )
    payload = {
        "status": "passed" if unresolved == 0 else "failed",
        "reason": None if unresolved == 0 else "unresolved_review_threads",
        "pr_number": int(pr_payload["number"]),
        "pr_url": pr_payload["url"],
        "unresolved_threads": unresolved,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if unresolved == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from freshquant.runtime.memory import MemoryRuntimeConfig, MongoMemoryStore


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _ref_file_exists(repo_root: Path, reference_ref: str, relative_path: str) -> bool:
    result = _run_git(
        repo_root,
        "cat-file",
        "-e",
        f"{reference_ref}:{relative_path}",
    )
    return result.returncode == 0


def _latest_mtime(path: Path) -> float:
    latest = path.stat().st_mtime
    for child in path.rglob("*"):
        try:
            latest = max(latest, child.stat().st_mtime)
        except OSError:
            continue
    return latest


def archive_stale_context_packs(
    config: MemoryRuntimeConfig,
    *,
    archive_root: Path,
    days: int,
    dry_run: bool,
) -> list[dict[str, object]]:
    packs_root = config.artifact_root / "context-packs"
    cutoff = datetime.now(UTC).timestamp() - max(int(days), 1) * 86400
    archived: list[dict[str, object]] = []
    if not packs_root.exists():
        return archived
    stamp = datetime.now().strftime("%Y%m%d")
    for issue_dir in sorted(packs_root.iterdir()):
        if not issue_dir.is_dir():
            continue
        if _latest_mtime(issue_dir) >= cutoff:
            continue
        dest = archive_root / "context-packs" / f"{issue_dir.name}-legacy-{stamp}"
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(issue_dir), str(dest))
        archived.append({"issue": issue_dir.name, "moved_to": str(dest)})
    return archived


def prune_missing_knowledge_items(
    config: MemoryRuntimeConfig,
    store: MongoMemoryStore,
    *,
    dry_run: bool,
) -> list[dict[str, object]]:
    """删除 source 已不存在的 knowledge_items（对比 reference_ref 与本地文件）。"""
    items = store.find("knowledge_items")
    removed: list[dict[str, object]] = []
    for item in items:
        source_path = str(item.get("source_path") or "")
        source_ref = str(item.get("source_ref") or "")
        if source_ref and source_path.startswith(f"{source_ref}:"):
            relative_path = source_path[len(source_ref) + 1 :]
            exists = _ref_file_exists(config.repo_root, source_ref, relative_path)
        elif source_path.startswith("http") or not source_path:
            continue
        else:
            exists = Path(source_path).exists()
        if exists:
            continue
        if not dry_run:
            store.delete_many(
                "knowledge_items", {"knowledge_item_id": item.get("knowledge_item_id")}
            )
        removed.append(
            {
                "knowledge_item_id": item.get("knowledge_item_id"),
                "source_path": source_path,
            }
        )
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="FreshQuant 记忆整合：归档旧 context packs + 清理 stale knowledge + 输出报告"
    )
    parser.add_argument("--repo-root", default=Path.cwd())
    parser.add_argument("--service-root", default=None)
    parser.add_argument("--archive-root", default=None)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    environ = dict(os.environ)
    if args.service_root:
        environ.setdefault("FRESHQUANT_MEMORY__ARTIFACT_ROOT", "artifacts/memory")
    config = MemoryRuntimeConfig.from_settings(
        repo_root=Path(args.repo_root).resolve(),
        service_root=args.service_root,
        environ=environ,
    )
    archive_root = (
        Path(args.archive_root).resolve()
        if args.archive_root
        else config.artifact_root / "archive"
    )
    store = MongoMemoryStore(
        host=config.mongo_host,
        port=config.mongo_port,
        db_name=config.mongo_db,
    )

    archived_packs = archive_stale_context_packs(
        config,
        archive_root=archive_root,
        days=args.days,
        dry_run=args.dry_run,
    )
    removed_knowledge = prune_missing_knowledge_items(
        config,
        store,
        dry_run=args.dry_run,
    )

    report = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "dry_run": bool(args.dry_run),
        "archive_root": str(archive_root),
        "days": int(args.days),
        "context_packs_archived": archived_packs,
        "knowledge_items_removed": removed_knowledge,
        "counts": {
            "context_packs_archived": len(archived_packs),
            "knowledge_items_removed": len(removed_knowledge),
            "knowledge_items_kept": store.count("knowledge_items"),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if not args.dry_run:
        report_root = config.artifact_root / "consolidation-reports"
        report_root.mkdir(parents=True, exist_ok=True)
        report_path = report_root / f"{datetime.now():%Y%m%d-%H%M%S}.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"report written: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

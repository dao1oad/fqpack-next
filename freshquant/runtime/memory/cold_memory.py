from __future__ import annotations

from pathlib import Path, PurePosixPath


def _extract_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def build_cold_memory_item(
    *,
    relative_path: PurePosixPath,
    content: str,
    source_path: str,
    generated_at: str,
    source_kind: str = "cold_memory",
    source_ref: str | None = None,
) -> dict[str, str]:
    title = _extract_title(content, Path(relative_path.name).stem.replace("-", " ").title())
    category = (
        relative_path.parts[0]
        if len(relative_path.parts) > 1
        else Path(relative_path.name).stem
    )
    item = {
        "knowledge_item_id": relative_path.as_posix(),
        "category": category,
        "title": title,
        "source_path": source_path,
        "content": content,
        "generated_at": generated_at,
        "source_kind": source_kind,
    }
    if source_ref:
        item["source_ref"] = source_ref
    return item


def load_cold_memory_items(
    cold_memory_root: Path, *, generated_at: str, source_ref: str | None = None
) -> list[dict[str, str]]:
    if not cold_memory_root.exists():
        return []

    items: list[dict[str, str]] = []
    for path in sorted(cold_memory_root.rglob("*.md")):
        relative_path = path.relative_to(cold_memory_root)
        content = path.read_text(encoding="utf-8").strip()
        items.append(
            build_cold_memory_item(
                relative_path=PurePosixPath(relative_path.as_posix()),
                content=content,
                source_path=str(path),
                generated_at=generated_at,
                source_ref=source_ref,
            )
        )
    return items

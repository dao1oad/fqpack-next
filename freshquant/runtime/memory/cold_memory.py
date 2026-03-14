from __future__ import annotations

from pathlib import Path


def _extract_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def load_cold_memory_items(cold_memory_root: Path, *, generated_at: str) -> list[dict[str, str]]:
    if not cold_memory_root.exists():
        return []

    items: list[dict[str, str]] = []
    for path in sorted(cold_memory_root.rglob("*.md")):
        relative_path = path.relative_to(cold_memory_root)
        content = path.read_text(encoding="utf-8").strip()
        title = _extract_title(content, path.stem.replace("-", " ").title())
        category = relative_path.parts[0] if len(relative_path.parts) > 1 else path.stem
        items.append(
            {
                "knowledge_item_id": relative_path.as_posix(),
                "category": category,
                "title": title,
                "source_path": str(path),
                "content": content,
                "generated_at": generated_at,
                "source_kind": "cold_memory",
            }
        )
    return items

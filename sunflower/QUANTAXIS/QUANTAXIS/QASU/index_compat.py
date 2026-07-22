from typing import Any


def ensure_compatible_index(collection: Any, fields: list[tuple[str, int]]) -> None:
    """Reuse an existing index with the same key pattern, regardless of options."""
    normalized_fields = list(fields)
    for spec in collection.index_information().values():
        if list(spec.get("key") or []) == normalized_fields:
            return
    collection.create_index(normalized_fields)

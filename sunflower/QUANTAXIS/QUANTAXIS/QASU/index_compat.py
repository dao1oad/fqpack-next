from typing import Any

CANONICAL_INDEX_SPECS: dict[str, list[tuple[str, int]]] = {
    "index_day": [("code", 1), ("date_stamp", 1)],
    "index_min": [
        ("code", 1),
        ("type", 1),
        ("time_stamp", 1),
        ("date_stamp", 1),
    ],
}
LEGACY_COMPATIBLE_INDEX_SPECS: dict[str, list[list[tuple[str, int]]]] = {
    "index_day": [],
    "index_min": [[("code", 1), ("time_stamp", 1), ("date_stamp", 1)]],
}


def _default_index_name(fields: list[tuple[str, int]]) -> str:
    return "_".join(f"{field}_{direction}" for field, direction in fields)


def ensure_compatible_index(
    collection: Any,
    fields: list[tuple[str, int]],
    *,
    unique: bool = True,
    compatible_fields: list[list[tuple[str, int]]] | None = None,
) -> None:
    """Create a canonical index on a new collection without conflicting in place.

    Existing indexes with the same key pattern are reused even when their options
    differ. Option changes are handled by the explicit migration entry point.
    """
    normalized_fields = list(fields)
    compatible_patterns = [list(pattern) for pattern in (compatible_fields or [])]
    for spec in collection.index_information().values():
        existing_fields = list(spec.get("key") or [])
        if (
            existing_fields == normalized_fields
            or existing_fields in compatible_patterns
        ):
            return
    collection.create_index(normalized_fields, unique=unique)


def ensure_canonical_index(collection: Any, collection_name: str) -> None:
    ensure_compatible_index(
        collection,
        CANONICAL_INDEX_SPECS[collection_name],
        unique=True,
        compatible_fields=LEGACY_COMPATIBLE_INDEX_SPECS[collection_name],
    )


def _is_canonical_spec(spec: dict[str, Any], fields: list[tuple[str, int]]) -> bool:
    if list(spec.get("key") or []) != fields or not bool(spec.get("unique")):
        return False
    if bool(spec.get("sparse")) or bool(spec.get("hidden")):
        return False
    return not any(
        option in spec
        for option in (
            "partialFilterExpression",
            "expireAfterSeconds",
            "collation",
            "wildcardProjection",
        )
    )


def _count_duplicate_groups(
    collection: Any,
    fields: list[tuple[str, int]],
) -> int:
    group_id = {field: f"${field}" for field, _direction in fields}
    pipeline = [
        {"$group": {"_id": group_id, "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$count": "groups"},
    ]
    try:
        rows = list(collection.aggregate(pipeline, allowDiskUse=True))
    except TypeError:
        rows = list(collection.aggregate(pipeline))
    return int(rows[0].get("groups") or 0) if rows else 0


def _plan_collection_migration(
    collection_name: str,
    collection: Any,
    fields: list[tuple[str, int]],
) -> dict[str, Any]:
    indexes = collection.index_information()
    canonical_name = _default_index_name(fields)
    canonical_indexes = sorted(
        name for name, spec in indexes.items() if _is_canonical_spec(spec, fields)
    )
    legacy_patterns = LEGACY_COMPATIBLE_INDEX_SPECS[collection_name]
    drop_indexes = sorted(
        name
        for name, spec in indexes.items()
        if name != "_id_"
        and not _is_canonical_spec(spec, fields)
        and (
            list(spec.get("key") or []) == fields
            or list(spec.get("key") or []) in legacy_patterns
            or name == canonical_name
        )
    )
    if canonical_indexes and not drop_indexes:
        return {
            "collection": collection_name,
            "keys": [list(item) for item in fields],
            "unique": True,
            "canonical_indexes": canonical_indexes,
            "drop_indexes": [],
            "duplicate_groups": 0,
            "action": "none",
            "status": "canonical",
        }

    duplicate_groups = (
        0 if canonical_indexes else _count_duplicate_groups(collection, fields)
    )
    return {
        "collection": collection_name,
        "keys": [list(item) for item in fields],
        "unique": True,
        "canonical_indexes": [],
        "drop_indexes": drop_indexes,
        "duplicate_groups": duplicate_groups,
        "action": "cleanup" if canonical_indexes else "replace",
        "status": "blocked" if duplicate_groups else "planned",
    }


def migrate_canonical_indexes(database: Any, *, execute: bool) -> dict[str, Any]:
    """Plan or execute the canonical unique indexes for Index and ETF bars."""
    plans = [
        _plan_collection_migration(
            collection_name,
            database[collection_name],
            list(fields),
        )
        for collection_name, fields in CANONICAL_INDEX_SPECS.items()
    ]
    ready_for_execute = all(int(plan["duplicate_groups"]) == 0 for plan in plans)
    report: dict[str, Any] = {
        "mode": "execute" if execute else "dry-run",
        "ok": True,
        "ready_for_execute": ready_for_execute,
        "changed": 0,
        "collections": plans,
    }
    if not execute:
        return report
    if not ready_for_execute:
        report["ok"] = False
        return report

    changed = 0
    for plan in plans:
        if plan["action"] == "none":
            continue
        collection = database[plan["collection"]]
        for index_name in plan["drop_indexes"]:
            collection.drop_index(index_name)
        if plan["action"] == "replace":
            fields = [tuple(item) for item in plan["keys"]]
            created_name = collection.create_index(
                fields,
                unique=True,
                name=_default_index_name(fields),
            )
            plan["canonical_indexes"] = [created_name]
        plan["status"] = "migrated"
        changed += 1

    report["changed"] = changed
    return report

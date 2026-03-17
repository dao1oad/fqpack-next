from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping, Sequence


class InMemoryMemoryStore:
    def __init__(self) -> None:
        self._collections: dict[str, list[dict[str, Any]]] = {}

    def upsert_many(
        self,
        collection: str,
        documents: Iterable[Mapping[str, Any]],
        *,
        key_fields: Sequence[str],
    ) -> None:
        bucket = self._collections.setdefault(collection, [])
        for document in documents:
            payload = dict(document)
            key = tuple(payload[field] for field in key_fields)
            replaced = False
            for index, existing in enumerate(bucket):
                existing_key = tuple(existing.get(field) for field in key_fields)
                if existing_key == key:
                    bucket[index] = payload
                    replaced = True
                    break
            if not replaced:
                bucket.append(payload)

    def find(
        self,
        collection: str,
        *,
        filters: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        items = [deepcopy(item) for item in self._collections.get(collection, [])]
        if not filters:
            return items
        return [
            item
            for item in items
            if all(item.get(key) == value for key, value in filters.items())
        ]

    def count(self, collection: str) -> int:
        return len(self._collections.get(collection, []))


class MongoMemoryStore:
    def __init__(self, *, host: str, port: int, db_name: str) -> None:
        import pymongo

        from freshquant.carnation.config import TZ

        self._client = pymongo.MongoClient(
            host=host,
            port=port,
            connect=False,
            tz_aware=True,
            tzinfo=TZ,
        )
        self._db = self._client[db_name]

    def upsert_many(
        self,
        collection: str,
        documents: Iterable[Mapping[str, Any]],
        *,
        key_fields: Sequence[str],
    ) -> None:
        collection_ref = self._db[collection]
        for document in documents:
            payload = dict(document)
            query = {field: payload[field] for field in key_fields}
            collection_ref.replace_one(query, payload, upsert=True)

    def find(
        self,
        collection: str,
        *,
        filters: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return list(self._db[collection].find(filters or {}))

    def count(self, collection: str) -> int:
        return self._db[collection].count_documents({})

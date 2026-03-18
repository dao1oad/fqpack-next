from __future__ import annotations

from collections import Counter
from types import SimpleNamespace
from typing import Any

from freshquant.db import DBScreening


class DailyScreeningRepository:
    def __init__(self, db=None):
        self.db = DBScreening if db is None else db
        self.runs = self._resolve_collection("daily_screening_runs")
        self.memberships = self._resolve_collection("daily_screening_memberships")
        self.stock_snapshots = self._resolve_collection(
            "daily_screening_stock_snapshots"
        )

    def index_specs(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "daily_screening_runs": [
                {
                    "name": "daily_screening_runs_run_id",
                    "keys": [("run_id", 1)],
                    "unique": True,
                }
            ],
            "daily_screening_memberships": [
                {
                    "name": "daily_screening_memberships_run_scope_stage_code_model_period_fire_time",
                    "keys": [
                        ("run_id", 1),
                        ("scope", 1),
                        ("stage", 1),
                        ("code", 1),
                        ("model_key", 1),
                        ("period", 1),
                        ("fire_time", 1),
                    ],
                    "unique": True,
                }
            ],
            "daily_screening_stock_snapshots": [
                {
                    "name": "daily_screening_stock_snapshots_run_scope_code",
                    "keys": [("run_id", 1), ("scope", 1), ("code", 1)],
                    "unique": True,
                }
            ],
        }

    def ensure_indexes(self) -> None:
        for collection_name, specs in self.index_specs().items():
            collection = getattr(self, self._collection_attr(collection_name))
            if not hasattr(collection, "create_index"):
                continue
            for spec in specs:
                kwargs: dict[str, Any] = {}
                if spec.get("unique") is not None:
                    kwargs["unique"] = bool(spec["unique"])
                if spec.get("name"):
                    kwargs["name"] = spec["name"]
                collection.create_index(spec["keys"], **kwargs)

    def save_run(self, run=None, **document):
        payload = self._merge_document(run, document)
        run_id = self._primary_value(payload, "run_id")
        if run_id is None:
            raise ValueError("run_id required")
        payload["run_id"] = run_id
        payload.setdefault("id", run_id)
        self._upsert_one(self.runs, {"run_id": run_id}, payload)
        return self.get_run(run_id) or dict(payload)

    def get_run(self, run_id):
        return self._find_one(self.runs, {"run_id": run_id})

    def replace_stage_memberships(
        self,
        run_id=None,
        stage=None,
        memberships=None,
        scope=None,
        **document,
    ):
        raw_items = list(memberships or [])
        effective_run_id = self._resolve_single_identity(
            run_id, raw_items, field_name="run_id"
        )
        effective_stage = self._resolve_single_identity(
            stage, raw_items, field_name="stage"
        )
        effective_scope = self._resolve_single_identity(
            scope, raw_items, field_name="scope"
        )
        if effective_run_id is None:
            raise ValueError("run_id required")
        if effective_stage is None:
            raise ValueError("stage required")
        if not raw_items:
            query = self._scope_query(run_id=effective_run_id, scope=effective_scope)
            query["stage"] = effective_stage
            self._delete_many(self.memberships, query)
            return []
        payloads = [
            self._normalize_membership(
                item,
                run_id=effective_run_id,
                stage=effective_stage,
                scope=effective_scope,
            )
            for item in raw_items
        ]
        if any(
            self._primary_value(payload, "code", "symbol") is None
            for payload in payloads
        ):
            raise ValueError("code required")
        query = self._scope_query(run_id=effective_run_id, scope=effective_scope)
        query["stage"] = effective_stage
        self._delete_many(self.memberships, query)
        if payloads:
            self._insert_many(self.memberships, payloads)
        return payloads

    def upsert_stock_snapshots(
        self,
        run_id=None,
        snapshots=None,
        scope=None,
        **document,
    ):
        raw_items = list(snapshots or [])
        effective_run_id = self._resolve_single_identity(
            run_id, raw_items, field_name="run_id"
        )
        effective_scope = self._resolve_single_identity(
            scope, raw_items, field_name="scope"
        )
        if effective_run_id is None and raw_items:
            raise ValueError("run_id required")
        if not raw_items:
            return []
        payloads = [
            self._normalize_snapshot(
                item, run_id=effective_run_id, scope=effective_scope
            )
            for item in raw_items
        ]
        if any(
            self._primary_value(payload, "code", "symbol") is None
            for payload in payloads
        ):
            raise ValueError("code required")
        for payload in payloads:
            query = self._snapshot_query(
                payload,
                run_id=effective_run_id,
                scope=effective_scope,
            )
            self._upsert_one(self.stock_snapshots, query, payload)
        return payloads

    def query_scope_summary(
        self,
        run_id=None,
        scope=None,
        stage=None,
        **filters,
    ) -> dict[str, Any]:
        membership_query = self._scope_query(run_id=run_id, scope=scope)
        membership_query.update(filters)
        stock_query = self._scope_query(run_id=run_id, scope=scope)
        stock_query.update(filters)
        if stage is not None:
            membership_query["stage"] = stage
        memberships = self._find_many(self.memberships, membership_query)
        stocks = self._find_many(self.stock_snapshots, stock_query)
        stage_counts = Counter(
            str(item.get("stage") or "").strip()
            for item in memberships
            if item.get("stage")
        )
        return {
            "run_id": run_id,
            "scope": scope,
            "membership_count": len(memberships),
            "stock_count": len(stocks),
            "stage_counts": dict(stage_counts),
            "stock_codes": [
                self._stock_identity(item)
                for item in sorted(stocks, key=self._stock_sort_key)
            ],
        }

    def query_scope_stocks(self, run_id=None, scope=None, **filters):
        query = self._scope_query(run_id=run_id, scope=scope)
        query.update(filters)
        stocks = self._find_many(self.stock_snapshots, query)
        return sorted(stocks, key=self._stock_sort_key)

    def get_stock_detail_memberships(
        self, run_id=None, code=None, scope=None, **filters
    ):
        query = self._scope_query(run_id=run_id, scope=scope)
        if code is not None:
            query["code"] = code
        query.update(filters)
        memberships = self._find_many(self.memberships, query)
        return sorted(memberships, key=self._membership_sort_key)

    def _collection_attr(self, collection_name: str) -> str:
        mapping = {
            "daily_screening_runs": "runs",
            "daily_screening_memberships": "memberships",
            "daily_screening_stock_snapshots": "stock_snapshots",
        }
        return mapping[collection_name]

    def _resolve_collection(self, name: str):
        try:
            return self.db[name]
        except Exception:
            return _NullCollection(name)

    def _merge_document(self, value, extra: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if isinstance(value, dict):
            payload.update(value)
        elif value is not None:
            raise TypeError("document must be a mapping")
        payload.update(extra)
        return payload

    def _primary_value(self, payload: dict[str, Any], *keys: str):
        for key in keys:
            value = payload.get(key)
            if value is not None and str(value).strip() != "":
                return value
        return None

    def _first_non_empty(self, value, *candidates):
        if value is not None and str(value).strip() != "":
            return value
        for candidate in candidates:
            if candidate is not None and str(candidate).strip() != "":
                return candidate
        return None

    def _resolve_single_identity(
        self,
        explicit_scope,
        items: list[dict[str, Any]],
        *,
        field_name: str,
    ):
        values = []
        explicit = self._first_non_empty(explicit_scope)
        if explicit is not None:
            values.append(str(explicit).strip())
        for item in items:
            value = self._first_non_empty(self._primary_value(item, field_name))
            if value is not None:
                values.append(str(value).strip())
        normalized = {value for value in values if value}
        if len(normalized) > 1:
            raise ValueError(f"{field_name} must be consistent within one call")
        return next(iter(normalized), None)

    def _scope_query(self, *, run_id=None, scope=None) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if run_id is not None:
            query["run_id"] = run_id
        if scope is not None:
            query["scope"] = scope
        return query

    def _normalize_membership(
        self,
        item: Any,
        *,
        run_id=None,
        stage=None,
        scope=None,
    ) -> dict[str, Any]:
        payload = dict(item or {})
        if run_id is not None:
            payload.setdefault("run_id", run_id)
        if stage is not None:
            payload.setdefault("stage", stage)
        if scope is not None:
            payload.setdefault("scope", scope)
        code = self._primary_value(payload, "code", "symbol")
        if code is not None:
            payload.setdefault("code", code)
        return payload

    def _normalize_snapshot(
        self, item: Any, *, run_id=None, scope=None
    ) -> dict[str, Any]:
        payload = dict(item or {})
        if run_id is not None:
            payload.setdefault("run_id", run_id)
        if scope is not None:
            payload.setdefault("scope", scope)
        code = self._primary_value(payload, "code", "symbol")
        if code is not None:
            payload.setdefault("code", code)
        return payload

    def _snapshot_query(
        self,
        payload: dict[str, Any],
        *,
        run_id=None,
        scope=None,
    ) -> dict[str, Any]:
        query = self._scope_query(run_id=run_id, scope=scope)
        code = self._primary_value(payload, "code", "symbol")
        if code is not None:
            query["code"] = code
        return query

    def _stock_identity(self, item: dict[str, Any]):
        return self._primary_value(item, "code", "symbol")

    def _stock_sort_key(self, item: dict[str, Any]):
        return (
            str(self._primary_value(item, "code", "symbol") or ""),
            str(item.get("name") or ""),
        )

    def _membership_sort_key(self, item: dict[str, Any]):
        return (
            str(item.get("stage") or ""),
            str(self._primary_value(item, "code", "symbol") or ""),
            str(item.get("name") or ""),
        )

    def _find_many(self, collection, query: dict[str, Any]) -> list[dict[str, Any]]:
        if hasattr(collection, "find"):
            rows = collection.find(query or {})
            return [dict(row) for row in list(rows)]
        rows = self._collection_rows(collection)
        return [
            dict(row)
            for row in rows
            if all(row.get(key) == value for key, value in (query or {}).items())
        ]

    def _find_one(self, collection, query: dict[str, Any]):
        if hasattr(collection, "find_one"):
            row = collection.find_one(query)
            return dict(row) if row is not None else None
        rows = self._find_many(collection, query)
        return rows[0] if rows else None

    def _upsert_one(self, collection, query: dict[str, Any], document: dict[str, Any]):
        if hasattr(collection, "replace_one"):
            collection.replace_one(query, document, upsert=True)
            return document
        rows = self._collection_rows(collection)
        if rows is None:
            return document
        for index, row in enumerate(rows):
            if all(row.get(key) == value for key, value in query.items()):
                rows[index] = dict(document)
                return document
        rows.append(dict(document))
        return document

    def _delete_many(self, collection, query: dict[str, Any]):
        if hasattr(collection, "delete_many"):
            collection.delete_many(query)
            return
        rows = self._collection_rows(collection)
        if rows is None:
            return
        remaining = [
            row
            for row in rows
            if not all(row.get(key) == value for key, value in query.items())
        ]
        self._set_collection_rows(collection, remaining)

    def _insert_many(self, collection, documents: list[dict[str, Any]]):
        if hasattr(collection, "insert_many"):
            collection.insert_many(documents, ordered=False)
            return
        rows = self._collection_rows(collection)
        if rows is None:
            return
        rows.extend(dict(doc) for doc in documents)

    def _collection_rows(self, collection):
        if hasattr(collection, "docs"):
            return collection.docs
        if hasattr(collection, "documents"):
            return collection.documents
        return None

    def _set_collection_rows(self, collection, rows):
        if hasattr(collection, "docs"):
            collection.docs = list(rows)
        elif hasattr(collection, "documents"):
            collection.documents = list(rows)


class _NullCollection:
    def __init__(self, name: str) -> None:
        self.name = name

    def find(self, query=None):
        return []

    def find_one(self, query=None):
        return None

    def replace_one(self, query, document, upsert=False):
        return SimpleNamespace(matched_count=0, modified_count=0)

    def delete_many(self, query):
        return SimpleNamespace(deleted_count=0)

    def insert_many(self, documents, ordered=False):
        return SimpleNamespace(inserted_ids=[])

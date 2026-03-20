from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from freshquant.db import DBfreshquant

SHOUBAN30_CATEGORIES = {
    "三十涨停Pro预选",
    "三十涨停Pro自选",
    "三十涨停Pro",
}


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_symbol(symbol: Any, code: str) -> str:
    text = _to_text(symbol)
    if text:
        return text
    if len(code) == 6 and code.isdigit():
        return f"{'sh' if code.startswith('6') else 'sz'}{code}"
    return code


def _pick_earliest(left: Any, right: Any) -> Any:
    if left is None:
        return right
    if right is None:
        return left
    return right if right < left else left


def _pick_latest(left: Any, right: Any) -> Any:
    if left is None:
        return right
    if right is None:
        return left
    return right if right > left else left


def _deepcopy_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return deepcopy(value)
    return {}


def _membership_sort_key(item: dict) -> tuple[str, str]:
    return (_to_text(item.get("source")), _to_text(item.get("category")))


def _dedupe_text_list(values: list[str]) -> list[str]:
    items = sorted({_to_text(value) for value in values if _to_text(value)})
    return items


def _looks_like_unified_doc(document: dict) -> bool:
    return isinstance(document.get("memberships"), list)


def _infer_legacy_source(document: dict) -> str:
    remark = _to_text(document.get("remark"))
    category = _to_text(document.get("category"))
    extra = _deepcopy_dict(document.get("extra"))

    if remark.startswith("daily-screening:"):
        return "daily-screening"
    if category in SHOUBAN30_CATEGORIES or any(
        str(key).startswith("shouban30_") for key in extra
    ):
        return "shouban30"
    if remark:
        return remark
    return "manual"


def _infer_legacy_category(document: dict) -> str:
    category = _to_text(document.get("category"))
    extra = _deepcopy_dict(document.get("extra"))

    if category in SHOUBAN30_CATEGORIES or any(
        str(key).startswith("shouban30_") for key in extra
    ):
        plate_key = _to_text(extra.get("shouban30_plate_key"))
        if plate_key:
            return f"plate:{plate_key}"
    if category:
        return category

    remark = _to_text(document.get("remark"))
    if remark.startswith("daily-screening:"):
        return remark.split(":", 1)[1] or "daily-screening"
    return "uncategorized"


def _build_legacy_membership(document: dict) -> dict:
    extra = _deepcopy_dict(document.get("extra"))
    remark = _to_text(document.get("remark"))
    if remark:
        extra.setdefault("source_remark", remark)
    return {
        "source": _infer_legacy_source(document),
        "category": _infer_legacy_category(document),
        "added_at": document.get("updated_at") or document.get("datetime"),
        "expire_at": document.get("expire_at"),
        "extra": extra,
    }


class PrePoolService:
    def __init__(self, *, db=None) -> None:
        self.db = db or DBfreshquant
        self.collection = self.db["stock_pre_pools"]

    def upsert_code(
        self,
        *,
        code: str,
        name: str | None = None,
        symbol: str | None = None,
        source: str,
        category: str,
        added_at: Any = None,
        expire_at: Any = None,
        stop_loss_price: Any = None,
        source_remark: str | None = None,
        extra: dict | None = None,
        workspace_order: int | None = None,
    ) -> dict:
        code = _to_text(code)
        if not code:
            raise ValueError("code required")

        source = _to_text(source) or "manual"
        category = _to_text(category) or "uncategorized"

        existing = self.get_code(code) or {
            "code": code,
            "name": "",
            "symbol": _normalize_symbol(symbol, code),
            "created_at": added_at,
            "updated_at": added_at,
            "datetime": added_at,
            "expire_at": expire_at,
            "stop_loss_price": stop_loss_price,
            "sources": [],
            "categories": [],
            "memberships": [],
            "workspace_order": workspace_order,
        }

        membership_map: dict[tuple[str, str], dict] = {
            (_to_text(item.get("source")), _to_text(item.get("category"))): {
                "source": _to_text(item.get("source")),
                "category": _to_text(item.get("category")),
                "added_at": item.get("added_at"),
                "expire_at": item.get("expire_at"),
                "extra": _deepcopy_dict(item.get("extra")),
            }
            for item in existing.get("memberships") or []
        }

        membership_extra = _deepcopy_dict(extra)
        if _to_text(source_remark):
            membership_extra.setdefault("source_remark", _to_text(source_remark))

        membership_map[(source, category)] = {
            "source": source,
            "category": category,
            "added_at": added_at,
            "expire_at": expire_at,
            "extra": membership_extra,
        }

        created_at = _pick_earliest(existing.get("created_at"), added_at)
        updated_at = _pick_latest(existing.get("updated_at"), added_at)
        resolved_workspace_order = (
            workspace_order
            if workspace_order is not None
            else existing.get("workspace_order")
        )

        memberships = sorted(membership_map.values(), key=_membership_sort_key)
        document = {
            "code": code,
            "name": _to_text(name) or _to_text(existing.get("name")) or code,
            "symbol": _normalize_symbol(symbol or existing.get("symbol"), code),
            "created_at": created_at,
            "updated_at": updated_at,
            "datetime": created_at,
            "expire_at": _pick_latest(existing.get("expire_at"), expire_at),
            "stop_loss_price": (
                stop_loss_price
                if stop_loss_price is not None
                else existing.get("stop_loss_price")
            ),
            "sources": _dedupe_text_list(
                [item.get("source") for item in memberships]
            ),
            "categories": _dedupe_text_list(
                [item.get("category") for item in memberships]
            ),
            "memberships": memberships,
            "workspace_order": resolved_workspace_order,
        }
        self._replace_code_document(code, document)
        return deepcopy(document)

    def list_codes(
        self,
        *,
        source: str | None = None,
        category: str | None = None,
        code: str | None = None,
    ) -> list[dict]:
        rows = self._load_all_rows()
        grouped: dict[str, dict] = {}

        for raw_row in rows:
            code_key = _to_text(raw_row.get("code"))
            if not code_key:
                continue
            group = grouped.setdefault(
                code_key,
                {
                    "code": code_key,
                    "name": "",
                    "symbol": _normalize_symbol(raw_row.get("symbol"), code_key),
                    "created_at": None,
                    "updated_at": None,
                    "datetime": None,
                    "expire_at": None,
                    "stop_loss_price": None,
                    "workspace_order": None,
                    "_memberships": {},
                },
            )
            self._merge_row_into_group(group, raw_row)

        items = [self._finalize_group(group) for group in grouped.values()]
        if code:
            items = [item for item in items if item.get("code") == _to_text(code)]
        if source:
            items = [
                item
                for item in items
                if _to_text(source) in set(item.get("sources") or [])
            ]
        if category:
            items = [
                item
                for item in items
                if _to_text(category) in set(item.get("categories") or [])
            ]
        return sorted(items, key=self._list_sort_key)

    def get_code(self, code: str) -> dict | None:
        rows = self.list_codes(code=code)
        return deepcopy(rows[0]) if rows else None

    def delete_code(self, code: str) -> bool:
        code = _to_text(code)
        if not code:
            return False
        if hasattr(self.collection, "delete_many"):
            result = self.collection.delete_many({"code": code})
            return bool(getattr(result, "deleted_count", 0))
        if hasattr(self.collection, "delete_one"):
            result = self.collection.delete_one({"code": code})
            return bool(getattr(result, "deleted_count", 0))
        return False

    def _load_all_rows(self) -> list[dict]:
        rows = self.collection.find({})
        return [deepcopy(dict(row)) for row in list(rows)]

    def _replace_code_document(self, code: str, document: dict) -> None:
        if hasattr(self.collection, "delete_many") and hasattr(self.collection, "insert_one"):
            self.collection.delete_many({"code": code})
            self.collection.insert_one(document)
            return
        if hasattr(self.collection, "replace_one"):
            self.collection.replace_one({"code": code}, document, upsert=True)
            return
        raise RuntimeError("stock_pre_pools collection does not support save operations")

    def _merge_row_into_group(self, group: dict, raw_row: dict) -> None:
        group["name"] = _to_text(raw_row.get("name")) or group["name"] or group["code"]
        group["symbol"] = _normalize_symbol(
            raw_row.get("symbol") or group.get("symbol"), group["code"]
        )
        group["created_at"] = _pick_earliest(
            group.get("created_at"),
            raw_row.get("created_at") or raw_row.get("datetime"),
        )
        group["updated_at"] = _pick_latest(
            group.get("updated_at"),
            raw_row.get("updated_at") or raw_row.get("datetime"),
        )
        group["expire_at"] = _pick_latest(group.get("expire_at"), raw_row.get("expire_at"))
        if raw_row.get("stop_loss_price") is not None:
            group["stop_loss_price"] = raw_row.get("stop_loss_price")

        workspace_order = raw_row.get("workspace_order")
        if workspace_order is None:
            workspace_order = _deepcopy_dict(raw_row.get("extra")).get("shouban30_order")
        if workspace_order is not None and (
            group.get("workspace_order") is None
            or workspace_order < group.get("workspace_order")
        ):
            group["workspace_order"] = workspace_order

        memberships = (
            raw_row.get("memberships")
            if _looks_like_unified_doc(raw_row)
            else [_build_legacy_membership(raw_row)]
        )
        for membership in memberships:
            normalized = {
                "source": _to_text(membership.get("source")) or "manual",
                "category": _to_text(membership.get("category")) or "uncategorized",
                "added_at": membership.get("added_at"),
                "expire_at": membership.get("expire_at"),
                "extra": _deepcopy_dict(membership.get("extra")),
            }
            key = (normalized["source"], normalized["category"])
            current = group["_memberships"].get(key)
            if current is None or _pick_latest(current.get("added_at"), normalized.get("added_at")) == normalized.get("added_at"):
                group["_memberships"][key] = normalized

    def _finalize_group(self, group: dict) -> dict:
        memberships = sorted(group.pop("_memberships").values(), key=_membership_sort_key)
        created_at = group.get("created_at")
        updated_at = group.get("updated_at")
        return {
            "code": group["code"],
            "name": group.get("name") or group["code"],
            "symbol": _normalize_symbol(group.get("symbol"), group["code"]),
            "created_at": created_at,
            "updated_at": updated_at,
            "datetime": created_at,
            "expire_at": group.get("expire_at"),
            "stop_loss_price": group.get("stop_loss_price"),
            "sources": _dedupe_text_list([item.get("source") for item in memberships]),
            "categories": _dedupe_text_list([item.get("category") for item in memberships]),
            "memberships": memberships,
            "workspace_order": group.get("workspace_order"),
        }

    def _list_sort_key(self, item: dict) -> tuple[int, Any, str]:
        workspace_order = item.get("workspace_order")
        if workspace_order is None:
            return (1, item.get("updated_at") or item.get("created_at") or datetime.min, item["code"])
        return (0, workspace_order, item["code"])

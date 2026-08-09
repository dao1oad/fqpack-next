from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Iterable

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


def _dedupe_text_list(values: Iterable[Any]) -> list[str]:
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
        self.db = DBfreshquant if db is None else db
        self.collection = self.db["stock_pre_pools"]

    def reconcile_clx_trade_date(
        self,
        *,
        trade_date: str,
        target_codes: Iterable[str],
        asset_type_by_code: dict[str, str] | None = None,
        batch_id: str = "",
        publication_id: str = "",
        content_hash: str = "",
        selection_key: str = "",
        added_at: Any = None,
        now: Any = None,
    ) -> dict:
        """按 ready generation 对当前交易日的 CLX membership 做幂等对账。

        - 同一 code、同一交易日最多保留一个 CLX membership
          （source=clx_daily_selection, category=trade_date:YYYY-MM-DD）；
        - 同日发布新 generation 时替换该交易日的 CLX membership；
        - 旧 generation 命中但当前不再命中的 CLX membership 被移除；
        - code 的其他来源 membership 不受影响；
        - 无剩余 membership 时删除顶层文档。
        """
        trade_date = _to_text(trade_date)
        if not trade_date:
            raise ValueError("trade_date required")
        category = f"trade_date:{trade_date}"
        now = now if now is not None else datetime.now()
        added_at = added_at if added_at is not None else now
        asset_type_by_code = asset_type_by_code or {}
        target_set = {_to_text(code) for code in target_codes if _to_text(code)}
        extra = {
            "batch_id": _to_text(batch_id),
            "publication_id": _to_text(publication_id),
            "content_hash": _to_text(content_hash),
            "selection_key": _to_text(selection_key),
            "direction_mode": "pure_buy",
        }

        added = 0
        updated = 0
        unchanged = 0
        for code in sorted(target_set):
            existing = self.get_code(code) or {}
            membership = next(
                (
                    item
                    for item in (existing.get("memberships") or [])
                    if _to_text(item.get("source")) == "clx_daily_selection"
                    and _to_text(item.get("category")) == category
                ),
                None,
            )
            row_extra = _deepcopy_dict(membership.get("extra")) if membership else {}
            same_generation = (
                membership is not None
                and row_extra.get("batch_id") == extra["batch_id"]
                and row_extra.get("publication_id") == extra["publication_id"]
                and row_extra.get("content_hash") == extra["content_hash"]
            )
            membership_extra = dict(extra)
            asset_type = _to_text(asset_type_by_code.get(code))
            if asset_type:
                membership_extra["asset_type"] = asset_type
            self.upsert_code(
                code=code,
                name=(existing or {}).get("name"),
                symbol=(existing or {}).get("symbol"),
                source="clx_daily_selection",
                category=category,
                added_at=added_at,
                extra=membership_extra,
            )
            if same_generation:
                unchanged += 1
            elif membership is not None:
                updated += 1
            else:
                added += 1

        removed = 0
        for row in self.list_codes(source="clx_daily_selection"):
            code = _to_text(row.get("code"))
            if not code or code in target_set:
                continue
            has_membership = any(
                _to_text(item.get("source")) == "clx_daily_selection"
                and _to_text(item.get("category")) == category
                for item in (row.get("memberships") or [])
            )
            if has_membership and self.remove_membership(
                code=code, source="clx_daily_selection", category=category
            ):
                removed += 1

        return {
            "trade_date": trade_date,
            "category": category,
            "target_count": len(target_set),
            "added": added,
            "updated": updated,
            "unchanged": unchanged,
            "removed": removed,
        }

    def purge_expired_memberships(self, now: Any = None) -> dict:
        """清理已过期 membership，重算顶层派生字段，无有效 membership 时删除顶层文档。"""
        now = now if now is not None else datetime.now()
        removed_memberships = 0
        removed_docs = 0
        refreshed_docs = 0
        for row in self._load_all_rows():
            code = _to_text(row.get("code"))
            if not code or not _looks_like_unified_doc(row):
                continue
            remaining = []
            for item in row.get("memberships") or []:
                expire_at = item.get("expire_at")
                if expire_at is not None and expire_at < now:
                    removed_memberships += 1
                    continue
                remaining.append(
                    {
                        "source": _to_text(item.get("source")) or "manual",
                        "category": _to_text(item.get("category")) or "uncategorized",
                        "added_at": item.get("added_at"),
                        "expire_at": item.get("expire_at"),
                        "extra": _deepcopy_dict(item.get("extra")),
                    }
                )
            if not remaining:
                if self.delete_code(code):
                    removed_docs += 1
                continue
            if len(remaining) == len(row.get("memberships") or []):
                continue
            document = deepcopy(row)
            document["memberships"] = sorted(remaining, key=_membership_sort_key)
            document["sources"] = _dedupe_text_list(
                [item.get("source") for item in document["memberships"]]
            )
            document["categories"] = _dedupe_text_list(
                [item.get("category") for item in document["memberships"]]
            )
            remaining_expire_at = [
                item.get("expire_at") for item in document["memberships"]
            ]
            if remaining_expire_at:
                resolved_expire_at = remaining_expire_at[0]
                for candidate in remaining_expire_at[1:]:
                    resolved_expire_at = _pick_latest(resolved_expire_at, candidate)
            else:
                resolved_expire_at = None
            document["expire_at"] = resolved_expire_at
            self._replace_code_document(code, document)
            refreshed_docs += 1
        return {
            "removed_memberships": removed_memberships,
            "removed_docs": removed_docs,
            "refreshed_docs": refreshed_docs,
        }

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
        row_category: str | None = None,
        row_remark: str | None = None,
        row_extra: dict | None = None,
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
            "category": _to_text(row_category),
            "remark": _to_text(row_remark),
            "extra": _deepcopy_dict(row_extra),
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
            "category": _to_text(row_category) or _to_text(existing.get("category")),
            "remark": _to_text(row_remark) or _to_text(existing.get("remark")),
            "extra": _deepcopy_dict(row_extra) or _deepcopy_dict(existing.get("extra")),
            "sources": _dedupe_text_list([item.get("source") for item in memberships]),
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

    def remove_membership(
        self, *, code: str, source: str, category: str | None = None
    ) -> bool:
        code = _to_text(code)
        source = _to_text(source)
        category = _to_text(category)
        if not code or not source:
            return False
        row = self.get_code(code)
        if row is None:
            return False

        remaining = []
        removed = False
        for item in row.get("memberships") or []:
            same_source = _to_text(item.get("source")) == source
            same_category = not category or _to_text(item.get("category")) == category
            if same_source and same_category:
                removed = True
                continue
            remaining.append(
                {
                    "source": _to_text(item.get("source")) or "manual",
                    "category": _to_text(item.get("category")) or "uncategorized",
                    "added_at": item.get("added_at"),
                    "expire_at": item.get("expire_at"),
                    "extra": _deepcopy_dict(item.get("extra")),
                }
            )

        if not removed:
            return False
        if not remaining:
            return self.delete_code(code)

        document = deepcopy(row)
        document["memberships"] = sorted(remaining, key=_membership_sort_key)
        document["sources"] = _dedupe_text_list(
            [item.get("source") for item in document["memberships"]]
        )
        document["categories"] = _dedupe_text_list(
            [item.get("category") for item in document["memberships"]]
        )
        if source == "shouban30":
            document["workspace_order"] = self._workspace_order_from_memberships(
                document["memberships"]
            )
        self._replace_code_document(code, document)
        return True

    def _load_all_rows(self) -> list[dict]:
        rows = self.collection.find({})
        return [deepcopy(dict(row)) for row in list(rows)]

    def _replace_code_document(self, code: str, document: dict) -> None:
        if hasattr(self.collection, "delete_many") and hasattr(
            self.collection, "insert_one"
        ):
            self.collection.delete_many({"code": code})
            self.collection.insert_one(document)
            return
        if hasattr(self.collection, "replace_one"):
            self.collection.replace_one({"code": code}, document, upsert=True)
            return
        raise RuntimeError(
            "stock_pre_pools collection does not support save operations"
        )

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
        group["expire_at"] = _pick_latest(
            group.get("expire_at"), raw_row.get("expire_at")
        )
        if raw_row.get("stop_loss_price") is not None:
            group["stop_loss_price"] = raw_row.get("stop_loss_price")

        workspace_order = raw_row.get("workspace_order")
        if workspace_order is None:
            workspace_order = _deepcopy_dict(raw_row.get("extra")).get(
                "shouban30_order"
            )
        if workspace_order is not None and (
            group.get("workspace_order") is None
            or workspace_order < group.get("workspace_order")
        ):
            group["workspace_order"] = workspace_order

        raw_memberships = raw_row.get("memberships")
        memberships = (
            raw_memberships
            if _looks_like_unified_doc(raw_row) and isinstance(raw_memberships, list)
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
            if current is None or _pick_latest(
                current.get("added_at"), normalized.get("added_at")
            ) == normalized.get("added_at"):
                group["_memberships"][key] = normalized

    def _finalize_group(self, group: dict) -> dict:
        memberships = sorted(
            group.pop("_memberships").values(), key=_membership_sort_key
        )
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
            "categories": _dedupe_text_list(
                [item.get("category") for item in memberships]
            ),
            "memberships": memberships,
            "workspace_order": group.get("workspace_order"),
        }

    def _list_sort_key(self, item: dict) -> tuple[int, Any, str]:
        workspace_order = item.get("workspace_order")
        if workspace_order is None:
            return (
                1,
                item.get("updated_at") or item.get("created_at") or datetime.min,
                item["code"],
            )
        return (0, workspace_order, item["code"])

    def _workspace_order_from_memberships(self, memberships: list[dict]) -> int | None:
        orders = []
        for membership in memberships:
            value = _deepcopy_dict(membership.get("extra")).get("shouban30_order")
            if value is None:
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed >= 0:
                orders.append(parsed)
        return min(orders) if orders else None

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError

from freshquant.config import cfg
from freshquant.data.trade_date_hist import tool_trade_date_hist_sina
from freshquant.db import DBfreshquant

COL_POSTCLOSE_MARKERS = "dagster_pipeline_markers"
POSTCLOSE_CUTOFF_HOUR = 15
POSTCLOSE_CUTOFF_MINUTE = 5


class StalePostclosePublicationError(RuntimeError):
    code = "stale_publication"

    def __init__(self, incoming: dict[str, Any], current: dict[str, Any]) -> None:
        self.incoming_publication_id = str(incoming.get("publication_id") or "")
        self.current_publication_id = str(current.get("publication_id") or "")
        super().__init__(
            "postclose marker stale-publication rejected: "
            f"incoming={self.incoming_publication_id}, "
            f"current={self.current_publication_id}"
        )


def _get_marker_collection(collection=None):
    if collection is not None:
        return collection
    return DBfreshquant[COL_POSTCLOSE_MARKERS]


def _ensure_marker_indexes(collection) -> None:
    collection.create_index(
        [("pipeline_key", 1), ("trade_date", 1)],
        unique=True,
        name="uniq_pipeline_trade_date",
    )


def _normalize_marker(
    pipeline_key: str,
    trade_date: str,
    *,
    status: str = "success",
    run_id: str | None = None,
    payload: dict[str, Any] | None = None,
    generation_id: str | None = None,
    generation_order: str | None = None,
    publication_id: str | None = None,
    now_provider=None,
) -> dict[str, Any]:
    now_provider = now_provider or (lambda: datetime.now(timezone.utc))
    marker = {
        "pipeline_key": str(pipeline_key or "").strip(),
        "trade_date": str(trade_date or "").strip(),
        "status": str(status or "").strip() or "success",
        "updated_at": now_provider().isoformat(),
        "run_id": str(run_id or "").strip(),
        "payload": dict(payload or {}),
    }
    if any((generation_id, generation_order, publication_id)):
        marker.update(
            {
                "generation_id": str(generation_id or "").strip(),
                "generation_order": str(generation_order or "").strip(),
                "publication_id": str(publication_id or "").strip(),
            }
        )
        if not all(
            marker[key]
            for key in ("generation_id", "generation_order", "publication_id")
        ):
            raise ValueError("generation publication identity must be complete")
    return marker


def resolve_latest_completed_trade_date(
    *,
    now_provider=None,
    trade_dates_provider=None,
) -> str:
    return resolve_recent_completed_trade_dates(
        limit=1,
        now_provider=now_provider,
        trade_dates_provider=trade_dates_provider,
    )[0]


def resolve_recent_completed_trade_dates(
    *,
    limit: int = 5,
    now_provider=None,
    trade_dates_provider=None,
) -> list[str]:
    limit = int(limit)
    if limit < 1:
        raise ValueError("trade date limit must be positive")
    trade_dates_provider = trade_dates_provider or tool_trade_date_hist_sina
    trade_dates = {
        _as_trade_date(value) for value in trade_dates_provider()["trade_date"]
    }
    if not trade_dates:
        raise RuntimeError("no trade dates available")

    now = now_provider() if callable(now_provider) else datetime.now(cfg.TZ)
    if now.tzinfo is None:
        localize = getattr(cfg.TZ, "localize", None)
        now = localize(now) if callable(localize) else now.replace(tzinfo=cfg.TZ)
    else:
        now = now.astimezone(cfg.TZ)
    today = now.date()
    cutoff = now.replace(
        hour=POSTCLOSE_CUTOFF_HOUR,
        minute=POSTCLOSE_CUTOFF_MINUTE,
        second=0,
        microsecond=0,
    )
    completed = sorted(
        (
            trade_date
            for trade_date in trade_dates
            if trade_date < today or (trade_date == today and now >= cutoff)
        ),
        reverse=True,
    )
    if not completed:
        raise RuntimeError("no completed trade date available")
    return [trade_date.strftime("%Y-%m-%d") for trade_date in completed[:limit]]


def _as_trade_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def upsert_postclose_marker(
    pipeline_key: str,
    trade_date: str,
    *,
    status: str = "success",
    run_id: str | None = None,
    payload: dict[str, Any] | None = None,
    generation_id: str | None = None,
    generation_order: str | None = None,
    publication_id: str | None = None,
    collection=None,
    now_provider=None,
) -> dict[str, Any]:
    target_collection = _get_marker_collection(collection)
    _ensure_marker_indexes(target_collection)
    marker = _normalize_marker(
        pipeline_key,
        trade_date,
        status=status,
        run_id=run_id,
        payload=payload,
        generation_id=generation_id,
        generation_order=generation_order,
        publication_id=publication_id,
        now_provider=now_provider,
    )
    if marker.get("publication_id"):
        return _publish_generation_marker(target_collection, marker)
    target_collection.update_one(
        {
            "pipeline_key": marker["pipeline_key"],
            "trade_date": marker["trade_date"],
        },
        {"$set": marker},
        upsert=True,
    )
    return marker


def _publish_generation_marker(collection, marker: dict[str, Any]) -> dict[str, Any]:
    identity = {
        "pipeline_key": marker["pipeline_key"],
        "trade_date": marker["trade_date"],
    }
    for _attempt in range(4):
        existing = collection.find_one(identity)
        if existing:
            if existing.get("publication_id") == marker["publication_id"]:
                return existing
            if (
                str(existing.get("generation_order") or "")
                >= marker["generation_order"]
            ):
                raise StalePostclosePublicationError(marker, existing)
            query = {
                **identity,
                "publication_id": existing.get("publication_id"),
                "generation_order": existing.get("generation_order"),
            }
            result = collection.update_one(query, {"$set": marker})
            if getattr(result, "matched_count", 0):
                return marker
            continue
        try:
            result = collection.update_one(
                {
                    **identity,
                    "publication_id": {"$exists": False},
                },
                {"$set": marker},
                upsert=True,
            )
        except DuplicateKeyError:
            continue
        if getattr(result, "upserted_id", None) is not None or getattr(
            result, "matched_count", 0
        ):
            return marker
    current = collection.find_one(identity)
    if current:
        if current.get("publication_id") == marker["publication_id"]:
            return current
        if str(current.get("generation_order") or "") >= marker["generation_order"]:
            raise StalePostclosePublicationError(marker, current)
    raise RuntimeError("postclose marker generation CAS did not converge")


def get_postclose_marker(pipeline_key: str, trade_date: str, *, collection=None):
    target_collection = _get_marker_collection(collection)
    return target_collection.find_one(
        {
            "pipeline_key": str(pipeline_key or "").strip(),
            "trade_date": str(trade_date or "").strip(),
        }
    )


def has_success_postclose_marker(
    pipeline_key: str,
    trade_date: str,
    *,
    collection=None,
) -> bool:
    marker = get_postclose_marker(pipeline_key, trade_date, collection=collection)
    return bool(marker) and str(marker.get("status") or "").strip() == "success"


def delete_postclose_marker(pipeline_key: str, trade_date: str, *, collection=None):
    target_collection = _get_marker_collection(collection)
    target_collection.delete_many(
        {
            "pipeline_key": str(pipeline_key or "").strip(),
            "trade_date": str(trade_date or "").strip(),
        }
    )

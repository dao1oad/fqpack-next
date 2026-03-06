# -*- coding: utf-8 -*-

from datetime import datetime, timezone

from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.tracking.service import OrderTrackingService


def prepare_submit_execution(order_message, repository=None, tracking_service=None):
    repository = repository or OrderManagementRepository()
    tracking_service = tracking_service or OrderTrackingService(repository=repository)
    internal_order_id = order_message.get("internal_order_id")
    if not internal_order_id:
        return {"status": "passthrough"}

    order = repository.find_order(internal_order_id)
    if order is None:
        return {"status": "missing_order"}
    if order["state"] in {"CANCEL_REQUESTED", "CANCELED"}:
        tracking_service.ingest_order_report(
            {
                "internal_order_id": internal_order_id,
                "state": "CANCELED",
                "event_type": "canceled_before_submit",
                "broker_order_id": order.get("broker_order_id"),
            }
        )
        return {"status": "skipped", "reason": "already_canceled"}

    tracking_service.ingest_order_report(
        {
            "internal_order_id": internal_order_id,
            "state": "SUBMITTING",
            "event_type": "submit_started",
            "broker_order_id": order.get("broker_order_id"),
        }
    )
    return {"status": "execute"}


def finalize_submit_execution(
    order_message,
    broker_order_id,
    repository=None,
    tracking_service=None,
):
    repository = repository or OrderManagementRepository()
    tracking_service = tracking_service or OrderTrackingService(repository=repository)
    internal_order_id = order_message.get("internal_order_id")
    if not internal_order_id:
        return None

    if broker_order_id is None or int(broker_order_id) <= 0:
        tracking_service.ingest_order_report(
            {
                "internal_order_id": internal_order_id,
                "state": "FAILED",
                "event_type": "submit_failed",
                "broker_order_id": None,
            }
        )
        return {"status": "failed"}

    tracking_service.ingest_order_report(
        {
            "internal_order_id": internal_order_id,
            "state": "SUBMITTED",
            "event_type": "submitted",
            "broker_order_id": str(broker_order_id),
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {"status": "submitted", "broker_order_id": str(broker_order_id)}


def dispatch_cancel_execution(
    order_message,
    cancel_executor,
    repository=None,
    tracking_service=None,
):
    repository = repository or OrderManagementRepository()
    tracking_service = tracking_service or OrderTrackingService(repository=repository)
    internal_order_id = order_message.get("internal_order_id")
    broker_order_id = order_message.get("broker_order_id")
    order = repository.find_order(internal_order_id) if internal_order_id else None
    if order is not None and order["state"] == "CANCELED":
        return {"status": "already_canceled"}
    if broker_order_id is None and order is not None:
        broker_order_id = order.get("broker_order_id")

    if broker_order_id in (None, "", "None"):
        if internal_order_id:
            tracking_service.ingest_order_report(
                {
                    "internal_order_id": internal_order_id,
                    "state": "CANCELED",
                    "event_type": "canceled_before_submit",
                    "broker_order_id": None,
                }
            )
        return {"status": "canceled_before_submit"}

    cancel_result = cancel_executor(int(broker_order_id))
    if cancel_result == 0:
        return {"status": "cancel_submitted", "broker_order_id": str(broker_order_id)}

    if internal_order_id:
        tracking_service.ingest_order_report(
            {
                "internal_order_id": internal_order_id,
                "state": "FAILED",
                "event_type": "cancel_failed",
                "broker_order_id": str(broker_order_id),
            }
        )
    return {"status": "cancel_failed", "broker_order_id": str(broker_order_id)}

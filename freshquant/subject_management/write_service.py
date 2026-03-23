# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime

from freshquant.util.code import normalize_to_base_code


class SubjectManagementWriteService:
    def __init__(self, *, database=None, guardian_service=None):
        if database is None:
            from freshquant.db import DBfreshquant

            database = DBfreshquant
        self.database = database
        self.guardian_service = guardian_service

    def update_must_pool(self, symbol, payload):
        normalized_symbol = _require_symbol(symbol)
        category = str(payload.get("category") or "").strip()
        if not category:
            raise ValueError("category is required")

        stop_loss_price = _require_positive_float(
            payload.get("stop_loss_price"),
            "stop_loss_price",
        )
        initial_lot_amount = _require_non_negative_int(
            payload.get("initial_lot_amount"),
            "initial_lot_amount",
        )
        lot_amount = _require_non_negative_int(payload.get("lot_amount"), "lot_amount")
        forever = True
        updated_by = str(payload.get("updated_by") or "api")

        from freshquant.instrument.general import query_instrument_info

        instrument = query_instrument_info(normalized_symbol)
        if not instrument:
            raise ValueError("symbol not found")

        now = datetime.now()
        document = {
            "code": normalized_symbol,
            "name": str(instrument.get("name") or "").strip(),
            "instrument_type": instrument.get("sec"),
            "category": category,
            "stop_loss_price": stop_loss_price,
            "initial_lot_amount": initial_lot_amount,
            "lot_amount": lot_amount,
            "forever": forever,
            "disabled": False,
            "updated_at": now,
            "updated_by": updated_by,
        }
        self.database["must_pool"].update_one(
            {"code": normalized_symbol},
            {"$set": document, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        return {
            "symbol": normalized_symbol,
            "name": document["name"],
            "category": category,
            "stop_loss_price": stop_loss_price,
            "initial_lot_amount": initial_lot_amount,
            "lot_amount": lot_amount,
            "forever": forever,
        }

    def update_guardian_buy_grid(self, symbol, payload):
        normalized_symbol = _require_symbol(symbol)
        guardian_service = self._guardian_service()
        detail = guardian_service.upsert_config(
            normalized_symbol,
            buy_1=_optional_float(payload.get("buy_1"), "buy_1"),
            buy_2=_optional_float(payload.get("buy_2"), "buy_2"),
            buy_3=_optional_float(payload.get("buy_3"), "buy_3"),
            buy_enabled=_optional_bool_list(payload.get("buy_enabled"), "buy_enabled"),
            enabled=_optional_bool(payload.get("enabled")),
            updated_by=str(payload.get("updated_by") or "api"),
        )
        return {
            "symbol": normalized_symbol,
            "enabled": bool(detail.get("enabled", True)),
            "buy_1": _optional_float(detail.get("BUY-1"), "BUY-1"),
            "buy_2": _optional_float(detail.get("BUY-2"), "BUY-2"),
            "buy_3": _optional_float(detail.get("BUY-3"), "BUY-3"),
            "buy_enabled": _optional_bool_list(
                detail.get("buy_enabled"), "buy_enabled"
            ),
        }

    def _guardian_service(self):
        if self.guardian_service is None:
            from freshquant.strategy.guardian_buy_grid import GuardianBuyGridService

            self.guardian_service = GuardianBuyGridService()
        return self.guardian_service


def _require_symbol(value):
    normalized = normalize_to_base_code(str(value or ""))
    if not normalized:
        raise ValueError("symbol is required")
    return normalized


def _require_positive_float(value, field_name):
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be numeric") from error
    if number <= 0:
        raise ValueError(f"{field_name} must be greater than 0")
    return number


def _require_non_negative_int(value, field_name):
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be integer")

    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"{field_name} must be integer")
        number = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text or not text.lstrip("+-").isdigit():
            raise ValueError(f"{field_name} must be integer")
        number = int(text)
    else:
        raise ValueError(f"{field_name} must be integer")

    if number < 0:
        raise ValueError(f"{field_name} must be greater than or equal to 0")
    return number


def _optional_float(value, field_name):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be numeric") from error


def _optional_bool(value):
    if value is None:
        return None
    return bool(value)


def _optional_bool_list(value, field_name):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{field_name} must be a 3-item boolean list")
    return [bool(value[0]), bool(value[1]), bool(value[2])]

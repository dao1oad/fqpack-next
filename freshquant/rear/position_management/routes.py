# -*- coding: utf-8 -*-

from flask import Blueprint, jsonify, request

position_management_bp = Blueprint(
    "position_management",
    __name__,
    url_prefix="/api/position-management",
)


def _get_position_management_dashboard_service():
    from freshquant.position_management.dashboard_service import (
        PositionManagementDashboardService,
    )

    return PositionManagementDashboardService()


def _get_position_reconciliation_read_service():
    from freshquant.position_management.reconciliation_read_service import (
        PositionReconciliationReadService,
    )

    return PositionReconciliationReadService()


@position_management_bp.get("/dashboard")
def get_dashboard():
    return jsonify(_get_position_management_dashboard_service().get_dashboard())


@position_management_bp.get("/config")
def get_config():
    return jsonify(_get_position_management_dashboard_service().get_config())


@position_management_bp.post("/config")
def update_config():
    payload = request.get_json(silent=True) or {}
    try:
        result = _get_position_management_dashboard_service().update_config(payload)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(result)


@position_management_bp.get("/symbol-limits")
def get_symbol_limits():
    return jsonify(_get_position_management_dashboard_service().get_symbol_limits())


@position_management_bp.get("/symbol-limits/<symbol>")
def get_symbol_limit(symbol):
    try:
        return jsonify(
            _get_position_management_dashboard_service().get_symbol_limit(symbol)
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@position_management_bp.get("/reconciliation")
def get_reconciliation_overview():
    return jsonify(_get_position_reconciliation_read_service().get_overview())


@position_management_bp.get("/reconciliation/<symbol>")
def get_reconciliation_detail(symbol):
    try:
        return jsonify(
            _get_position_reconciliation_read_service().get_symbol_detail(symbol)
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@position_management_bp.get("/reconciliation-workspace/<symbol>")
def get_reconciliation_workspace(symbol):
    try:
        return jsonify(
            _get_position_reconciliation_read_service().get_symbol_workspace(symbol)
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@position_management_bp.post("/symbol-limits/<symbol>")
def update_symbol_limit(symbol):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(
            _get_position_management_dashboard_service().update_symbol_limit(
                symbol, payload
            )
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

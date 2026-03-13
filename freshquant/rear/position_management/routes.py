# -*- coding: utf-8 -*-

from flask import Blueprint, jsonify, request

from freshquant.position_management.dashboard_service import (
    PositionManagementDashboardService,
)

position_management_bp = Blueprint(
    "position_management",
    __name__,
    url_prefix="/api/position-management",
)


def _get_position_management_dashboard_service():
    return PositionManagementDashboardService()


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

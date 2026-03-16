# -*- coding: utf-8 -*-

from flask import Blueprint, jsonify, request

from freshquant.subject_management.dashboard_service import (
    SubjectManagementDashboardService,
)
from freshquant.subject_management.write_service import SubjectManagementWriteService

subject_management_bp = Blueprint(
    "subject_management",
    __name__,
    url_prefix="/api/subject-management",
)


def _get_dashboard_service():
    return SubjectManagementDashboardService()


def _get_write_service():
    return SubjectManagementWriteService()


@subject_management_bp.route("/overview", methods=["GET"])
def get_subject_management_overview():
    return jsonify({"rows": _get_dashboard_service().get_overview()})


@subject_management_bp.route("/<symbol>", methods=["GET"])
def get_subject_management_detail(symbol):
    try:
        return jsonify(_get_dashboard_service().get_detail(symbol))
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@subject_management_bp.route("/<symbol>/must-pool", methods=["POST"])
def update_subject_must_pool(symbol):
    payload = request.get_json(silent=True) or {}
    try:
        detail = _get_write_service().update_must_pool(symbol, payload)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(detail)


@subject_management_bp.route("/<symbol>/guardian-buy-grid", methods=["POST"])
def update_subject_guardian_buy_grid(symbol):
    payload = request.get_json(silent=True) or {}
    try:
        detail = _get_write_service().update_guardian_buy_grid(symbol, payload)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(detail)

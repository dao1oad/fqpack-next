# -*- coding: utf-8 -*-

from flask import Blueprint, jsonify, request

from freshquant.system_config_service import SystemConfigService

system_config_bp = Blueprint(
    "system_config",
    __name__,
    url_prefix="/api/system-config",
)


def _get_system_config_service():
    return SystemConfigService()


@system_config_bp.get("/dashboard")
def get_dashboard():
    return jsonify(_get_system_config_service().get_dashboard())


@system_config_bp.post("/bootstrap")
def update_bootstrap():
    payload = request.get_json(silent=True) or {}
    try:
        result = _get_system_config_service().update_bootstrap(payload)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(result)


@system_config_bp.post("/settings")
def update_settings():
    payload = request.get_json(silent=True) or {}
    try:
        result = _get_system_config_service().update_settings(payload)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(result)

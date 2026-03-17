# -*- coding: utf-8 -*-

from datetime import datetime
from types import SimpleNamespace

import pytest

from freshquant.position_management.models import ALLOW_OPEN, HOLDING_ONLY
from freshquant.position_management.snapshot_service import PositionSnapshotService


class FakeRepository:
    def __init__(self):
        self.config_doc = None
        self.current_state_doc = None
        self.snapshot_doc = None
        self.upserted_config = None
        self.snapshots = []
        self.decision_docs = []

    def get_config(self):
        return self.config_doc

    def upsert_config(self, document):
        self.upserted_config = dict(document)
        self.config_doc = dict(document)
        return self.config_doc

    def get_current_state(self, account_id=None):
        return self.current_state_doc

    def get_snapshot(self, snapshot_id):
        if self.snapshot_doc and self.snapshot_doc.get("snapshot_id") == snapshot_id:
            return self.snapshot_doc
        return None

    def get_latest_snapshot(self):
        return self.snapshot_doc

    def insert_snapshot(self, document):
        self.snapshots.append(document)
        self.snapshot_doc = dict(document)
        return document

    def upsert_current_state(self, document):
        self.current_state_doc = dict(document)
        return document

    def list_recent_decisions(self, limit=10):
        return list(self.decision_docs[:limit])


class SuccessfulCreditClient:
    account_id = "1208970161"
    account_type = "CREDIT"

    def query_credit_detail(self):
        return [
            {
                "m_dEnableBailBalance": 865432.12,
                "m_dAvailable": 102345.67,
                "m_dFetchBalance": 92345.67,
                "m_dBalance": 1432100.0,
                "m_dMarketValue": 1210000.0,
                "m_dTotalDebt": 530000.0,
            }
        ]


def _fixed_now():
    return datetime.fromisoformat("2026-03-07T12:00:20+08:00")


def _system_settings_provider():
    return SimpleNamespace(
        xtquant=SimpleNamespace(
            path="D:/miniqmt/userdata_mini",
            account="1208970161",
            account_type="CREDIT",
            broker_submit_mode="observe_only",
        )
    )


def test_dashboard_surfaces_effective_state_holding_scope_and_rule_matrix():
    from freshquant.position_management.dashboard_service import (
        PositionManagementDashboardService,
    )

    repository = FakeRepository()
    repository.config_doc = {
        "code": "default",
        "enabled": True,
        "thresholds": {
            "allow_open_min_bail": 800000.0,
            "holding_only_min_bail": 100000.0,
            "single_symbol_position_limit": 800000.0,
        },
        "updated_at": "2026-03-07T11:59:00+08:00",
        "updated_by": "pytest",
    }
    repository.current_state_doc = {
        "account_id": "1208970161",
        "state": ALLOW_OPEN,
        "available_bail_balance": 865432.12,
        "snapshot_id": "pms_1",
        "data_source": "xtquant",
        "evaluated_at": "2026-03-07T12:00:00+08:00",
        "last_query_ok": "2026-03-07T12:00:00+08:00",
    }
    repository.snapshot_doc = {
        "snapshot_id": "pms_1",
        "available_amount": 102345.67,
        "fetch_balance": 92345.67,
        "total_asset": 1432100.0,
        "market_value": 1210000.0,
        "total_debt": 530000.0,
        "source": "xtquant",
    }
    repository.decision_docs = [
        {
            "strategy_name": "Guardian",
            "action": "buy",
            "symbol": "000001",
            "state": HOLDING_ONLY,
            "allowed": True,
            "reason_code": "holding_buy_allowed",
            "reason_text": "当前状态允许买入已持仓标的",
            "evaluated_at": "2026-03-07T12:00:00+08:00",
            "meta": {
                "symbol_name": "平安银行",
            },
        }
    ]

    service = PositionManagementDashboardService(
        repository=repository,
        holding_codes_provider=lambda: ["000001", "600000"],
        settings_provider=_system_settings_provider(),
        now_provider=_fixed_now,
    )

    payload = service.get_dashboard()
    rules = {item["key"]: item for item in payload["rule_matrix"]}
    inventory = {item["key"]: item for item in payload["config"]["inventory"]}

    assert payload["state"]["raw_state"] == ALLOW_OPEN
    assert payload["state"]["effective_state"] == HOLDING_ONLY
    assert payload["state"]["stale"] is True
    assert payload["state"]["matched_rule"]["code"] == "stale_default_state"
    assert payload["holding_scope"]["codes"] == ["000001", "600000"]
    assert rules["buy_new"]["allowed"] is False
    assert rules["buy_holding"]["allowed"] is True
    assert rules["sell"]["allowed"] is True
    assert inventory["allow_open_min_bail"]["editable"] is True
    assert inventory["single_symbol_position_limit"]["editable"] is True
    assert inventory["single_symbol_position_limit"]["value"] == 800000.0
    assert inventory["state_stale_after_seconds"]["editable"] is False
    assert inventory["xtquant.account_type"]["value"] == "CREDIT"
    assert payload["recent_decisions"][0]["symbol_name"] == "平安银行"


def test_update_config_persists_thresholds_that_snapshot_service_consumes():
    from freshquant.position_management.dashboard_service import (
        PositionManagementDashboardService,
    )

    repository = FakeRepository()
    service = PositionManagementDashboardService(
        repository=repository,
        holding_codes_provider=lambda: [],
        settings_provider=_system_settings_provider(),
        now_provider=_fixed_now,
    )

    result = service.update_config(
        {
            "allow_open_min_bail": 900000,
            "holding_only_min_bail": 400000,
            "single_symbol_position_limit": 950000,
            "updated_by": "pytest",
        }
    )
    snapshot_service = PositionSnapshotService(
        repository=repository,
        credit_client=SuccessfulCreditClient(),
    )

    state = snapshot_service.refresh_once()

    assert repository.upserted_config["thresholds"] == {
        "allow_open_min_bail": 900000.0,
        "holding_only_min_bail": 400000.0,
        "single_symbol_position_limit": 950000.0,
    }
    assert result["thresholds"]["allow_open_min_bail"] == 900000.0
    assert result["thresholds"]["single_symbol_position_limit"] == 950000.0
    assert state["state"] == HOLDING_ONLY


def test_update_config_rejects_invalid_threshold_order():
    from freshquant.position_management.dashboard_service import (
        PositionManagementDashboardService,
    )

    service = PositionManagementDashboardService(
        repository=FakeRepository(),
        holding_codes_provider=lambda: [],
        settings_provider=_system_settings_provider(),
        now_provider=_fixed_now,
    )

    with pytest.raises(
        ValueError,
        match="allow_open_min_bail must be greater than holding_only_min_bail",
    ):
        service.update_config(
            {
                "allow_open_min_bail": 100000,
                "holding_only_min_bail": 200000,
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("allow_open_min_bail", "nan"),
        ("allow_open_min_bail", "inf"),
        ("holding_only_min_bail", "-inf"),
        ("single_symbol_position_limit", "nan"),
    ],
)
def test_update_config_rejects_non_finite_threshold_values(field, value):
    from freshquant.position_management.dashboard_service import (
        PositionManagementDashboardService,
    )

    service = PositionManagementDashboardService(
        repository=FakeRepository(),
        holding_codes_provider=lambda: [],
        settings_provider=_system_settings_provider(),
        now_provider=_fixed_now,
    )
    payload = {
        "allow_open_min_bail": 800000,
        "holding_only_min_bail": 100000,
        "single_symbol_position_limit": 800000,
    }
    payload[field] = value

    with pytest.raises(ValueError, match=f"{field} must be a finite number"):
        service.update_config(payload)


def test_get_config_falls_back_to_defaults_for_non_finite_thresholds():
    from freshquant.position_management.dashboard_service import (
        PositionManagementDashboardService,
    )

    repository = FakeRepository()
    repository.config_doc = {
        "code": "default",
        "enabled": True,
        "thresholds": {
            "allow_open_min_bail": "nan",
            "holding_only_min_bail": "inf",
            "single_symbol_position_limit": "nan",
        },
    }
    service = PositionManagementDashboardService(
        repository=repository,
        holding_codes_provider=lambda: [],
        settings_provider=_system_settings_provider(),
        now_provider=_fixed_now,
    )

    payload = service.get_config()

    assert payload["thresholds"]["allow_open_min_bail"] == 800000.0
    assert payload["thresholds"]["holding_only_min_bail"] == 100000.0
    assert payload["thresholds"]["single_symbol_position_limit"] == 800000.0


def test_dashboard_marks_threshold_change_as_pending_refresh_when_state_is_fresh():
    from freshquant.position_management.dashboard_service import (
        PositionManagementDashboardService,
    )

    repository = FakeRepository()
    repository.config_doc = {
        "code": "default",
        "enabled": True,
        "thresholds": {
            "allow_open_min_bail": 900000.0,
            "holding_only_min_bail": 400000.0,
            "single_symbol_position_limit": 950000.0,
        },
        "updated_at": "2026-03-07T12:00:18+08:00",
        "updated_by": "pytest",
    }
    repository.current_state_doc = {
        "account_id": "1208970161",
        "state": ALLOW_OPEN,
        "available_bail_balance": 865432.12,
        "snapshot_id": "pms_1",
        "data_source": "xtquant",
        "evaluated_at": "2026-03-07T12:00:15+08:00",
        "last_query_ok": "2026-03-07T12:00:15+08:00",
    }
    repository.snapshot_doc = {
        "snapshot_id": "pms_1",
        "available_amount": 102345.67,
        "fetch_balance": 92345.67,
        "total_asset": 1432100.0,
        "market_value": 1210000.0,
        "total_debt": 530000.0,
        "source": "xtquant",
    }

    service = PositionManagementDashboardService(
        repository=repository,
        holding_codes_provider=lambda: ["000001"],
        settings_provider=_system_settings_provider(),
        now_provider=_fixed_now,
    )

    payload = service.get_dashboard()
    rules = {item["key"]: item for item in payload["rule_matrix"]}

    assert payload["state"]["effective_state"] == ALLOW_OPEN
    assert payload["state"]["stale"] is False
    assert (
        payload["state"]["matched_rule"]["code"] == "thresholds_updated_pending_refresh"
    )
    assert "下一次 snapshot 刷新" in payload["state"]["matched_rule"]["detail"]
    assert rules["buy_new"]["allowed"] is True

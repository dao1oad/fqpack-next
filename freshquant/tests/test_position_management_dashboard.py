# -*- coding: utf-8 -*-

from datetime import datetime
from types import SimpleNamespace

import pytest

from freshquant.position_management.models import (
    ALLOW_OPEN,
    FORCE_PROFIT_REDUCE,
    HOLDING_ONLY,
)
from freshquant.position_management.snapshot_service import PositionSnapshotService


class FakeRepository:
    def __init__(self):
        self.config_doc = None
        self.current_state_doc = None
        self.snapshot_doc = None
        self.upserted_config = None
        self.snapshots = []
        self.decision_docs = []
        self.symbol_snapshot_docs = []

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

    def list_symbol_snapshots(self, symbols=None):
        rows = list(self.symbol_snapshot_docs)
        if symbols:
            allowed = set(symbols)
            rows = [item for item in rows if item.get("symbol") in allowed]
        return rows


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
            "decision_id": "pmd_1",
            "strategy_name": "Guardian",
            "action": "buy",
            "symbol": "000001",
            "state": HOLDING_ONLY,
            "allowed": True,
            "reason_code": "holding_buy_allowed",
            "reason_text": "当前状态允许买入已持仓标的",
            "source": "strategy",
            "source_module": "Guardian",
            "evaluated_at": "2026-03-07T12:00:00+08:00",
            "trace_id": "trc_1",
            "intent_id": "int_1",
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
    assert "状态已过期，按默认 HOLDING_ONLY 处理" in rules["buy_new"]["reason_text"]
    assert "只允许对当前已持仓标的继续买入" in rules["buy_new"]["reason_text"]
    assert "不允许借此开新仓" in rules["buy_holding"]["reason_text"]
    assert "仓位门禁不阻断卖出" in rules["sell"]["reason_text"]
    assert "不会因为该状态自动发起卖单" in rules["sell"]["reason_text"]
    assert inventory["allow_open_min_bail"]["editable"] is True
    assert inventory["single_symbol_position_limit"]["editable"] is True
    assert inventory["single_symbol_position_limit"]["label"] == "单标的默认持仓上限"
    assert inventory["single_symbol_position_limit"]["value"] == 800000.0
    assert inventory["state_stale_after_seconds"]["editable"] is False
    assert inventory["xtquant.account_type"]["value"] == "CREDIT"
    assert payload["recent_decisions"][0]["decision_id"] == "pmd_1"
    assert payload["recent_decisions"][0]["symbol_name"] == "平安银行"
    assert payload["recent_decisions"][0]["source"] == "strategy"
    assert payload["recent_decisions"][0]["source_module"] == "Guardian"
    assert payload["recent_decisions"][0]["trace_id"] == "trc_1"
    assert payload["recent_decisions"][0]["intent_id"] == "int_1"


@pytest.mark.parametrize(
    ("state", "available_bail_balance", "expected_rule_code"),
    [
        (ALLOW_OPEN, 900000.0, "allow_open_threshold"),
        (HOLDING_ONLY, 300000.0, "holding_only_threshold"),
        (FORCE_PROFIT_REDUCE, 50000.0, "force_profit_reduce_threshold"),
    ],
)
def test_dashboard_rule_matrix_reason_text_explains_state_specific_gate_semantics(
    state,
    available_bail_balance,
    expected_rule_code,
):
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
        "state": state,
        "available_bail_balance": available_bail_balance,
        "snapshot_id": "pms_1",
        "data_source": "xtquant",
        "evaluated_at": "2026-03-07T12:00:20+08:00",
        "last_query_ok": "2026-03-07T12:00:20+08:00",
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

    assert payload["state"]["matched_rule"]["code"] == expected_rule_code
    assert "当前 effective_state=" in rules["buy_new"]["reason_text"]
    assert "当前命中：" in rules["buy_new"]["reason_text"]
    assert "仓位门禁不阻断卖出" in rules["sell"]["reason_text"]

    if state == ALLOW_OPEN:
        assert "允许对新标的发起买入" in rules["buy_new"]["reason_text"]
        assert "已持仓标的也可继续买入" in rules["buy_holding"]["reason_text"]
    elif state == HOLDING_ONLY:
        assert "只允许对当前已持仓标的继续买入" in rules["buy_new"]["reason_text"]
        assert "不允许借此开新仓" in rules["buy_holding"]["reason_text"]
    else:
        assert "禁止一切买入" in rules["buy_new"]["reason_text"]
        assert "禁止一切买入" in rules["buy_holding"]["reason_text"]
        assert "盈利减仓/退出条件" in rules["sell"]["reason_text"]


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


def test_dashboard_exposes_symbol_limit_rows_with_default_and_override_values():
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
        "symbol_position_limits": {
            "overrides": {
                "600000": {
                    "limit": 500000.0,
                    "updated_at": "2026-03-22T10:00:00+08:00",
                    "updated_by": "pytest",
                }
            }
        },
    }
    repository.symbol_snapshot_docs = [
        {
            "symbol": "600000",
            "market_value": 520000.0,
            "market_value_source": "xt_positions.market_value",
            "name": "浦发银行",
        },
        {
            "symbol": "000001",
            "market_value": 200000.0,
            "market_value_source": "xt_positions.market_value",
            "name": "平安银行",
        },
    ]

    service = PositionManagementDashboardService(
        repository=repository,
        holding_codes_provider=lambda: ["600000", "000001"],
        settings_provider=_system_settings_provider(),
        now_provider=_fixed_now,
    )

    payload = service.get_dashboard()
    rows = payload["symbol_position_limits"]["rows"]

    assert [row["symbol"] for row in rows] == ["600000", "000001"]
    assert rows[0]["override_limit"] == 500000.0
    assert rows[0]["effective_limit"] == 500000.0
    assert rows[0]["using_override"] is True
    assert rows[0]["blocked"] is True
    assert rows[1]["override_limit"] is None
    assert rows[1]["effective_limit"] == 800000.0
    assert rows[1]["using_override"] is False
    assert rows[1]["blocked"] is False


def test_dashboard_exposes_three_position_views_and_quantity_consistency():
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
    }
    repository.symbol_snapshot_docs = [
        {
            "symbol": "600000",
            "quantity": 1200,
            "quantity_source": "xt_positions",
            "market_value": 520000.0,
            "market_value_source": "xt_positions_market_value",
            "name": "浦发银行",
        },
        {
            "symbol": "000001",
            "quantity": 800,
            "quantity_source": "xt_positions",
            "market_value": 200000.0,
            "market_value_source": "xt_positions_market_value",
            "name": "平安银行",
        },
    ]

    service = PositionManagementDashboardService(
        repository=repository,
        holding_codes_provider=lambda: ["600000", "000001"],
        inferred_position_loader=lambda: [
            {
                "symbol": "sh600000",
                "quantity": 1000,
                "amount_adjusted": -510000.0,
                "name": "浦发银行",
            },
            {
                "symbol": "sz000001",
                "quantity": 800,
                "amount_adjusted": -195000.0,
                "name": "平安银行",
            },
        ],
        legacy_position_loader=lambda: [
            {
                "symbol": "sh600000",
                "quantity": 1000,
                "amount_adjusted": -505000.0,
                "name": "浦发银行",
            },
            {
                "symbol": "sz000001",
                "quantity": 800,
                "amount_adjusted": -190000.0,
                "name": "平安银行",
            },
        ],
        settings_provider=_system_settings_provider(),
        now_provider=_fixed_now,
    )

    payload = service.get_dashboard()
    rows = {row["symbol"]: row for row in payload["symbol_position_limits"]["rows"]}

    assert rows["600000"]["broker_position"]["quantity"] == 1200
    assert rows["600000"]["broker_position"]["market_value"] == 520000.0
    assert rows["600000"]["inferred_position"]["quantity"] == 1200
    assert rows["600000"]["inferred_position"]["market_value"] == 520000.0
    assert "broker_truth" in rows["600000"]["inferred_position"]["quantity_source"]
    assert rows["600000"]["legacy_position"]["quantity"] == 1200
    assert rows["600000"]["legacy_position"]["market_value"] == 520000.0
    assert "broker_truth" in rows["600000"]["legacy_position"]["quantity_source"]
    assert rows["600000"]["position_consistency"]["quantity_values"] == {
        "broker": 1200,
        "inferred": 1200,
        "legacy_stock_fills": 1200,
    }
    assert rows["600000"]["position_consistency"]["quantity_consistent"] is True

    assert rows["000001"]["broker_position"]["quantity"] == 800
    assert rows["000001"]["inferred_position"]["quantity"] == 800
    assert rows["000001"]["legacy_position"]["quantity"] == 800
    assert rows["000001"]["position_consistency"]["quantity_consistent"] is True


def test_dashboard_aligns_non_broker_views_to_broker_truth_for_symbol_limit_detail():
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
    }
    repository.symbol_snapshot_docs = [
        {
            "symbol": "600000",
            "quantity": 1200,
            "quantity_source": "xt_positions",
            "market_value": 520000.0,
            "market_value_source": "xt_positions_market_value",
            "name": "浦发银行",
        }
    ]

    service = PositionManagementDashboardService(
        repository=repository,
        holding_codes_provider=lambda: ["600000"],
        inferred_position_loader=lambda: [
            {
                "symbol": "sh600000",
                "quantity": 1000,
                "amount_adjusted": -510000.0,
                "name": "浦发银行",
            }
        ],
        legacy_position_loader=lambda: [
            {
                "symbol": "sh600000",
                "quantity": 1000,
                "amount_adjusted": -505000.0,
                "name": "浦发银行",
            }
        ],
        settings_provider=_system_settings_provider(),
        now_provider=_fixed_now,
    )

    detail = service.get_symbol_limit("600000")

    assert detail["broker_position"]["quantity"] == 1200
    assert detail["inferred_position"]["quantity"] == 1200
    assert detail["legacy_position"]["quantity"] == 1200
    assert detail["inferred_position"]["market_value"] == 520000.0
    assert detail["legacy_position"]["market_value"] == 520000.0
    assert "broker_truth" in detail["inferred_position"]["quantity_source"]
    assert "broker_truth" in detail["legacy_position"]["quantity_source"]
    assert detail["position_consistency"]["quantity_values"] == {
        "broker": 1200,
        "inferred": 1200,
        "legacy_stock_fills": 1200,
    }
    assert detail["position_consistency"]["quantity_consistent"] is True


def test_dashboard_filters_dirty_symbols_that_are_not_in_holdings_or_any_pool():
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
        "symbol_position_limits": {
            "overrides": {
                "000001": {
                    "limit": 300000.0,
                    "updated_at": "2026-03-22T10:00:00+08:00",
                    "updated_by": "pytest",
                }
            }
        },
    }
    repository.symbol_snapshot_docs = [
        {
            "symbol": "600000",
            "quantity": 1200,
            "quantity_source": "xt_positions.volume",
            "market_value": 520000.0,
            "market_value_source": "xt_positions.market_value",
            "name": "浦发银行",
        },
        {
            "symbol": "000001",
            "quantity": 800,
            "quantity_source": "xt_positions.volume",
            "market_value": 200000.0,
            "market_value_source": "xt_positions.market_value",
            "name": "平安银行",
        },
    ]

    service = PositionManagementDashboardService(
        repository=repository,
        holding_codes_provider=lambda: ["600000"],
        tracked_symbol_context_provider=lambda: {
            "600000": {
                "scope_memberships": ["holding", "stock_pool"],
                "in_scope": True,
            },
        },
        inferred_position_loader=lambda: [
            {
                "symbol": "sh600000",
                "quantity": 1200,
                "amount_adjusted": -520000.0,
                "name": "浦发银行",
            },
            {
                "symbol": "sz000001",
                "quantity": 800,
                "amount_adjusted": -200000.0,
                "name": "平安银行",
            },
        ],
        legacy_position_loader=lambda: [
            {
                "symbol": "sh600000",
                "quantity": 1200,
                "amount_adjusted": -520000.0,
                "name": "浦发银行",
            },
            {
                "symbol": "sz000001",
                "quantity": 800,
                "amount_adjusted": -200000.0,
                "name": "平安银行",
            },
        ],
        settings_provider=_system_settings_provider(),
        now_provider=_fixed_now,
    )

    rows = service.get_dashboard()["symbol_position_limits"]["rows"]

    assert [row["symbol"] for row in rows] == ["600000"]


def test_dashboard_backfills_recent_decision_truth_fields_from_current_system_state():
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
        "symbol_position_limits": {
            "overrides": {
                "600000": {
                    "limit": 500000.0,
                    "updated_at": "2026-03-22T10:00:00+08:00",
                    "updated_by": "pytest",
                }
            }
        },
    }
    repository.symbol_snapshot_docs = [
        {
            "symbol": "600000",
            "quantity": 1200,
            "quantity_source": "xt_positions.volume",
            "market_value": 520000.0,
            "market_value_source": "xt_positions.market_value",
            "name": "浦发银行",
        }
    ]
    repository.decision_docs = [
        {
            "decision_id": "pmd_1",
            "strategy_name": "Guardian",
            "action": "buy",
            "symbol": "600000",
            "state": HOLDING_ONLY,
            "allowed": False,
            "reason_code": "symbol_position_limit_blocked",
            "reason_text": "单标的实时仓位已达到上限，禁止继续买入",
            "source": "strategy",
            "source_module": "Guardian",
            "evaluated_at": "2026-03-07T12:00:00+08:00",
            "trace_id": "trc_1",
            "intent_id": "int_1",
            "meta": {},
        }
    ]

    service = PositionManagementDashboardService(
        repository=repository,
        holding_codes_provider=lambda: ["600000"],
        tracked_symbol_context_provider=lambda: {
            "600000": {
                "scope_memberships": ["holding", "must_pool"],
                "in_scope": True,
            },
        },
        settings_provider=_system_settings_provider(),
        now_provider=_fixed_now,
    )

    row = service.get_dashboard()["recent_decisions"][0]

    assert row["symbol_name"] == "浦发银行"
    assert row["meta"]["is_holding_symbol"] is True
    assert row["meta"]["symbol_market_value"] == 520000.0
    assert row["meta"]["symbol_position_limit"] == 500000.0
    assert row["meta"]["symbol_market_value_source"] == "xt_positions.market_value"
    assert row["meta"]["symbol_quantity_source"] == "xt_positions.volume"
    assert row["meta"]["force_profit_reduce"] is False
    assert row["meta"]["profit_reduce_mode"] == "off"
    assert row["meta"]["symbol_limit_source"] == "override"
    assert row["meta"]["symbol_scope_memberships"] == ["holding", "must_pool"]


def test_dashboard_legacy_view_reads_compat_loader_not_raw_stock_fills_scan(
    monkeypatch,
):
    import freshquant.db as fq_db
    from freshquant.order_management.projection import stock_fills_compat
    from freshquant.position_management import dashboard_service

    class BoomStockFillsCollection:
        def find(self, *_args, **_kwargs):
            raise AssertionError("raw stock_fills collection should not be scanned")

    monkeypatch.setattr(
        stock_fills_compat,
        "list_compat_stock_positions",
        lambda repository=None, database=None: [
            {
                "symbol": "000001",
                "quantity": 600,
                "amount": -6000.0,
                "amount_adjusted": -6600.0,
                "name": "平安银行",
            }
        ],
    )
    monkeypatch.setattr(
        fq_db,
        "DBfreshquant",
        {"stock_fills": BoomStockFillsCollection()},
    )

    assert dashboard_service._default_legacy_position_loader() == [
        {
            "symbol": "000001",
            "quantity": 600,
            "amount": -6000.0,
            "amount_adjusted": -6600.0,
            "name": "平安银行",
        }
    ]


def test_update_symbol_limit_persists_override_when_limit_differs_from_default():
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
        "symbol_position_limits": {"overrides": {}},
    }
    repository.symbol_snapshot_docs = [
        {
            "symbol": "600000",
            "market_value": 480000.0,
            "market_value_source": "xt_positions.market_value",
            "name": "浦发银行",
        }
    ]

    service = PositionManagementDashboardService(
        repository=repository,
        holding_codes_provider=lambda: ["600000"],
        settings_provider=_system_settings_provider(),
        now_provider=_fixed_now,
    )

    detail = service.update_symbol_limit(
        "600000.SH",
        {
            "limit": 500000,
            "updated_by": "pytest",
        },
    )

    assert detail["symbol"] == "600000"
    assert detail["override_limit"] == 500000.0
    assert detail["effective_limit"] == 500000.0
    assert detail["using_override"] is True
    assert (
        repository.upserted_config["symbol_position_limits"]["overrides"]["600000"][
            "limit"
        ]
        == 500000.0
    )


def test_update_symbol_limit_deletes_override_when_limit_equals_default():
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
        "symbol_position_limits": {
            "overrides": {
                "600000": {
                    "limit": 500000.0,
                    "updated_at": "2026-01-01T00:00:00+08:00",
                    "updated_by": "seed",
                }
            }
        },
    }
    repository.symbol_snapshot_docs = [
        {
            "symbol": "600000",
            "market_value": 480000.0,
            "market_value_source": "xt_positions.market_value",
            "name": "浦发银行",
        }
    ]

    service = PositionManagementDashboardService(
        repository=repository,
        holding_codes_provider=lambda: ["600000"],
        settings_provider=_system_settings_provider(),
        now_provider=_fixed_now,
    )

    reset_detail = service.update_symbol_limit(
        "600000",
        {
            "limit": 800000.0,
            "updated_by": "pytest",
        },
    )

    assert reset_detail["override_limit"] is None
    assert reset_detail["effective_limit"] == 800000.0
    assert reset_detail["using_override"] is False
    assert repository.upserted_config["symbol_position_limits"]["overrides"] == {}

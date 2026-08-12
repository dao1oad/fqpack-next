# -*- coding: utf-8 -*-

"""#597 幽灵写入防护回归测试。

覆盖：
1. PR-1：终态订单收到"同一时刻、不同时区格式"的 submitted_at 回报，不再刷新
   om_broker_orders.updated_at（submitted_at 归一化）。
2. PR-3：update_broker_order_fields 拒绝 updated_at-only 写（堵住"幽灵刷新"的
   合法 API 滥用面）。
3. PR-3：repository 真写库路径落写前审计（audit_log）。
"""

from types import SimpleNamespace

import pytest

from freshquant.order_management.broker_identity import BrokerIdentityConflict
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.tracking.service import OrderTrackingService
from freshquant.tests.test_external_order_identity_p1 import (
    _FakeCollection,
    _FakeDatabase,
    _matches,
    _real_owner,
)


class _AuditCollection:
    def __init__(self):
        self.rows = []

    def insert_one(self, document):
        self.rows.append(dict(document))
        return SimpleNamespace(inserted_id=len(self.rows))


class _FakeFreshquantDb:
    def __init__(self, audit_collection):
        self._audit = audit_collection

    def __getitem__(self, name):
        assert name == "audit_log"
        return self._audit


@pytest.fixture
def audit_log(monkeypatch):
    """把 freshquant.db.DBfreshquant 替换为 fake，捕获 audit_log 写入。"""

    collection = _AuditCollection()
    monkeypatch.setattr(
        "freshquant.db.DBfreshquant",
        _FakeFreshquantDb(collection),
    )
    return collection


def _seed_terminal_order(database, repository, owner):
    database["om_orders"].rows.append({**owner, "state": "FILLED"})
    broker, _ = repository.claim_broker_order_owner({**owner, "state": "FILLED"})
    # 模拟真实终态：CAS 写入 state/aggregate/submitted_at（对应 116 14:45:07 定格）
    repository.compare_and_set_broker_order(
        before=broker,
        after={
            **broker,
            "state": "FILLED",
            "filled_quantity": 100,
            "fill_count": 1,
            "aggregate_revision": 1,
            "submitted_at": "2026-08-11T14:45:05",
            "updated_at": "2026-08-11T06:45:07.619518+00:00",
        },
    )


def _replay_report(owner):
    return {
        "internal_order_id": owner["internal_order_id"],
        "broker_order_key": owner["broker_order_key"],
        "broker_order_id": owner["broker_order_id"],
        "account_id": owner["account_id"],
        "trading_day": owner["trading_day"],
        "order_sysid": owner.get("order_sysid"),
        "symbol": owner["symbol"],
        "side": owner["side"],
        "state": "FILLED",
        # 与 broker_order 的北京无时区 submitted_at 为同一时刻（UTC ISO 格式）
        "submitted_at": "2026-08-11T06:45:05.125049+00:00",
        "event_type": "xt_order_reported",
    }


def test_terminal_replay_same_instant_submitted_at_does_not_refresh_broker_order(
    audit_log,
):
    """#597 PR-1：同刻不同格式的 submitted_at 不再产生伪差异写入。"""

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    owner = _real_owner()
    _seed_terminal_order(database, repository, owner)
    tracking = OrderTrackingService(repository=repository)

    key = owner["broker_order_key"]
    before = repository.find_broker_order(key)["updated_at"]
    tracking.ingest_order_report_with_meta(_replay_report(owner))
    after = repository.find_broker_order(key)["updated_at"]

    assert before == after
    assert repository.find_order(owner["internal_order_id"])["state"] == "FILLED"


def test_terminal_replay_with_same_naive_submitted_at_does_not_refresh(
    audit_log,
):
    """#597 PR-1：完全相同的（北京无时区）submitted_at 重复回报同样不刷新。"""

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    owner = _real_owner()
    _seed_terminal_order(database, repository, owner)
    tracking = OrderTrackingService(repository=repository)

    report = _replay_report(owner)
    report["submitted_at"] = "2026-08-11T14:45:05"
    key = owner["broker_order_key"]
    before = repository.find_broker_order(key)["updated_at"]
    tracking.ingest_order_report_with_meta(report)
    after = repository.find_broker_order(key)["updated_at"]

    assert before == after


def test_update_broker_order_fields_rejects_updated_at_only(audit_log):
    """#597 PR-3：仅刷新 updated_at 的调用被拒绝，不落库、不产生审计。"""

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    owner = _real_owner()
    _seed_terminal_order(database, repository, owner)

    key = owner["broker_order_key"]
    audit_log.rows.clear()  # 清除 seed claim 的审计，只断言本调用不产生新写
    before = repository.find_broker_order(key)["updated_at"]
    saved = repository.update_broker_order_fields(
        key,
        {"updated_at": "2026-08-11T10:05:44.530126+00:00"},
    )

    assert repository.find_broker_order(key)["updated_at"] == before
    assert saved is not None
    assert audit_log.rows == []


def test_update_broker_order_fields_rejects_unchanged_business_fields_with_new_updated_at(
    audit_log,
):
    """#597 PR-3：业务字段值全等于 current、仅 updated_at 变化时，拒绝落库。"""

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    owner = _real_owner()
    _seed_terminal_order(database, repository, owner)

    key = owner["broker_order_key"]
    audit_log.rows.clear()
    before = repository.find_broker_order(key)["updated_at"]
    saved = repository.update_broker_order_fields(
        key,
        {
            "state": "FILLED",  # 与 current 全等
            "updated_at": "2026-08-11T10:05:44.530126+00:00",
        },
    )

    assert repository.find_broker_order(key)["updated_at"] == before
    assert saved is not None
    assert audit_log.rows == []


def test_repository_real_write_records_write_audit(audit_log):
    """#597 PR-3：真实写库路径（execution fence）写前落 audit_log。"""

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    owner = _real_owner()
    database["om_orders"].rows.append({**owner, "state": "SUBMITTED"})
    repository.claim_broker_order_owner(
        {
            **owner,
            "state": "SUBMITTED",
            "broker_order_key": owner["broker_order_key"],
        }
    )
    audit_log.rows.clear()

    # execution_fence 未设置 → fence 触发真实写库
    repository.fence_broker_order_execution(
        {
            **owner,
            "broker_order_key": owner["broker_order_key"],
            "execution_fence": True,
        }
    )

    assert len(audit_log.rows) == 1
    latest = audit_log.rows[-1]
    assert latest["collection"] == "om_broker_orders"
    assert latest["broker_order_key"] == owner["broker_order_key"]
    assert latest["status"] == "started"
    assert "broker_correlation_token" in latest["before"]
    assert latest["after"]["execution_fence"] is True


def test_broker_only_with_token_is_rejected_by_claim():
    """#597 PR-2：broker_only + token 为非法态，claim 必须 fail-closed。"""

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    owner = _real_owner()
    database["om_orders"].rows.append({**owner, "state": "FILLED"})
    broker_only_id = "ord_broker_1201afddd169dff6f62cb731"
    invalid = {
        **owner,
        "internal_order_id": broker_only_id,
        "request_id": None,
        "broker_correlation_token": "FQOM8e56206a3555853e6f00",
        "source_type": "broker_only",
    }

    with pytest.raises(BrokerIdentityConflict, match="broker-only owner cannot carry"):
        repository.claim_broker_order_owner(invalid)


def test_repair_script_unsets_broker_only_token(monkeypatch):
    """#597 PR-2：修复脚本 dry-run 列出、execute $unset 非法 token。"""

    import script.maintenance.repair_broker_only_correlation_token as repair

    database = _FakeDatabase()
    collection = _UnsetAwareCollection()
    collection.rows.append(
        {
            "broker_order_key": "account:068000076370:day:20260811:sysid:1703",
            "internal_order_id": "ord_broker_1201afddd169dff6f62cb731",
            "source_type": "broker_only",
            "broker_correlation_token": "FQOM8e56206a3555853e6f00",
            "updated_at": "2026-08-11T10:05:50.953571+00:00",
        }
    )
    collection.rows.append(
        {
            "broker_order_key": "account:068000076370:day:20260811:sysid:1323",
            "internal_order_id": "ord_broker_other",
            "source_type": "broker_only",
            "broker_correlation_token": None,
        }
    )
    database["om_broker_orders"] = collection

    monkeypatch.setattr(repair, "get_order_management_db", lambda: database)

    violations = repair._collect_violations(database)
    assert len(violations) == 1
    assert violations[0]["broker_order_key"].endswith(":1703")

    # dry-run 不写
    repair._apply_repairs(database, [])
    # execute
    repair._apply_repairs(database, violations)
    saved = database["om_broker_orders"].find_one(
        {"broker_order_key": "account:068000076370:day:20260811:sysid:1703"}
    )
    assert "broker_correlation_token" not in saved
    untouched = database["om_broker_orders"].find_one(
        {"broker_order_key": "account:068000076370:day:20260811:sysid:1323"}
    )
    assert untouched.get("broker_correlation_token") is None


class _UnsetAwareCollection(_FakeCollection):
    """支持 $unset 的 fake collection（补 _FakeCollection 缺失语义）。"""

    def update_one(self, query, update, upsert=False):
        for index, document in enumerate(self.rows):
            if not _matches(document, query or {}):
                continue
            saved = dict(document)
            saved.update(dict((update or {}).get("$set") or {}))
            for field in dict((update or {}).get("$unset") or {}):
                saved.pop(field, None)
            self.rows[index] = saved
            return SimpleNamespace(matched_count=1, upserted_id=None)
        if upsert:
            saved = dict(query or {})
            saved.update(dict((update or {}).get("$setOnInsert") or {}))
            saved.update(dict((update or {}).get("$set") or {}))
            self.rows.append(saved)
            return SimpleNamespace(matched_count=0, upserted_id=len(self.rows))
        return SimpleNamespace(matched_count=0, upserted_id=None)

from __future__ import annotations

from freshquant.xt_account_sync.position_cleanup import converge_position_configs


class FakePositionsCollection:
    def __init__(self, docs):
        self.docs = list(docs)
        self.last_query = None

    def find(self, query=None, projection=None):
        self.last_query = query
        return [dict(doc) for doc in self.docs if (doc.get("volume") or 0) > 0]


class FakeBuyConfigCollection:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, query=None, projection=None):
        return [
            dict(doc)
            for doc in self.docs
            if doc.get("enabled") or any(doc.get("buy_enabled") or [])
        ]


class FakeTpProfileCollection:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, query=None, projection=None):
        return [
            dict(doc)
            for doc in self.docs
            if any(tier.get("manual_enabled") for tier in (doc.get("tiers") or []))
        ]


class FakeBuyGridService:
    def __init__(self, fail_codes=()):
        self.disabled = []
        self.fail_codes = set(fail_codes)

    def disable_grid(self, code, *, updated_by="xt_account_sync"):
        if code in self.fail_codes:
            raise RuntimeError(f"disable denied for {code}")
        self.disabled.append((code, updated_by))
        return {"code": code, "enabled": False}


class FakeTpService:
    def __init__(self, fail_symbols=()):
        self.calls = []
        self.fail_symbols = set(fail_symbols)

    def set_tier_manual_enabled(self, symbol, *, level, enabled, updated_by="system"):
        if symbol in self.fail_symbols:
            raise RuntimeError(f"tp disable denied for {symbol}")
        self.calls.append(
            {
                "symbol": symbol,
                "level": level,
                "enabled": enabled,
                "updated_by": updated_by,
            }
        )


def _positions_with_holding_600000():
    return FakePositionsCollection(
        [
            {"stock_code": "600000.SH", "volume": 1000},
            # 曾持仓已清仓：volume=0 视为未持仓
            {"stock_code": "600002.SH", "volume": 0},
        ]
    )


def test_converge_disables_only_non_holding_enabled_configs():
    buy_service = FakeBuyGridService()
    tp_service = FakeTpService()
    events = []

    result = converge_position_configs(
        positions_collection=_positions_with_holding_600000(),
        buy_grid_service=buy_service,
        takeprofit_service=tp_service,
        buy_config_collection=FakeBuyConfigCollection(
            [
                # 持仓：保持不动
                {"code": "600000", "enabled": True},
                # 未持仓：关闭
                {"code": "600001", "enabled": True},
                # 已清仓（volume=0）：关闭
                {"code": "600002", "buy_enabled": [True, False, False]},
                # 已禁用：不进入候选
                {
                    "code": "600003",
                    "enabled": False,
                    "buy_enabled": [False, False, False],
                },
                # 从未持仓候选标的：关闭
                {"code": "600004", "buy_enabled": [False, True, False]},
            ]
        ),
        takeprofit_profile_collection=FakeTpProfileCollection(
            [
                # 持仓：保持不动
                {
                    "symbol": "600000",
                    "tiers": [
                        {"level": 1, "manual_enabled": True},
                        {"level": 2, "manual_enabled": False},
                    ],
                },
                # 未持仓：只关 manual_enabled=True 的档位
                {
                    "symbol": "600005",
                    "tiers": [
                        {"level": 1, "manual_enabled": True},
                        {"level": 2, "manual_enabled": False},
                        {"level": 3, "manual_enabled": True},
                    ],
                },
                # 全部未启用：不进入候选
                {
                    "symbol": "600006",
                    "tiers": [
                        {"level": 1, "manual_enabled": False},
                        {"level": 2, "manual_enabled": False},
                    ],
                },
            ]
        ),
        event_emitter=events.append,
    )

    assert result["holding_count"] == 1
    assert sorted(buy_service.disabled) == [
        ("600001", "xt_account_sync"),
        ("600002", "xt_account_sync"),
        ("600004", "xt_account_sync"),
    ]
    assert tp_service.calls == [
        {
            "symbol": "600005",
            "level": 1,
            "enabled": False,
            "updated_by": "xt_account_sync",
        },
        {
            "symbol": "600005",
            "level": 3,
            "enabled": False,
            "updated_by": "xt_account_sync",
        },
    ]
    assert result["disabled_total"] == 4
    assert len(events) == 1
    assert events[0]["node"] == "position_cleanup_disabled"
    assert events[0]["reason_code"] == "non_holding_config_disabled"


def test_converge_is_idempotent_second_round_no_writes():
    buy_service = FakeBuyGridService()
    tp_service = FakeTpService()
    events = []
    kwargs = {
        "positions_collection": _positions_with_holding_600000(),
        "buy_grid_service": buy_service,
        "takeprofit_service": tp_service,
        "buy_config_collection": FakeBuyConfigCollection(
            [{"code": "600001", "enabled": True}]
        ),
        "takeprofit_profile_collection": FakeTpProfileCollection(
            [
                {
                    "symbol": "600005",
                    "tiers": [{"level": 1, "manual_enabled": True}],
                }
            ]
        ),
        "event_emitter": events.append,
    }

    first = converge_position_configs(**kwargs)
    # 模拟 disable_grid / set_tier_manual_enabled 已写库：配置翻转为关闭
    kwargs["buy_config_collection"].docs[0]["enabled"] = False
    kwargs["buy_config_collection"].docs[0]["buy_enabled"] = [False, False, False]
    kwargs["takeprofit_profile_collection"].docs[0]["tiers"][0][
        "manual_enabled"
    ] = False
    # 第二轮：配置已关闭 → 候选为空，不再写库、不再发事件
    second = converge_position_configs(**kwargs)

    assert first["disabled_total"] == 2
    assert second["disabled_total"] == 0
    assert len(buy_service.disabled) == 1
    assert len(tp_service.calls) == 1
    assert len(events) == 1


def test_converge_normalizes_suffixed_xt_codes():
    buy_service = FakeBuyGridService()
    result = converge_position_configs(
        positions_collection=FakePositionsCollection(
            [{"stock_code": "512600.SH", "volume": 4700}]
        ),
        buy_grid_service=buy_service,
        takeprofit_service=FakeTpService(),
        buy_config_collection=FakeBuyConfigCollection(
            [
                {"code": "512600", "enabled": True},
                {"code": "600001", "enabled": True},
            ]
        ),
        takeprofit_profile_collection=FakeTpProfileCollection([]),
    )

    assert [code for code, _ in buy_service.disabled] == ["600001"]
    assert result["holding_count"] == 1


def test_converge_per_code_failure_is_best_effort():
    buy_service = FakeBuyGridService(fail_codes=("600001",))
    tp_service = FakeTpService(fail_symbols=("600005",))

    result = converge_position_configs(
        positions_collection=FakePositionsCollection([]),
        buy_grid_service=buy_service,
        takeprofit_service=tp_service,
        buy_config_collection=FakeBuyConfigCollection(
            [
                {"code": "600001", "enabled": True},
                {"code": "600002", "enabled": True},
            ]
        ),
        takeprofit_profile_collection=FakeTpProfileCollection(
            [
                {
                    "symbol": "600005",
                    "tiers": [{"level": 1, "manual_enabled": True}],
                },
                {
                    "symbol": "600006",
                    "tiers": [{"level": 2, "manual_enabled": True}],
                },
            ]
        ),
    )

    # 失败仅 warning，不阻断其余标的；成功标的仍计入结果
    assert [code for code, _ in buy_service.disabled] == ["600002"]
    assert [call["symbol"] for call in tp_service.calls] == ["600006"]
    assert result["disabled_total"] == 2


def test_converge_positions_query_failure_does_not_raise():
    class ExplodingPositionsCollection:
        def find(self, query=None, projection=None):
            raise RuntimeError("positions unavailable")

    buy_service = FakeBuyGridService()
    result = converge_position_configs(
        positions_collection=ExplodingPositionsCollection(),
        buy_grid_service=buy_service,
        takeprofit_service=FakeTpService(),
        # 即使存在启用配置，持仓数据不可用时也必须整体跳过，绝不误关
        buy_config_collection=FakeBuyConfigCollection(
            [{"code": "600001", "enabled": True}]
        ),
        takeprofit_profile_collection=FakeTpProfileCollection([]),
    )

    assert result["skipped"] is True
    assert result["reason"] == "positions_unavailable"
    assert result["disabled_total"] == 0
    assert buy_service.disabled == []

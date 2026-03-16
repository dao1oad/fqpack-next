from freshquant.tpsl.takeprofit_service import TakeprofitService


class InMemoryTpslRepository:
    def __init__(self):
        self.profiles = {}
        self.states = {}
        self.events = []

    def find_takeprofit_profile(self, symbol):
        return self.profiles.get(symbol)

    def upsert_takeprofit_profile(self, document):
        self.profiles[document["symbol"]] = document
        return document

    def find_takeprofit_state(self, symbol):
        return self.states.get(symbol)

    def upsert_takeprofit_state(self, document):
        self.states[document["symbol"]] = document
        return document

    def insert_exit_trigger_event(self, document):
        self.events.append(document)
        return document


class MongoSafeStateRepository(InMemoryTpslRepository):
    def upsert_takeprofit_state(self, document):
        armed_levels = dict(document.get("armed_levels") or {})
        assert armed_levels == {str(key): value for key, value in armed_levels.items()}
        stored = {
            **document,
            "armed_levels": dict(armed_levels),
        }
        self.states[document["symbol"]] = stored
        return stored


def _build_tiers():
    return [
        {"level": 1, "price": 10.2, "manual_enabled": True},
        {"level": 2, "price": 10.8, "manual_enabled": False},
        {"level": 3, "price": 11.5, "manual_enabled": True},
    ]


def test_save_takeprofit_profile_updates_price_and_manual_enabled():
    repo = InMemoryTpslRepository()
    service = TakeprofitService(repository=repo)

    profile = service.save_profile("000001", tiers=_build_tiers(), updated_by="api")

    assert profile["symbol"] == "000001"
    assert profile["tiers"][1]["level"] == 2
    assert profile["tiers"][1]["manual_enabled"] is False
    assert profile["tiers"][2]["price"] == 11.5

    state = service.get_state("000001")
    assert state["armed_levels"] == {1: True, 2: False, 3: True}
    assert state["version"] == 1


def test_disable_triggered_and_lower_levels_after_hit():
    repo = InMemoryTpslRepository()
    service = TakeprofitService(repository=repo)
    service.save_profile(
        "000001",
        tiers=[
            {"level": 1, "price": 10.2, "manual_enabled": True},
            {"level": 2, "price": 10.8, "manual_enabled": True},
            {"level": 3, "price": 11.5, "manual_enabled": True},
        ],
        updated_by="api",
    )

    state = service.mark_level_triggered("000001", level=2, batch_id="tp_batch_1")

    assert state["armed_levels"] == {1: False, 2: False, 3: True}
    assert state["last_triggered_level"] == 2
    assert repo.events[-1]["event_type"] == "takeprofit_hit"


def test_rearm_all_levels_only_restores_manual_enabled_tiers():
    repo = InMemoryTpslRepository()
    service = TakeprofitService(repository=repo)
    service.save_profile("000001", tiers=_build_tiers(), updated_by="api")
    service.mark_level_triggered("000001", level=3, batch_id="tp_batch_3")

    state = service.rearm_all_levels("000001", updated_by="manual")

    assert state["armed_levels"] == {1: True, 2: False, 3: True}
    assert state["last_rearm_reason"] == "manual"


def test_get_profile_with_state_returns_profile_and_runtime_state():
    repo = InMemoryTpslRepository()
    service = TakeprofitService(repository=repo)
    service.save_profile("000001", tiers=_build_tiers(), updated_by="api")

    detail = service.get_profile_with_state("000001")

    assert detail["symbol"] == "000001"
    assert len(detail["tiers"]) == 3
    assert detail["state"]["armed_levels"] == {1: True, 2: False, 3: True}


def test_save_profile_stores_mongo_safe_state_keys_but_returns_level_map():
    repo = MongoSafeStateRepository()
    service = TakeprofitService(repository=repo)

    profile = service.save_profile("000001", tiers=_build_tiers(), updated_by="api")

    assert repo.states["000001"]["armed_levels"] == {
        "1": True,
        "2": False,
        "3": True,
    }
    assert profile["state"]["armed_levels"] == {1: True, 2: False, 3: True}

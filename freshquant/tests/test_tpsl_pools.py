from freshquant.tpsl import pools


class FakeCollection:
    def __init__(self, rows):
        self.rows = list(rows)

    def find(self, *_args, **_kwargs):
        return list(self.rows)


class FakeDb(dict):
    def __getitem__(self, name):
        return dict.__getitem__(self, name)


def test_load_active_tpsl_codes_only_returns_held_and_configured_symbols(monkeypatch):
    monkeypatch.setattr(
        pools,
        "DBfreshquant",
        FakeDb(
            {
                "xt_positions": FakeCollection(
                    [
                        {"stock_code": "000001.SZ", "volume": 300},
                        {"stock_code": "600000.SH", "volume": 0},
                        {"stock_code": "000002.SZ", "volume": 500},
                    ]
                )
            }
        ),
    )
    monkeypatch.setattr(
        pools,
        "DBOrderManagement",
        FakeDb(
            {
                "om_stoploss_bindings": FakeCollection(
                    [
                        {"symbol": "sz000001", "enabled": True},
                        {"symbol": "sh600000", "enabled": True},
                    ]
                ),
                "om_takeprofit_profiles": FakeCollection(
                    [
                        {"symbol": "000002.SZ"},
                        {"symbol": "000003.SZ"},
                    ]
                ),
            }
        ),
    )

    assert pools.load_active_tpsl_codes() == ["sz000001", "sz000002"]

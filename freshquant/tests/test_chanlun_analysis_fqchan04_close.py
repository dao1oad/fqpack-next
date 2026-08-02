import pytest

from freshquant.analysis import chanlun_analysis


class FakeChanModule:
    def __init__(self):
        self.bi_args = None

    def fq_recognise_bars(self, length, high, low):
        return []

    def fq_recognise_std_bars(self, length, high, low):
        return []

    def fq_recognise_bi(self, *args):
        self.bi_args = args
        return [0.0] * args[0]

    def fq_recognise_duan(self, length, signal, high, low):
        return [0.0] * length

    def fq_recognise_pivots(self, length, higher, signal, high, low):
        return []


@pytest.mark.parametrize(
    ("implementation", "expected_args"),
    [
        ("cl4", (1, [10.0], [9.0], [9.5])),
        ("cl1", (1, [10.0], [9.0])),
    ],
)
def test_chanlun_only_passes_close_to_fqchan04(
    monkeypatch, implementation, expected_args
):
    fake_module = FakeChanModule()
    monkeypatch.setitem(chanlun_analysis.imps, implementation, fake_module)

    chanlun_analysis.Chanlun(implementation).analysis(
        dt_list=[1],
        open_price_list=[9.2],
        close_price_list=[9.5],
        low_price_list=[9.0],
        high_price_list=[10.0],
    )

    assert fake_module.bi_args == expected_args

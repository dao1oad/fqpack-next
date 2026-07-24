from datetime import date, timedelta

from freshquant.backtest.clx.causality import analyse_prefix_stability
from freshquant.backtest.clx.engine import ClxBatchResult


class RevisingEngine:
    def calculate_all(self, high, low, open_, close, volume, *, options):
        bar_count = len(high)
        rows = [[0] * bar_count for _ in range(18)]
        if bar_count == 4:
            rows[0][3] = 102
        elif bar_count == 5:
            rows[0][3] = 202
            rows[1][3] = 1102
        elif bar_count >= 6:
            rows[1][3] = 1102
        return ClxBatchResult(tuple(tuple(row) for row in rows), bar_count)


def test_prefix_audit_records_add_replace_remove_and_reveal_dates():
    values = [1.0] * 6
    dates = [date(2024, 1, 1) + timedelta(days=offset) for offset in range(6)]
    report = analyse_prefix_stability(
        engine=RevisingEngine(),
        high=values,
        low=values,
        open_=values,
        close=values,
        volume=values,
        dates=dates,
        warmup_bars=3,
    )

    revisions = report["revision_counts"]
    assert revisions["add_zero_to_nonzero"] == 1
    assert revisions["replace_nonzero_code"] == 1
    assert revisions["remove_nonzero_to_zero"] == 1
    assert revisions["historical_backfill_additions"] == 1
    assert revisions["backfill_add_lag"]["max"] == 1
    assert revisions["signal_date_strictly_before_reveal_date"] is True
    assert (
        revisions["examples"][0]["signal_date"]
        < revisions["examples"][0]["reveal_date"]
    )
    assert report["online_to_final_zero"] == 1
    assert report["final_from_online_zero"] == 1
    assert report["stable_exact_reveal_lag"]["max"] == 1

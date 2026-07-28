from __future__ import annotations

import pandas as pd
from QUANTAXIS.QASU.save_tdx import _select_strictly_new_minute_rows


def _bars(*datetimes: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "datetime": list(datetimes),
            "code": ["301234"] * len(datetimes),
            "type": ["30min"] * len(datetimes),
            "time_stamp": [pd.Timestamp(value).timestamp() for value in datetimes],
        }
    )


def test_incremental_minute_rows_keep_first_real_bar_when_source_omits_cutoff():
    frame = _bars(
        "2026-07-22 10:00:00",
        "2026-07-22 10:30:00",
    )

    selected = _select_strictly_new_minute_rows(
        frame,
        "2026-07-21 15:00:00",
    )

    assert selected["datetime"].tolist() == [
        "2026-07-22 10:00:00",
        "2026-07-22 10:30:00",
    ]


def test_incremental_minute_rows_drop_only_the_actual_cutoff_bar():
    frame = _bars(
        "2026-07-21 15:00:00",
        "2026-07-22 10:00:00",
    )

    selected = _select_strictly_new_minute_rows(
        frame,
        "2026-07-21 15:00:00",
    )

    assert selected["datetime"].tolist() == ["2026-07-22 10:00:00"]


def test_incremental_minute_rows_keep_a_single_new_bar():
    frame = _bars("2026-07-22 10:00:00")

    selected = _select_strictly_new_minute_rows(
        frame,
        "2026-07-21 15:00:00",
    )

    assert len(selected) == 1


def test_initial_minute_rows_keep_a_single_valid_bar():
    frame = _bars("2026-07-22 10:00:00")

    selected = _select_strictly_new_minute_rows(frame, None)

    assert selected["datetime"].tolist() == ["2026-07-22 10:00:00"]


def test_incremental_minute_rows_fall_back_to_datetime_for_deduplication():
    frame = _bars(
        "2026-07-22 10:00:00",
        "2026-07-22 10:00:00",
        "2026-07-22 10:30:00",
    ).drop(columns=["time_stamp"])

    selected = _select_strictly_new_minute_rows(
        frame,
        "2026-07-21 15:00:00",
    )

    assert selected["datetime"].tolist() == [
        "2026-07-22 10:00:00",
        "2026-07-22 10:30:00",
    ]

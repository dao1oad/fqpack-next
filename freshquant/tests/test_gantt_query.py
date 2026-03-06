from freshquant.data.gantt_readmodel import (
    build_gantt_plate_matrix,
    build_gantt_stock_matrix,
    select_shouban30_plate_rows,
    select_shouban30_stock_rows,
)


def test_build_gantt_plate_matrix_groups_daily_rows():
    result = build_gantt_plate_matrix(
        [
            {
                "provider": "xgb",
                "trade_date": "2026-03-04",
                "plate_key": "11",
                "plate_name": "robotics",
                "rank": 2,
                "hot_stock_count": 5,
                "limit_up_count": 1,
                "stock_codes": ["000001", "000002"],
            },
            {
                "provider": "xgb",
                "trade_date": "2026-03-05",
                "plate_key": "11",
                "plate_name": "robotics",
                "rank": 1,
                "hot_stock_count": 8,
                "limit_up_count": 3,
                "stock_codes": ["000001", "000002", "000003"],
            },
        ]
    )

    assert result["dates"] == ["2026-03-04", "2026-03-05"]
    assert result["y_axis"] == [{"id": "11", "name": "robotics"}]
    assert result["series"] == [
        [0, 0, 2, 5, 1, ["000001", "000002"]],
        [1, 0, 1, 8, 3, ["000001", "000002", "000003"]],
    ]


def test_build_gantt_stock_matrix_builds_streaks():
    result = build_gantt_stock_matrix(
        [
            {
                "provider": "xgb",
                "trade_date": "2026-03-04",
                "plate_key": "11",
                "code6": "000001",
                "name": "alpha",
                "is_limit_up": 1,
                "stock_reason": "r1",
            },
            {
                "provider": "xgb",
                "trade_date": "2026-03-05",
                "plate_key": "11",
                "code6": "000001",
                "name": "alpha",
                "is_limit_up": 0,
                "stock_reason": "r2",
            },
        ],
        plate_key="11",
    )

    assert result["dates"] == ["2026-03-04", "2026-03-05"]
    assert result["y_axis"] == [{"symbol": "000001", "name": "alpha"}]
    assert result["series"] == [
        [0, 0, 1, 1, "r1"],
        [1, 0, 2, 0, "r2"],
    ]


def test_select_shouban30_plate_rows_prefers_latest_as_of_date():
    rows = select_shouban30_plate_rows(
        [
            {"provider": "xgb", "as_of_date": "2026-03-04", "plate_key": "11"},
            {"provider": "xgb", "as_of_date": "2026-03-05", "plate_key": "22"},
        ],
        provider="xgb",
    )

    assert rows == [{"provider": "xgb", "as_of_date": "2026-03-05", "plate_key": "22"}]


def test_select_shouban30_stock_rows_filters_by_plate_key():
    rows = select_shouban30_stock_rows(
        [
            {
                "provider": "xgb",
                "as_of_date": "2026-03-05",
                "plate_key": "11",
                "code6": "000001",
            },
            {
                "provider": "xgb",
                "as_of_date": "2026-03-05",
                "plate_key": "22",
                "code6": "000002",
            },
        ],
        provider="xgb",
        plate_key="11",
        as_of_date="2026-03-05",
    )

    assert rows == [
        {
            "provider": "xgb",
            "as_of_date": "2026-03-05",
            "plate_key": "11",
            "code6": "000001",
        }
    ]

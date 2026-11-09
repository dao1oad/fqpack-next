from __future__ import annotations

from dagster import job, op

from ..assets.market_data_repair import ensure_stock_postclose_ready


@op
def stock_postclose_repair_op(context) -> dict:
    return ensure_stock_postclose_ready(context=context)


@job(
    name="stock_postclose_repair_job",
    tags={
        "freshquant/mongo_writer": "quantaxis_market_data",
        "dagster/max_concurrent_runs": "1",
        "dagster/max_retries": "1",
    },
)
def stock_postclose_repair_job() -> None:
    stock_postclose_repair_op()


__all__ = ["stock_postclose_repair_job", "stock_postclose_repair_op"]

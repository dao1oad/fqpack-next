from datetime import datetime

from dagster import Output, graph, op

from freshquant.daily_screening.service import DailyScreeningService
from freshquant.data.trade_date_hist import tool_trade_date_hist_sina

POSTCLOSE_CUTOFF_HOUR = 15
POSTCLOSE_CUTOFF_MINUTE = 5


def _query_latest_trade_date() -> str:
    trade_dates = list(tool_trade_date_hist_sina()["trade_date"])
    if not trade_dates:
        raise RuntimeError("no trade dates available")

    now = datetime.now()
    today = now.date()
    cutoff = now.replace(
        hour=POSTCLOSE_CUTOFF_HOUR,
        minute=POSTCLOSE_CUTOFF_MINUTE,
        second=0,
        microsecond=0,
    )

    if today in trade_dates and now >= cutoff:
        return today.strftime("%Y-%m-%d")

    for trade_date in reversed(trade_dates):
        if trade_date < today:
            return trade_date.strftime("%Y-%m-%d")

    raise RuntimeError("no completed trade date available")


@op
def op_run_daily_screening_postclose(context):
    trade_date = _query_latest_trade_date()
    service = DailyScreeningService()
    repository = getattr(getattr(service, "pipeline_service", None), "repository", None)
    ensure_indexes = getattr(repository, "ensure_indexes", None)
    if callable(ensure_indexes):
        ensure_indexes()
    run = service.start_run(
        {"model": "all", "trade_date": trade_date},
        run_async=False,
        trigger_type="dagster_schedule",
    )
    run_id = str(run.get("id") or run.get("run_id") or "").strip()
    context.log.info(
        "completed daily_screening postclose trade_date=%s run_id=%s status=%s",
        trade_date,
        run_id,
        run.get("status"),
    )
    return Output(
        {
            "run_id": run_id,
            "trade_date": trade_date,
        }
    )


@graph
def graph_daily_screening_postclose():
    op_run_daily_screening_postclose()

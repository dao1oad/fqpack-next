# -*- coding: utf-8 -*-

from freshquant.position_management.credit_client import PositionCreditClient
from freshquant.position_management.snapshot_service import _normalize_credit_detail


class XtAutoRepayExecutor:
    def __init__(self, *, credit_client=None):
        self.credit_client = credit_client or PositionCreditClient()

    def query_credit_detail(self):
        details = self.credit_client.query_credit_detail()
        detail = _extract_credit_detail(details)
        if detail is None:
            raise ValueError("query_credit_detail returned no records")
        return _normalize_credit_detail(detail)

    def submit_direct_cash_repay(
        self,
        *,
        repay_amount,
        remark,
        strategy_name="XtAutoRepay",
    ):
        return self.credit_client.submit_direct_cash_repay(
            repay_amount=repay_amount,
            strategy_name=strategy_name,
            order_remark=remark,
            stock_code="",
            price=0.0,
        )


def _extract_credit_detail(details):
    if details is None:
        return None
    if isinstance(details, (list, tuple)):
        return details[0] if details else None
    return details

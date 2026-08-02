# -*- coding: utf-8 -*-

from QUANTAXIS import QA_fetch_stock_day_adv

from freshquant.data.qfq_reader import apply_qfq_to_bars
from freshquant.util.code import normalize_to_base_code


def fq_quote_QA_fetch_stock_day_adv(code, start, end):
    data = QA_fetch_stock_day_adv(code, start, end)
    if data is not None:
        adjusted, _metadata = apply_qfq_to_bars(
            data.data,
            scope="stock",
            code=normalize_to_base_code(code),
            date_col="date",
        )
        return adjusted
    return

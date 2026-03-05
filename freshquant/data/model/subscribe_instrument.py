# -*- coding: utf-8 -*-

from datetime import datetime
from typing import Optional

import tzlocal

import freshquant.util.datetime_helper as datetime_helper
from freshquant.data.model.my_base_model import MyBaseModel

local_tz = tzlocal.get_localzone()


class SubscribeInstrument(MyBaseModel):
    code: str  # 标的代码，比如600000.SH
    name: str  # 标的名称，比如浦发银行
    kind: str  # 标的类型，比如stock_cn/etf_cn/bond_cn/index_cn
    exchange: str  # 交易所
    created_at: Optional[datetime] = datetime_helper.now()
    updated_at: Optional[datetime] = datetime_helper.now()

# -*- coding: utf-8 -*-

from datetime import datetime

from freshquant.db import DBfreshquant
from freshquant.signal.strategy3 import doCaculate

if __name__ == '__main__':
    symbol = DBfreshquant['symbol'].find_one({'code': 'FU2001'})
    inspect_time = datetime(2019, 7, 31)
    doCaculate(symbol, inspect_time, True)

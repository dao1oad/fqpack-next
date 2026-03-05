# -*- coding: utf-8 -*-

import logging
import sys
from datetime import datetime

from freshquant.db import DBfreshquant
from freshquant.signal.strategy4 import doCaculate

if __name__ == '__main__':
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format='%(asctime)s %(threadName)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s',
    )
    symbol = DBfreshquant['symbol'].find_one({'code': 'RU2001'})
    doCaculate(symbol, None, True)

# -*- coding: utf-8 -*-

import logging
import os
import sys
import warnings

ORDER_QUEUE = "freshquant_order_queue"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

logging.disable(logging.INFO)
warnings.filterwarnings("ignore")

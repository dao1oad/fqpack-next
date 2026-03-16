# -*- coding: utf-8 -*-

import logging
import os
import sys
import warnings

from freshquant.runtime.network import clear_proxy_env_for_current_process

ORDER_QUEUE = "freshquant_order_queue"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

clear_proxy_env_for_current_process()
logging.disable(logging.INFO)
warnings.filterwarnings("ignore")

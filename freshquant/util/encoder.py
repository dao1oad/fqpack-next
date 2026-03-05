# -*- coding: utf-8 -*-

import datetime
import json

import numpy as np
import pandas as pd
from bson.objectid import ObjectId

from freshquant.carnation.enum_instrument import InstrumentType


class FqJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            if pd.isna(obj):
                return None
            return obj.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(obj, InstrumentType):
            return obj.value
        elif isinstance(obj, ObjectId):
            return str(obj)
        elif isinstance(obj, bytes):
            return str(obj, encoding="utf-8")
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return json.JSONEncoder.default(self, obj)

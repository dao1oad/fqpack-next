# coding=utf-8

import pandas as pd


def toDf(v):
    if isinstance(v, list):
        return pd.DataFrame(data=v)
    elif isinstance(v, dict):
        return pd.DataFrame(
            data=[
                v,
            ]
        )
    else:
        return None


def strToBool(s):
    if s is None or s == "":
        return False
    elif s.lower() in ["true", "yes", "1", "on"]:
        return True
    elif s.lower() in ["false", "no", "0", "off"]:
        return False
    else:
        raise ValueError("Invalid boolean string")

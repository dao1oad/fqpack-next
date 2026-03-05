# coding=utf-8

import json

from flask import Response, request

from freshquant.position.cn_future import (
    queryArrangedCnFutureFillList,
    queryCnFutureFillList,
)
from freshquant.util.convert import strToBool
from freshquant.util.encoder import FqJsonEncoder


def queryCnFuturePositions():
    symbol = request.args.get("symbol", default="", type=str)
    arranged = strToBool(request.args.get("arranged", default="", type=str))
    if arranged:
        posLong, posShort = queryArrangedCnFutureFillList(symbol)
    else:
        posLong, posShort = queryCnFutureFillList(symbol)
    return Response(
        json.dumps({"posLong": posLong, "posShort": posShort}, cls=FqJsonEncoder),
        mimetype="application/json",
    )

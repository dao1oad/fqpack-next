from flask import Blueprint, Response, request
import freshquant.rear.future.cn_future as cn_future
from func_timeout import func_timeout
from freshquant.signal.BusinessService import BusinessService
from freshquant.util.encoder import FqJsonEncoder
import json


future_bp = Blueprint('future', __name__, url_prefix='/api')

# 获取期货的持仓数据
@future_bp.route("/queryFuturePositions")
def queryFuturePositions():
    return cn_future.queryCnFuturePositions()


# 获取期货统计信息
@future_bp.route("/get_day_ma_list")
def get_day_ma_list():
    day_ma_list = func_timeout(30, BusinessService().get_day_ma_list)
    return Response(
        json.dumps(day_ma_list, cls=FqJsonEncoder), mimetype="application/json"
    )


# 获取期货统计信息
@future_bp.route("/get_statistic_list")
def get_statistic_list():
    date_range = request.args.get("dateRange")
    statistic_list = func_timeout(
        30, BusinessService().getStatisticList, args=(date_range,)
    )
    return Response(
        json.dumps(statistic_list, cls=FqJsonEncoder), mimetype="application/json"
    )


# 获取外盘涨跌幅列表
@future_bp.route("/get_global_future_change_list")
def get_global_future_change_list():
    globalFutureChangeList = func_timeout(
        30, BusinessService().getGlobalFutureChangeList
    )
    return Response(
        json.dumps(globalFutureChangeList, cls=FqJsonEncoder),
        mimetype="application/json",
    )


# 获取保证金率
@future_bp.route("/get_future_config")
def get_future_margin_rate():
    futureConfig = func_timeout(30, BusinessService().getFutureConfig)
    return Response(
        json.dumps(futureConfig, cls=FqJsonEncoder), mimetype="application/json"
    )


# 获取主力合约
# curl -X GET http://127.0.0.1:5000/dominant
@future_bp.route("/dominant")
def dominant():
    dominant_symbol_info_list = BusinessService().get_dominant_symbol_list()
    return Response(
        json.dumps(dominant_symbol_info_list, cls=FqJsonEncoder),
        mimetype="application/json",
    )


# 获取所有背驰列表
@future_bp.route("/get_future_signal_list")
def get_future_signal_list():
    futureSignalList = func_timeout(30, BusinessService().getFutureSignalList)
    return Response(
        json.dumps(futureSignalList, cls=FqJsonEncoder), mimetype="application/json"
    )


# 获取涨跌幅信息
@future_bp.route("/get_change_list")
def get_change_list():
    changeListResult = func_timeout(30, BusinessService().getChangeList)
    return Response(
        json.dumps(changeListResult, cls=FqJsonEncoder), mimetype="application/json"
    )


# 新增持仓信息
@future_bp.route("/create_position", methods=["POST"])
def create_position():
    position = request.json
    inserted_id = func_timeout(30, BusinessService().createPosition, args=(position,))
    res = {"id": str(inserted_id)}
    return Response(json.dumps(res, cls=FqJsonEncoder), mimetype="application/json")


# 更新持仓信息
@future_bp.route("/update_position", methods=["POST"])
def update_position():
    position = request.json
    func_timeout(30, BusinessService().updatePosition, args=(position,))
    res = {"code": "ok"}
    return Response(json.dumps(res, cls=FqJsonEncoder), mimetype="application/json")


# 更新持仓状态
@future_bp.route("/update_position_status")
def update_position_status():
    id = request.args.get("id")
    status = request.args.get("status")
    close_price = request.args.get("close_price")
    func_timeout(
        30, BusinessService().updatePositionStatus, args=(id, status, close_price)
    )
    res = {"code": "ok"}
    return Response(json.dumps(res, cls=FqJsonEncoder), mimetype="application/json")


# 查询持仓列表
@future_bp.route("/get_position_list")
def get_position_list():
    status = request.args.get("status")
    page = int(request.args.get("page") or "1")
    # 每页显示的条目
    size = int(request.args.get("size") or "10")
    endDate = request.args.get("endDate")
    positionList = func_timeout(
        30, BusinessService().getPositionList, args=(status, page, size, endDate)
    )
    return Response(
        json.dumps(positionList, cls=FqJsonEncoder), mimetype="application/json"
    )


# 跟据单个持仓
@future_bp.route("/get_position")
def get_position():
    symbol = request.args.get("symbol")
    period = request.args.get("period") or "all"
    status = request.args.get("status")
    direction = request.args.get("direction")
    singlePosition = func_timeout(
        30, BusinessService().getPosition, args=(symbol, period, status, direction)
    )
    return Response(
        json.dumps(singlePosition, cls=FqJsonEncoder), mimetype="application/json"
    )


# 查询期货级别多空方向列表
@future_bp.route("/get_future_level_direction_list")
def get_future_level_direction():
    levelDirectionList = func_timeout(30, BusinessService().getLevelDirectionList)
    return Response(
        json.dumps(levelDirectionList, cls=FqJsonEncoder), mimetype="application/json"
    )


# 新增预判信息
@future_bp.route("/create_future_prejudge_list", methods=["POST"])
def create_prejudge_list():
    futurePrejudgeData = request.json
    inserted_id = func_timeout(
        30,
        BusinessService().createFuturePrejudgeList,
        args=(futurePrejudgeData["endDate"], futurePrejudgeData["prejudgeList"]),
    )
    res = {"id": str(inserted_id)}
    return Response(json.dumps(res, cls=FqJsonEncoder), mimetype="application/json")


# 获取预判信息列表
@future_bp.route("/get_future_prejudge_list")
def get_future_prejudge_list():
    endDate = request.args.get("endDate")
    futurePrejudgeList = func_timeout(
        30, BusinessService().getFuturePrejudgeList, args=(endDate,)
    )
    return Response(
        json.dumps(futurePrejudgeList, cls=FqJsonEncoder), mimetype="application/json"
    )


# 更新预判信息列表
@future_bp.route("/update_future_prejudge_list", methods=["POST"])
def update_future_prejudge_list():
    futurePrejudgeData = request.json
    func_timeout(
        30,
        BusinessService().updateFuturePrejudgeList,
        args=(futurePrejudgeData["id"], futurePrejudgeData["prejudgeList"]),
    )
    res = {"code": "ok"}
    return Response(json.dumps(res, cls=FqJsonEncoder), mimetype="application/json")
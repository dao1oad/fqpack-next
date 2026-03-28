import json
import logging
import traceback
from datetime import datetime
from importlib import import_module
from typing import List

from flask import Blueprint, Response, jsonify, request

try:
    from func_timeout import func_timeout
except ModuleNotFoundError:  # pragma: no cover

    def func_timeout(timeout, func, args=(), kwargs=None):
        return func(*args, **(kwargs or {}))


from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.chanlun_service import get_data_v2
from freshquant.chanlun_structure_service import get_chanlun_structure
from freshquant.data.astock.holding import (
    get_arranged_stock_fill_list,
    get_stock_fills,
    get_stock_hold_position,
    get_stock_positions,
)
from freshquant.db import DBfreshquant
from freshquant.instrument.general import query_instrument_info, query_instrument_type
from freshquant.position.cn_future import queryArrangedCnFutureFillList
from freshquant.research.cjsd.main import getCjsdList
from freshquant.trading.dt import fq_trading_fetch_trade_dates
from freshquant.util.code import fq_util_code_append_market_code_suffix
from freshquant.util.encoder import FqJsonEncoder
from freshquant.util.period import (
    get_redis_cache_key,
    is_supported_realtime_period,
    to_backend_period,
)

try:
    from freshquant.database.redis import redis_db
except Exception:  # pragma: no cover
    redis_db = None

stock_bp = Blueprint("stock", __name__, url_prefix="/api")

MAX_STOCK_DATA_BAR_COUNT = 20000
SERIES_TAIL_FIELDS = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "_bi_signal_list",
)
POINT_SERIES_FIELDS = (
    "bidata",
    "duandata",
    "higherDuanData",
    "higherHigherDuanData",
)
STRUCTURE_SERIES_FIELDS = (
    ("zsdata", "zsflag"),
    ("duan_zsdata", "duan_zsflag"),
    ("higher_duan_zsdata", "higher_duan_zsflag"),
)


def _get_stock_service():
    return import_module("freshquant.stock_service")


def _create_business_service():
    return import_module("freshquant.signal.BusinessService").BusinessService()


def _get_manual_write_service():
    from freshquant.order_management.manual.service import (
        OrderManagementManualWriteService,
    )

    return OrderManagementManualWriteService()


def _get_guardian_buy_grid_service():
    from freshquant.strategy.guardian_buy_grid import get_guardian_buy_grid_service

    return get_guardian_buy_grid_service()


def _request_json_payload():
    getter = getattr(request, "get_json", None)
    if callable(getter):
        payload = getter(silent=True)
    else:  # pragma: no cover
        payload = getattr(request, "json", None)
    return payload or {}


def _get_realtime_stock_data_from_cache(symbol, period, end_date):
    if end_date or not symbol or not period or redis_db is None:
        return None

    period_backend = to_backend_period(period)
    if not is_supported_realtime_period(period_backend):
        return None

    cache_key = get_redis_cache_key(symbol, period_backend)
    try:
        cached = redis_db.get(cache_key)
    except Exception as exc:  # pragma: no cover
        logging.warning(
            "stock_data redis read failed for %s %s: %s", symbol, period, exc
        )
        return None

    if not cached:
        return None

    try:
        payload = json.loads(cached)
    except Exception as exc:
        logging.warning(
            "stock_data redis payload invalid for %s %s: %s", symbol, period, exc
        )
        return None

    return payload if isinstance(payload, dict) else None


def _parse_bar_count(raw):
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    return min(max(value, 0), MAX_STOCK_DATA_BAR_COUNT)


def _tail_stock_data_payload(payload, bar_count):
    if not isinstance(payload, dict) or bar_count <= 0:
        return payload

    date_list = payload.get("date")
    if not isinstance(date_list, list) or len(date_list) <= bar_count:
        return payload

    cutoff = str(date_list[-bar_count])
    result = dict(payload)

    for field in SERIES_TAIL_FIELDS:
        values = payload.get(field)
        if isinstance(values, list) and len(values) == len(date_list):
            result[field] = values[-bar_count:]

    for field in POINT_SERIES_FIELDS:
        values = payload.get(field)
        if not isinstance(values, dict):
            continue
        series_dates = values.get("date")
        series_data = values.get("data")
        if not isinstance(series_dates, list) or not isinstance(series_data, list):
            continue
        keep_indexes = [
            index for index, value in enumerate(series_dates) if str(value) >= cutoff
        ]
        result[field] = {
            **values,
            "date": [series_dates[index] for index in keep_indexes],
            "data": [
                series_data[index] for index in keep_indexes if index < len(series_data)
            ],
        }

    for field, flag_field in STRUCTURE_SERIES_FIELDS:
        values = payload.get(field)
        flags = payload.get(flag_field)
        if not isinstance(values, list):
            continue
        kept_values = []
        kept_flags = []
        for index, item in enumerate(values):
            if (
                not isinstance(item, list)
                or len(item) < 2
                or not isinstance(item[1], list)
                or not item[1]
            ):
                kept_values.append(item)
                if isinstance(flags, list) and index < len(flags):
                    kept_flags.append(flags[index])
                continue
            end_value = str(item[1][0])
            if end_value >= cutoff:
                kept_values.append(item)
                if isinstance(flags, list) and index < len(flags):
                    kept_flags.append(flags[index])
        result[field] = kept_values
        if isinstance(flags, list):
            result[flag_field] = kept_flags

    return result


@stock_bp.route("/stock_data")
def stock_data():
    period = request.args.get("period")
    symbol = request.args.get("symbol")
    end_date = request.args.get("endDate")
    bar_count = _parse_bar_count(request.args.get("barCount"))
    use_realtime_cache = request.args.get("realtimeCache", "").lower() in {
        "1",
        "true",
        "yes",
    }
    result = None
    if use_realtime_cache:
        result = _get_realtime_stock_data_from_cache(symbol, period, end_date)
        result = _tail_stock_data_payload(result, bar_count)
    if result is None:
        result = get_data_v2(symbol, period, end_date, bar_count=bar_count)
    return Response(json.dumps(result, cls=FqJsonEncoder), mimetype="application/json")


@stock_bp.route("/stock_data_v2")
def stock_data_v2():
    period = request.args.get("period")
    symbol = request.args.get("symbol")
    end_date = request.args.get("endDate")
    result = get_data_v2(symbol, period, end_date)
    return Response(json.dumps(result, cls=FqJsonEncoder), mimetype="application/json")


@stock_bp.route("/stock_data_chanlun_structure")
def stock_data_chanlun_structure():
    period = request.args.get("period")
    symbol = request.args.get("symbol")
    end_date = request.args.get("endDate")
    result = get_chanlun_structure(symbol, period, end_date)
    return Response(json.dumps(result, cls=FqJsonEncoder), mimetype="application/json")


# 获取股票信号列表
@stock_bp.route("/get_stock_signal_list")
def get_stock_signal_list():
    page = int(request.args.get("page", "1"))
    size = int(request.args.get("size", "1000"))
    category = request.args.get("category", "candidates")
    signalList = _get_stock_service().get_stock_signal_list(page, size, category)
    return jsonify(signalList)


@stock_bp.route("/get_stock_model_signal_list")
def get_stock_model_signal_list():
    page = int(request.args.get("page", "1"))
    size = int(request.args.get("size", "1000"))
    signal_list = _get_stock_service().get_stock_model_signal_list(page, size)
    return jsonify(signal_list)


# 获取股票池中股票列表
@stock_bp.route("/get_stock_pools_list")
def get_stock_pools_list():
    page = int(request.args.get("page", "1"))
    if page <= 0:
        page = 1
    pools_list = _get_stock_service().get_stock_pools_list(page)
    return jsonify(pools_list)


# 计算股票网格交易计划
@stock_bp.route("/plan_grid_trade")
def plan_grid_trade():
    try:
        # 获取股票代码参数
        code = request.args.get("code")

        if code:
            # 如果提供了股票代码，通过成交记录计算参数
            fills = get_arranged_stock_fill_list(code)
            if not fills:  # 检查list是否为空
                return jsonify({"error": f"未找到股票 {code} 的成交记录"}), 404

            # 通过成交记录计算网格参数
            prices = [fill["price"] for fill in fills]
            ceiling_price = float(request.args.get("ceiling_price", max(prices)))
            floor_price = float(request.args.get("floor_price", min(prices)))

            # 计算总数量和总金额
            # 使用get_stock_hold_position函数获取持仓信息
            position_info = get_stock_hold_position(code)
            if position_info:
                quantity = int(position_info["quantity"])
                amount_adjusted = float(position_info["amount_adjusted"])
                amount = abs(amount_adjusted)
            else:
                # 如果没有找到持仓信息，回退到原来的计算方式
                quantity = int(sum(fill["quantity"] for fill in fills))
                amount = float(
                    sum(fill["amount"] * fill.get("amount_adjust", 1) for fill in fills)
                )
            # grid_num可以被参数覆盖
            grid_num = int(request.args.get("grid_num", str(len(fills))))

        else:
            # 如果没有提供股票代码，检查必需的直接参数
            required_params = ["ceiling_price", "floor_price", "amount", "quantity"]
            for param in required_params:
                if param not in request.args:
                    return jsonify({"error": f"缺少必需参数: {param}"}), 400
            grid_num = int(request.args.get("grid_num", "10"))
            # 获取直接参数
            ceiling_price = float(request.args.get("ceiling_price"))
            floor_price = float(request.args.get("floor_price"))
            amount = float(request.args.get("amount"))
            quantity = int(request.args.get("quantity"))

        # 参数验证
        if ceiling_price <= floor_price:
            return (
                jsonify({"error": "ceiling_price must be greater than floor_price"}),
                400,
            )
        if amount <= 0:
            return jsonify({"error": "amount must be positive"}), 400
        if quantity <= 0:
            return jsonify({"error": "quantity must be positive"}), 400
        if grid_num < 2:
            return jsonify({"error": "grid_num must be at least 2"}), 400

        # 调用服务计算网格方案
        result = _get_stock_service().plan_stock_grid_trade(
            ceiling_price=ceiling_price,
            floor_price=floor_price,
            amount=amount,
            quantity=quantity,
            grid_num=grid_num,
        )
        if code:
            result["code"] = code  # 添加股票代码到结果中
        return jsonify(result)

    except ValueError as e:
        logging.error(f"网格交易计划计算异常: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logging.error(f"网格交易计划计算异常: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": "Internal server error"}), 500


# 获取预选股票池分类列表
@stock_bp.route("/get_stock_pre_pools_category")
def get_stock_pre_pools_category():
    category_list = _get_stock_service().get_stock_pre_pools_category()
    return jsonify(category_list)


# 获取预选股票池中股票列表
@stock_bp.route("/get_stock_pre_pools_list")
def get_stock_pre_pools_list():
    page = int(request.args.get("page", "1"))
    category = request.args.get("category")
    if category is None:
        category = ""
    if page <= 0:
        page = 1
    pools_list = _get_stock_service().get_stock_pre_pools_list(page, category)
    return jsonify(pools_list)


# 获取必选股票池中股票列表
@stock_bp.route("/get_stock_must_pools_list")
def get_stock_must_pools_list():
    page = int(request.args.get("page", "1"))
    if page <= 0:
        page = 1
    pools_list = _get_stock_service().get_stock_must_pools_list(page)
    return jsonify(pools_list)


# 从预选股票池中添加股票到股票池中
@stock_bp.route("/add_to_stock_pools_by_code")
def add_to_stock_pools_by_code():
    code = request.args.get("code")
    if code is None:
        return jsonify({"code": "1", "msg": "code is None"})
    days = int(request.args.get("days", "30"))
    result = _get_stock_service().add_to_stock_pools_by_code(code, days)
    if result:
        return jsonify({"code": "0", "msg": "操作成功"})
    else:
        return jsonify({"code": "1", "msg": "操作失败"})


# 从监控股票池中删除股票
@stock_bp.route("/delete_from_stock_pools_by_code")
def delete_from_stock_pools_by_code():
    code = request.args.get("code")
    if code is None:
        return jsonify({"code": "1", "msg": "code is None"})
    result = _get_stock_service().delete_from_stock_pools_by_code(code)
    if result:
        return jsonify({"code": "0", "msg": "操作成功"})
    else:
        return jsonify({"code": "1", "msg": "操作失败"})


# 从预选池删除股票
@stock_bp.route("/delete_from_stock_pre_pools_by_code")
def delete_from_stock_pre_pools_by_code():
    code = request.args.get("code")
    if code is None:
        return jsonify({"code": "1", "msg": "code is None"})
    result = _get_stock_service().delete_from_stock_pre_pools_by_code(code)
    if result:
        return jsonify({"code": "0", "msg": "操作成功"})
    else:
        return jsonify({"code": "1", "msg": "操作失败"})


# 从监控股票池中添加股票到必选池
@stock_bp.route("/add_to_must_pool_by_code")
def add_to_must_pool_by_code():
    """
    根据code从监控股票池中添加股票到必选池
    Args:
        code: 股票代码
        stop_loss_price: 止损价格
        initial_lot_amount: 初始 lot 数量
        lot_amount: 每次 lot 数量
    Returns:
        bool: 操作是否成功
    """
    code = request.args.get("code")
    stop_loss_price = request.args.get("stop_loss_price", type=float)
    initial_lot_amount = request.args.get("initial_lot_amount", type=float)
    lot_amount = request.args.get("lot_amount", type=float)
    if code is None or stop_loss_price < 0 or initial_lot_amount < 0 or lot_amount < 0:
        return jsonify({"code": "1", "msg": "code is None"})
    result = _get_stock_service().add_to_must_pool(
        code, stop_loss_price, initial_lot_amount, lot_amount
    )
    if result:
        return jsonify({"code": "0", "msg": "操作成功"})
    else:
        return jsonify({"code": "1", "msg": "操作失败"})


# 从必选池里面删除
@stock_bp.route("/delete_from_must_pool_by_code")
def delete_from_must_pool_by_code():
    code = request.args.get("code")
    if code is None:
        return jsonify({"code": "1", "msg": "code is None"})
    result = _get_stock_service().delete_from_must_pool_by_code(code)
    if result:
        return jsonify({"code": "0", "msg": "操作成功"})
    else:
        return jsonify({"code": "1", "msg": "操作失败"})


# 查询股票持仓列表
@stock_bp.route("/get_stock_position_list")
def get_stock_position_list():
    stock_positions: List = get_stock_positions()

    # 将amount_adjusted字段的值赋给amount字段，然后删除amount_adjusted字段
    for position in stock_positions:
        if "amount_adjusted" in position:
            position["amount"] = position["amount_adjusted"]
            del position["amount_adjusted"]
        # 保留amount字段两位小数
        if "amount" in position:
            position["amount"] = round(position["amount"], 2)

    return Response(
        json.dumps(stock_positions, cls=FqJsonEncoder),
        mimetype="application/json",
    )


@stock_bp.route("/stock_hold_position")
def stock_hold_position():
    """获取单个股票的持仓信息"""
    code = request.args.get("code")
    if not code:
        return jsonify({"code": 1, "error": "股票代码参数不能为空"}), 400

    try:
        position_info = get_stock_hold_position(code)
        if position_info:
            return jsonify({"code": 0, "data": position_info})
        else:
            return jsonify(
                {"code": 1, "data": None, "message": "未找到该股票的持仓信息"}
            )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@stock_bp.route("/guardian_buy_grid_config", methods=["GET"])
def guardian_buy_grid_config_get():
    code = request.args.get("code")
    result = _get_guardian_buy_grid_service().get_config(code)
    return jsonify(result or {})


@stock_bp.route("/guardian_buy_grid_config", methods=["POST"])
def guardian_buy_grid_config_post():
    payload = _request_json_payload()
    result = _get_guardian_buy_grid_service().upsert_config(
        payload.get("code"),
        buy_1=payload.get("buy_1"),
        buy_2=payload.get("buy_2"),
        buy_3=payload.get("buy_3"),
        buy_enabled=payload.get("buy_enabled"),
        enabled=payload.get("enabled"),
        updated_by=payload.get("updated_by", "api"),
    )
    return jsonify(result)


@stock_bp.route("/guardian_buy_grid_state", methods=["GET"])
def guardian_buy_grid_state_get():
    code = request.args.get("code")
    result = _get_guardian_buy_grid_service().get_state(code)
    return jsonify(result or {})


@stock_bp.route("/guardian_buy_grid_state", methods=["POST"])
def guardian_buy_grid_state_post():
    payload = _request_json_payload()
    result = _get_guardian_buy_grid_service().upsert_state(
        payload.get("code"),
        buy_active=payload.get("buy_active"),
        last_hit_level=payload.get("last_hit_level"),
        last_hit_price=payload.get("last_hit_price"),
        last_hit_signal_time=payload.get("last_hit_signal_time"),
        last_reset_reason=payload.get("last_reset_reason"),
        updated_by=payload.get("updated_by", "api"),
    )
    return jsonify(result)


@stock_bp.route("/guardian_buy_grid_state/reset", methods=["POST"])
def guardian_buy_grid_state_reset():
    payload = _request_json_payload()
    result = _get_guardian_buy_grid_service().reset_after_sell_trade(
        payload.get("code"),
        updated_by=payload.get("updated_by", "api"),
        reason=payload.get("reason", "manual_reset"),
    )
    return jsonify(result)


@stock_bp.route("/get_cjsd_list")
def get_cjsd_list():
    cjsdList = getCjsdList()
    return jsonify(cjsdList)


# 查询单个股票持仓
@stock_bp.route("/get_stock_position")
def get_stock_position():
    symbol = request.args.get("symbol")
    period = request.args.get("period") or "all"
    status = request.args.get("status")
    singlePosition = func_timeout(
        30, _create_business_service().getStockPosition, args=(symbol, period, status)
    )
    return Response(
        json.dumps(singlePosition, cls=FqJsonEncoder), mimetype="application/json"
    )


# 新增股票持仓信息
@stock_bp.route("/create_stock_position", methods=["POST"])
def create_stock_position():
    position = request.json
    inserted_id = func_timeout(
        30, _create_business_service().createStockPosition, args=(position,)
    )
    res = {"id": str(inserted_id)}
    return Response(json.dumps(res, cls=FqJsonEncoder), mimetype="application/json")


# 更新股票持仓信息
@stock_bp.route("/update_stock_position", methods=["POST"])
def update_stock_position():
    position = request.json
    func_timeout(30, _create_business_service().updateStockPosition, args=(position,))
    res = {"code": "ok"}
    return Response(json.dumps(res, cls=FqJsonEncoder), mimetype="application/json")


# 更新股票持仓状态
@stock_bp.route("/update_stock_position_status")
def update_stock_position_status():
    id = request.args.get("id")
    status = request.args.get("status")
    func_timeout(
        30, _create_business_service().updateStockPositionStatus, args=(id, status)
    )
    res = {"code": "ok"}
    return Response(json.dumps(res, cls=FqJsonEncoder), mimetype="application/json")


@stock_bp.route("/get_settings")
def get_params():
    params = _get_stock_service().get_params()
    return jsonify(params)


@stock_bp.route("/update_settings", methods=["POST"])
def update_params():
    try:
        # 检查请求体是否为空
        if not request.json:
            return jsonify({"code": "1", "msg": "请求体不能为空"})

        params = request.json

        # 检查必需的参数
        if "name" not in params:
            return jsonify({"code": "1", "msg": "缺少必需参数: name"})

        if "value" not in params:
            return jsonify({"code": "1", "msg": "缺少必需参数: value"})

        name = params["name"]
        value = params["value"]

        # 基本参数验证
        if not name or not isinstance(name, str):
            return jsonify({"code": "1", "msg": "参数名称必须是非空字符串"})

        if name.strip() == "":
            return jsonify({"code": "1", "msg": "参数名称不能为空字符串"})

        # 调用服务层函数
        result = _get_stock_service().update_params(name, value)

        if result:
            return jsonify({"code": "0", "msg": "操作成功"})
        else:
            return jsonify({"code": "1", "msg": "操作失败"})

    except ValueError as ve:
        return jsonify({"code": "1", "msg": str(ve)})
    except Exception as e:
        return jsonify({"code": "1", "msg": f"系统错误: {str(e)}"})


@stock_bp.route("/add_to_stock_pools_by_stock", methods=["POST"])
def add_to_stock_pools_by_stock():
    try:
        # 检查请求体是否为空
        if not request.json:
            return jsonify({"code": "1", "msg": "请求体不能为空"})

        stock = request.json

        # 检查必需的参数
        if "code" not in stock:
            return jsonify({"code": "1", "msg": "缺少必需参数: code"})

        if "category" not in stock:
            return jsonify({"code": "1", "msg": "缺少必需参数: category"})

        if "stop_loss_price" not in stock:
            return jsonify({"code": "1", "msg": "缺少必需参数: stop_loss_price"})

        code = stock["code"]

        # 基本参数验证
        if not code or not isinstance(code, str):
            return jsonify({"code": "1", "msg": "参数名称必须是非空字符串"})

        if code.strip() == "":
            return jsonify({"code": "1", "msg": "参数名称不能为空字符串"})

        # 调用服务层函数
        result = _get_stock_service().add_to_stock_pools_by_stock(stock)

        if result:
            return jsonify({"code": "0", "msg": "操作成功"})
        else:
            return jsonify({"code": "1", "msg": "操作失败"})

    except ValueError as ve:
        return jsonify({"code": "1", "msg": str(ve)})
    except Exception as e:
        return jsonify({"code": "1", "msg": f"系统错误: {str(e)}"})


@stock_bp.route("/stock_fills", methods=["GET"])
def query_stock_fills():
    try:
        symbol = request.args.get("symbol")
        instrumentType = query_instrument_type(symbol.lower())
        stock_fills = None
        future_fills = None
        if (
            instrumentType == InstrumentType.STOCK_CN
            or instrumentType == InstrumentType.ETF_CN
        ):
            stock_fills = get_stock_fills(symbol[-6:])
            if stock_fills is not None and len(stock_fills) > 0:
                # 只选择存在的列，忽略不存在的列
                desired_columns = [
                    "date",
                    "time",
                    "quantity",
                    "price",
                    "amount",
                    "amount_adjust",
                ]
                existing_columns = [
                    col for col in desired_columns if col in stock_fills.columns
                ]
                stock_fills = stock_fills[existing_columns].to_dict(orient="records")
        else:
            future_fills = queryArrangedCnFutureFillList(symbol)

        if stock_fills is not None and len(stock_fills) > 0:
            return jsonify(
                {
                    "code": "0",
                    "data": {
                        "instrument_type": InstrumentType.STOCK_CN.value,
                        "entry_ledger": stock_fills,
                        "stock_fills": stock_fills,
                    },
                }
            )
        elif future_fills is not None and len(future_fills) > 0:
            return jsonify(
                {
                    "code": "0",
                    "data": {
                        "instrument_type": InstrumentType.FUTURE_CN.value,
                        "future_fills": future_fills,
                    },
                }
            )
        else:
            return jsonify({"code": "1", "msg": "没有查询到任何数据"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@stock_bp.route("/stock_fills/reset", methods=["POST"])
def reset_stock_fills():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Missing request data"}), 400

        code = data.get("code")
        grid_list = data.get("grid_list")

        # 过滤掉price和quantity任一个字段是0的数据
        if grid_list:
            grid_list = [
                item
                for item in grid_list
                if item.get("price", 0) != 0 and item.get("quantity", 0) != 0
            ]

        if not code or not grid_list:
            return (
                jsonify({"error": "Missing required fields: code and grid_list"}),
                400,
            )

        position_info = get_stock_hold_position(code)
        if not position_info:
            return jsonify({"error": "No such position"}), 400
        quantity = position_info["quantity"]
        grid_quantity = sum(int(item["quantity"]) for item in grid_list)
        if quantity != grid_quantity:
            return jsonify({"error": "Quantity mismatch"}), 400

        existing_records = list(DBfreshquant.stock_fills.find({"symbol": code}))
        if existing_records:
            DBfreshquant.audit_log.insert_one(
                {
                    "operation": "reset_stock_fills",
                    "symbol": code,
                    "original_records": existing_records,
                    "timestamp": datetime.now(),
                    "record_count": len(existing_records),
                }
            )

        instrument = query_instrument_info(code)
        stock_name = instrument.get("name", "") if instrument else ""
        stock_code = fq_util_code_append_market_code_suffix(code)
        trade_dates_df = fq_trading_fetch_trade_dates()
        trade_dates = trade_dates_df["trade_date"].tolist()

        today = datetime.now().date()
        past_trade_dates = [date for date in trade_dates if date < today]
        past_trade_dates.sort(reverse=True)

        if len(past_trade_dates) < len(grid_list):
            return jsonify({"error": "Not enough trading days for the grid items"}), 400

        new_records = []
        for i, grid_item in enumerate(grid_list):
            trade_date = past_trade_dates[len(grid_list) - 1 - i]
            date_int = int(trade_date.strftime("%Y%m%d"))

            new_records.append(
                {
                    "symbol": code,
                    "date": date_int,
                    "time": "09:31:00",
                    "price": float(grid_item["price"]),
                    "amount": float(grid_item["amount"]),
                    "amount_adjust": float(grid_item["amount_adjust"]),
                    "quantity": int(grid_item["quantity"]),
                }
            )

        result = _get_manual_write_service().reset_symbol_lots(
            code=code,
            name=stock_name,
            stock_code=stock_code,
            grid_items=new_records,
            source="reset",
        )

        return (
            jsonify(
                {
                    "message": f"Successfully reset stock fills for {code}",
                    "deleted_count": result["deleted_count"],
                    "inserted_count": result["inserted_count"],
                }
            ),
            200,
        )

    except Exception as e:
        error_msg = f"Error in reset_stock_fills: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)  # 用于调试
        return jsonify({"error": str(e)}), 500

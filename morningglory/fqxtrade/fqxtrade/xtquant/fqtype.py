# coding=utf-8

from xtquant import xtconstant
from xtquant.xttype import (
    XtAccountStatus,
    XtAsset,
    XtCancelError,
    XtCancelOrderResponse,
    XtOrder,
    XtOrderError,
    XtOrderResponse,
    XtPosition,
    XtSmtAppointmentResponse,
    XtTrade,
)


class FqXtAsset(object):
    def __init__(self, xtAsset: XtAsset):
        self.account_type = xtconstant.SECURITY_ACCOUNT
        self.account_id = xtAsset.account_id
        self.cash = xtAsset.cash
        self.frozen_cash = xtAsset.frozen_cash
        self.market_value = xtAsset.market_value
        self.total_asset = xtAsset.total_asset

    def to_dict(self):
        return {
            "source": "xtquant",
            "account_type": self.account_type,
            "account_id": self.account_id,
            "cash": self.cash,
            "frozen_cash": self.frozen_cash,
            "market_value": self.market_value,
            "total_asset": self.total_asset,
            "position_pct": (
                self.market_value / self.total_asset * 100
                if self.total_asset > 0
                else 0
            ),
        }


class FqXtOrder(object):
    def __init__(self, xtOrder: XtOrder):
        self.account_type = xtconstant.SECURITY_ACCOUNT
        self.account_id = xtOrder.account_id
        self.stock_code = xtOrder.stock_code
        self.order_id = xtOrder.order_id
        self.order_sysid = xtOrder.order_sysid
        self.order_time = xtOrder.order_time
        self.order_type = xtOrder.order_type
        self.order_volume = xtOrder.order_volume
        self.price_type = xtOrder.price_type
        self.price = xtOrder.price
        self.traded_volume = xtOrder.traded_volume
        self.traded_price = xtOrder.traded_price
        self.order_status = xtOrder.order_status
        self.status_msg = xtOrder.status_msg
        self.strategy_name = xtOrder.strategy_name
        self.order_remark = xtOrder.order_remark

    def to_dict(self):
        return {
            "source": "xtquant",
            "account_type": self.account_type,
            "account_id": self.account_id,
            "stock_code": self.stock_code,
            "order_id": self.order_id,
            "order_sysid": self.order_sysid,
            "order_time": self.order_time,
            "order_type": self.order_type,
            "order_volume": self.order_volume,
            "price_type": self.price_type,
            "price": self.price,
            "traded_volume": self.traded_volume,
            "traded_price": self.traded_price,
            "order_status": self.order_status,
            "status_msg": self.status_msg,
            "strategy_name": self.strategy_name,
            "order_remark": self.order_remark,
        }


class FqXtTrade(object):
    def __init__(self, xtTrade: XtTrade):
        self.account_type = xtconstant.SECURITY_ACCOUNT
        self.account_id = xtTrade.account_id
        self.order_type = xtTrade.order_type
        self.stock_code = xtTrade.stock_code
        self.traded_id = xtTrade.traded_id
        self.traded_time = xtTrade.traded_time
        self.traded_price = xtTrade.traded_price
        self.traded_volume = xtTrade.traded_volume
        self.traded_amount = xtTrade.traded_amount
        self.order_id = xtTrade.order_id
        self.order_sysid = xtTrade.order_sysid
        self.strategy_name = xtTrade.strategy_name
        self.order_remark = xtTrade.order_remark

    def to_dict(self):
        return {
            "source": "xtquant",
            "account_type": self.account_type,
            "account_id": self.account_id,
            "order_type": self.order_type,
            "stock_code": self.stock_code,
            "traded_id": self.traded_id,
            "traded_time": self.traded_time,
            "traded_price": self.traded_price,
            "traded_volume": self.traded_volume,
            "traded_amount": self.traded_amount,
            "order_id": self.order_id,
            "order_sysid": self.order_sysid,
            "strategy_name": self.strategy_name,
            "order_remark": self.order_remark,
        }


class FqXtPosition(object):
    def __init__(self, xtPosition: XtPosition):
        self.account_type = xtconstant.SECURITY_ACCOUNT
        self.account_id = xtPosition.account_id
        self.stock_code = xtPosition.stock_code
        self.volume = xtPosition.volume
        self.can_use_volume = xtPosition.can_use_volume
        self.open_price = xtPosition.open_price
        self.market_value = xtPosition.market_value
        self.frozen_volume = xtPosition.frozen_volume
        self.on_road_volume = xtPosition.on_road_volume
        self.yesterday_volume = xtPosition.yesterday_volume
        self.avg_price = xtPosition.avg_price
        self.last_price = getattr(xtPosition, "last_price", None)
        self.instrument_name = getattr(xtPosition, "instrument_name", None)

    def to_dict(self):
        return {
            "source": "xtquant",
            "account_type": self.account_type,
            "account_id": self.account_id,
            "stock_code": self.stock_code,
            "volume": self.volume,
            "can_use_volume": self.can_use_volume,
            "open_price": self.open_price,
            "market_value": self.market_value,
            "frozen_volume": self.frozen_volume,
            "on_road_volume": self.on_road_volume,
            "yesterday_volume": self.yesterday_volume,
            "avg_price": self.avg_price,
            "last_price": self.last_price,
            "instrument_name": self.instrument_name,
        }


class FqXtOrderError(object):
    def __init__(self, xtOrderError: XtOrderError):
        self.account_type = xtconstant.SECURITY_ACCOUNT
        self.account_id = xtOrderError.account_id
        self.order_id = xtOrderError.order_id
        self.error_id = xtOrderError.error_id
        self.error_msg = xtOrderError.error_msg
        self.strategy_name = xtOrderError.strategy_name
        self.order_remark = xtOrderError.order_remark

    def to_dict(self):
        return {
            "source": "xtquant",
            "account_type": self.account_type,
            "account_id": self.account_id,
            "order_id": self.order_id,
            "error_id": self.error_id,
            "error_msg": self.error_msg,
            "strategy_name": self.strategy_name,
            "order_remark": self.order_remark,
        }


class FqXtCancelError(object):
    def __init__(self, xtCancelError: XtCancelError):
        self.account_type = xtconstant.SECURITY_ACCOUNT
        self.account_id = xtCancelError.account_id
        self.order_id = xtCancelError.order_id
        self.error_id = xtCancelError.error_id
        self.error_msg = xtCancelError.error_msg
        self.market = xtCancelError.market
        self.order_sysid = xtCancelError.order_sysid

    def to_dict(self):
        return {
            "source": "xtquant",
            "account_type": self.account_type,
            "account_id": self.account_id,
            "order_id": self.order_id,
            "error_id": self.error_id,
            "error_msg": self.error_msg,
            "market": self.market,
            "order_sysid": self.order_sysid,
        }


class FqXtOrderResponse(object):
    def __init__(self, xtOrderResponse: XtOrderResponse):
        self.account_type = xtconstant.SECURITY_ACCOUNT
        self.account_id = xtOrderResponse.account_id
        self.order_id = xtOrderResponse.order_id
        self.strategy_name = xtOrderResponse.strategy_name
        self.order_remark = xtOrderResponse.order_remark
        self.error_msg = xtOrderResponse.error_msg
        self.seq = xtOrderResponse.seq

    def to_dict(self):
        return {
            "source": "xtquant",
            "account_type": self.account_type,
            "account_id": self.account_id,
            "order_id": self.order_id,
            "strategy_name": self.strategy_name,
            "order_remark": self.order_remark,
            "seq": self.seq,
        }


class FqXtAccountStatus(object):
    def __init__(self, xtAccountStatus: XtAccountStatus):
        self.account_type = xtAccountStatus.account_type
        self.account_id = xtAccountStatus.account_id
        self.status = xtAccountStatus.status

    def to_dict(self):
        return {
            "source": "xtquant",
            "account_type": self.account_type,
            "account_id": self.account_id,
            "status": self.status,
        }


class FqXtSmtAppointmentResponse(object):
    def __init__(self, xtSmtAppointmentResponse: XtSmtAppointmentResponse):
        self.apply_id = xtSmtAppointmentResponse.apply_id
        self.msg = xtSmtAppointmentResponse.msg
        self.success = xtSmtAppointmentResponse.success
        self.seq = xtSmtAppointmentResponse.seq

    def to_dict(self):
        return {
            "source": "xtquant",
            "apply_id": self.apply_id,
            "msg": self.msg,
            "success": self.success,
            "seq": self.seq,
        }


class FqXtCancelOrderResponse(object):
    """
    迅投异步委托撤单请求返回结构
    """

    def __init__(self, xtCancelOrderResponse: XtCancelOrderResponse):
        self.account_type = xtconstant.SECURITY_ACCOUNT
        self.account_id = xtCancelOrderResponse.account_id
        self.cancel_result = xtCancelOrderResponse.cancel_result
        self.order_id = xtCancelOrderResponse.order_id
        self.order_sysid = xtCancelOrderResponse.order_sysid
        self.seq = xtCancelOrderResponse.seq

    def to_dict(self):
        return {
            "source": "xtquant",
            "account_type": self.account_type,
            "account_id": self.account_id,
            "cancel_result": self.cancel_result,
            "order_id": self.order_id,
            "seq": self.seq,
        }

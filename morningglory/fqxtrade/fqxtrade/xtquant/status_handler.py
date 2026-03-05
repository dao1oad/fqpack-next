from tornado.web import RequestHandler
from fqxtrade.xtquant.trading_manager import TradingManager
from fqxtrade.xtquant.connection_manager import ConnectionManager

class StatusHandler(RequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 初始化成员变量
        self.trading_manager = TradingManager()
        self.connection_manager = ConnectionManager()

    def get(self):
        _, _, connected = self.trading_manager.get_connection()
        self.write({
            "connected": connected,
            "retry_count": self.connection_manager.retry_count
        })

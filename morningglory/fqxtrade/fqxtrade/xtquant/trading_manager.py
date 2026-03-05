import threading

class TradingManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(TradingManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized') or not self._initialized:
            self._lock = threading.Lock()
            self.xt_trader = None
            self.acc = None
            self.connected = False
            self._initialized = True

    def update_connection(self, xt_trader, acc, connected):
        self.xt_trader = xt_trader
        self.acc = acc
        self.connected = connected

    def get_connection(self):
        return self.xt_trader, self.acc, self.connected
    
    def lock(self):
        return self._lock

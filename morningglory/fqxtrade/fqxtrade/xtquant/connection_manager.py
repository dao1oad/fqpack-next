import threading

class ConnectionManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(ConnectionManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized') or not self._initialized:
            self._lock = threading.Lock()
            self.connected = False
            self.retry_count = 0
            self.max_retries = 10
            self.retry_interval = 5  # seconds
            self._initialized = True

    def reset(self):
        with self._lock:
            self.connected = False
            self.retry_count = 0

    def can_retry(self):
        with self._lock:
            return self.retry_count < self.max_retries

    def mark_connected(self):
        with self._lock:
            self.connected = True
            self.retry_count = 0
            
    def reset_retry_count(self):
        with self._lock:
            self.retry_count = 0

    def mark_disconnected(self):
        with self._lock:
            self.connected = False
            self.retry_count += 1

    def get_retry_delay(self):
        with self._lock:
            return min(self.retry_interval * (self.retry_count + 1), 60)  # max 60 seconds

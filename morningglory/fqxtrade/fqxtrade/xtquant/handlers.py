from fqxtrade.xtquant.status_handler import StatusHandler
from fqxtrade.xtquant.query_data_handler import QueryDataHandler

handlers = [
    (r"/api/status", StatusHandler),
    (r"/api/query_data", QueryDataHandler),
]

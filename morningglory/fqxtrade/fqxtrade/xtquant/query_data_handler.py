from loguru import logger
from tornado.web import RequestHandler
from fqxtrade.xtquant.trading_manager import TradingManager
import json
import tempfile
import os

class QueryDataHandler(RequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 初始化成员变量
        self.trading_manager = TradingManager()

    def post(self):
        with self.trading_manager.lock():
            xt_trader, acc, _ = self.trading_manager.get_connection()
            if not xt_trader or not acc:
                response_data = {"error": "No active connection to the trading server."}
                logger.info(f"Response: {response_data}")
                self.set_status(500)
                self.write(response_data)
                return
            # 获取请求体中的数据
            data = self.request.body.decode('utf-8')
            logger.info(f"Request: {data}")
            query_data = json.loads(data)
            data_type = query_data.get("data_type")
            start_time = query_data.get("start_time")
            end_time = query_data.get("end_time")
            user_param = query_data.get("user_param", {})
            
            # 创建临时文件路径，后缀为 .csv
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as temp_file:
                result_path = temp_file.name
            try:
                # 调用交易管理器的查询数据方法
                result = xt_trader.query_data(acc, result_path, data_type, start_time, end_time, user_param)
                if result is None:
                    response_data = {"error": "Failed to query data."}
                    logger.info(f"Response: {response_data}")
                    self.set_status(500)
                    self.write(response_data)
                else:
                    records = result.to_dict(orient='records')
                    response_data = {"data": records}
                    logger.info(f"Response: {response_data}")
                    self.write(response_data)
            finally:
                # 确保临时文件被删除
                if os.path.exists(result_path):
                    os.remove(result_path)

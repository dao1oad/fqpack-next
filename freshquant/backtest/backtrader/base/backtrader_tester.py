import random
from freshquant.instrument.stock import fq_inst_fetch_stock_list
from datetime import datetime
from freshquant.backtest.backtrader.base.backtrader_runner import BacktraderRunner

class BacktraderTester:
    def get_stock_list_sample(self):
        """
        获取一些常用的股票代码作为示例

        返回:
        list: 股票代码列表
        """
        # 一些常用的股票代码
        popular_stocks = [
            "000001",  # 平安银行
            "000002",  # 万科A
            "600000",  # 浦发银行
            "600036",  # 招商银行
            "600519",  # 贵州茅台
            "000858",  # 五粮液
            "002415",  # 海康威视
            "300059",  # 东方财富
        ]

        try:
            # 尝试从数据库获取股票列表
            stock_list = fq_inst_fetch_stock_list()
            if stock_list and len(stock_list) > 0:
                # 随机选择100个标的作为回测对象
                available_codes = [stock['code'] for stock in stock_list]
                if len(available_codes) > 100:
                    selected_codes = random.sample(available_codes, 100)
                    print(f"从数据库获取到 {len(stock_list)} 只股票，随机选择100只作为回测对象")
                else:
                    selected_codes = available_codes
                    print(f"从数据库获取到 {len(stock_list)} 只股票，全部用作回测对象")
                return selected_codes
        except Exception as e:
            print(f"从数据库获取股票列表失败: {e}")

        print("使用预设的热门股票列表")
        return popular_stocks

    def run_with_real_data(self, stock_codes=None, start_date=None, end_date=None):
        """
        使用真实数据运行五阳策略的回测

        参数:
        stock_codes: list, 股票代码列表，如果为None则使用默认股票
        start_date: datetime, 回测开始日期
        end_date: datetime, 回测结束日期
        """
        print("=== 五阳策略真实数据回测 ===")

        # 设置默认参数
        if start_date is None:
            start_date = datetime(2023, 1, 1)
        if end_date is None:
            end_date = datetime.now()

        if stock_codes is None:
            stock_codes = self.get_stock_list_sample()

        print(f"回测股票: {stock_codes}")
        print(f"回测时间范围: {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')}")

        # 创建回测运行器
        runner = BacktraderRunner(
            base_strategy_class=self.strategy_class,
            init_cash=1000000  # 初始资金100万
        )

        # 获取并添加股票数据
        successful_stocks = []
        for stock_code in stock_codes:
            print(f"\n处理股票: {stock_code}")
            stock_data = runner.get_real_stock_data(stock_code, start_date, end_date)

            if stock_data is not None and len(stock_data) > 0:
                # 添加数据到回测器
                data_name = f"{stock_code}.SZ" if stock_code.startswith(('000', '002', '300')) else f"{stock_code}.SH"
                runner.add_data_from_dataframe(stock_data, name=data_name)
                successful_stocks.append(stock_code)
                print(f"成功添加股票 {stock_code} 的数据")
            else:
                print(f"跳过股票 {stock_code}，数据获取失败")

        if len(successful_stocks) == 0:
            print("错误: 没有成功获取任何股票数据，无法进行回测")
            return None

        print(f"\n成功加载 {len(successful_stocks)} 只股票的数据: {successful_stocks}")

        # 运行回测
        print("\n开始回测...")
        results = runner.run(
            strategy_name="五连阳动量跟随策略",
            strategy_id="five_yang_real_data",
            lot_size=10000,  # 每次买入金额限制
            init_cash=1000000
        )

        print("\n回测完成!")

        # 可选：绘制回测结果图表
        if len(successful_stocks) <= 10:
            try:
                print("正在生成回测图表...")
                runner.plot()
            except Exception as e:
                print(f"绘制图表时出错: {e}")
                print("提示: 可能需要安装matplotlib: pip install matplotlib")
        else:
            print(f"股票数量过多({len(successful_stocks)}只)，跳过绘图以避免图表过于复杂")

        return results

    def run_single_stock_backtest(self, stock_code, start_date=None, end_date=None):
        """
        对单只股票运行五阳策略回测

        参数:
        stock_code: str, 股票代码
        start_date: datetime, 开始日期
        end_date: datetime, 结束日期
        """
        print(f"=== 单股票回测: {stock_code} ===")

        if start_date is None:
            start_date = datetime(2023, 1, 1)
        if end_date is None:
            end_date = datetime.now()

        return self.run_with_real_data([stock_code], start_date, end_date)

    def run_custom_stock_list_backtest(self):
        """
        运行自定义股票列表的回测
        """
        print("=== 自定义股票列表回测 ===")
        print("请输入股票代码列表，用逗号分割 (例如: 000001,000002,600036,002415)")
        stock_input = input("股票代码: ").strip()

        if not stock_input:
            print("股票代码列表不能为空")
            return None

        # 解析股票代码列表
        try:
            # 按逗号分割并去除空格
            custom_stocks = [code.strip() for code in stock_input.split(',') if code.strip()]

            if not custom_stocks:
                print("未找到有效的股票代码")
                return None

            # 验证股票代码格式（6位数字）
            valid_stocks = []
            for code in custom_stocks:
                if len(code) == 6 and code.isdigit():
                    valid_stocks.append(code)
                else:
                    print(f"警告: 股票代码 '{code}' 格式不正确，已跳过")

            if not valid_stocks:
                print("没有有效的股票代码")
                return None

            print(f"使用自定义股票列表: {valid_stocks} (共{len(valid_stocks)}只股票)")

            # 自定义时间范围
            start_date = datetime(2023, 1, 1)
            end_date = datetime.now()

            return self.run_with_real_data(valid_stocks, start_date, end_date)

        except Exception as e:
            print(f"解析股票代码列表时出错: {e}")
            return None
        
def run_tester(tester: BacktraderTester):
    print("五阳策略Backtrader回测系统")
    print("=" * 50)

    print("请选择回测模式:")
    print("1. 随机100个股票回测")
    print("2. 单只股票回测")
    print("3. 自定义股票列表回测")
    print("4. 退出")

    choice = input("请输入选择 (1-4): ").strip()

    results = None

    if choice == "1":
        print("\n使用默认股票列表进行回测...")
        results = tester.run_with_real_data()

    elif choice == "2":
        stock_code = input("请输入股票代码 (如 000001): ").strip()
        if stock_code:
            results = tester.run_single_stock_backtest(stock_code)
        else:
            print("股票代码不能为空")

    elif choice == "3":
        print("\n使用自定义股票列表进行回测...")
        results = tester.run_custom_stock_list_backtest()

    elif choice == "4":
        print("退出程序")
        return

    else:
        print("无效选择，使用默认模式")
        results = tester.run_with_real_data()

    # 输出最终统计
    if results:
        print("\n" + "=" * 50)
        print("回测统计完成")
        print("详细分析结果请查看上方输出")
    else:
        print("\n回测失败，请检查数据源和网络连接")
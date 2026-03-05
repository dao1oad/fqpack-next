#!/usr/bin/env python
"""
策略运行脚本

用于运行 five_yang_strategy 和 clxs_strategy 中定义的策略，
支持依赖关系管理和并发数量限制。

使用方法:
    python script/run_strategies.py --help
    python script/run_strategies.py --strategy five_yang --max-workers 4
    python script/run_strategies.py --strategy clxs --max-workers 2
    python script/run_strategies.py --strategy all --max-workers 4
"""

import argparse
import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from itertools import product
from typing import Optional

import pendulum
import traceback

from freshquant.data.astock.pre_pool import save_a_stock_pre_pool
from freshquant.data.trade_date_hist import tool_trade_date_last
from freshquant.sim.analyze.strategy_analyzer import StrategyAnalyzer
from freshquant.sim.base_strategy.input_data_models import InputDataModel
from freshquant.sim.base_strategy.input_param_models import MarketDirection
from freshquant.sim.clxs_strategy.input_param_models import ClxsInputParamModel
from freshquant.sim.clxs_strategy.main import ClxsStrategy
from freshquant.sim.five_yang_strategy.input_param_models import FiveYangInputParamModel
from freshquant.sim.five_yang_strategy.main import FiveYangStrategy

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


@dataclass
class StrategyTask:
    """策略任务定义"""

    name: str
    task_type: str  # 'five_yang_main', 'five_yang_child', 'clxs'
    params: dict = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)


def execute_task(task_name: str, task_type: str, params: dict, dep_results: dict) -> dict:
    """在子进程中执行任务（顶层函数，可被pickle）"""
    try:
        if task_type == 'five_yang_main':
            result = run_five_yang_strategy(None, None, None)
            save_stock_pool(result, "momentum")
            analyze_strategy_performance(result)
            return result

        elif task_type == 'five_yang_child':
            parent_result = dep_results.get('five_yang_strategy')
            parent_account_cookie = (
                parent_result.get("account_cookie") if parent_result else None
            )
            stock_pool_cookies = (
                [parent_account_cookie] if parent_account_cookie else None
            )
            result = run_five_yang_strategy(
                params['direction_1d'],
                params['direction_60m'],
                params['direction_30m'],
                stock_pool_cookies,
            )
            save_stock_pool(result, "momentum")
            analyze_strategy_performance(result)
            return result

        elif task_type == 'clxs':
            result = run_clxs_strategy(params['model_opt'])
            save_stock_pool(result, "clxs")
            analyze_strategy_performance(result)
            return result

        else:
            raise ValueError(f"未知任务类型: {task_type}")

    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


class StrategyRunner:
    """策略运行器，管理依赖关系和多进程执行"""

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.tasks: dict[str, StrategyTask] = {}
        self.results: dict[str, dict] = {}

    def add_task(self, task: StrategyTask):
        """添加策略任务"""
        self.tasks[task.name] = task

    def _can_run(self, task: StrategyTask) -> bool:
        """检查任务的依赖是否已完成"""
        return all(dep in self.results for dep in task.dependencies)

    def _get_dependency_result(self, dep_name: str) -> Optional[dict]:
        """获取依赖任务的结果"""
        return self.results.get(dep_name)

    def run_all(self):
        """运行所有任务，按依赖顺序执行"""
        pending = set(self.tasks.keys())
        running = {}

        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            while pending or running:
                # 提交可以运行的任务
                ready_tasks = [
                    name
                    for name in pending
                    if self._can_run(self.tasks[name])
                    and len(running) < self.max_workers
                ]

                for task_name in ready_tasks:
                    task = self.tasks[task_name]
                    pending.remove(task_name)

                    # 获取依赖结果
                    dep_results = {
                        dep: self._get_dependency_result(dep)
                        for dep in task.dependencies
                    }

                    logger.info(f"开始运行: {task_name}")
                    future = executor.submit(
                        execute_task,
                        task_name,
                        task.task_type,
                        task.params,
                        dep_results,
                    )
                    running[future] = task_name

                if not running:
                    if pending:
                        logger.error(f"存在无法满足依赖的任务: {pending}")
                        break
                    continue

                # 等待任意一个任务完成
                done_futures = []
                for future in as_completed(running.keys()):
                    done_futures.append(future)
                    break  # 只处理一个完成的任务

                for future in done_futures:
                    task_name = running.pop(future)
                    try:
                        result = future.result()
                        if "error" in result:
                            logger.error(f"任务 {task_name} 失败: {result['error']}")
                        else:
                            logger.info(f"完成: {task_name}")
                        self.results[task_name] = result
                    except Exception as e:
                        logger.error(f"任务 {task_name} 失败: {e}")
                        self.results[task_name] = {"error": str(e)}

        return self.results


# ============== Five Yang Strategy ==============


def run_five_yang_strategy(
    direction_1d: Optional[MarketDirection],
    direction_60m: Optional[MarketDirection],
    direction_30m: Optional[MarketDirection],
    stock_pool_account_cookies: Optional[list[str]] = None,
) -> dict:
    """运行五连阳策略"""
    input_data_model = InputDataModel(
        data_length={'1d': 1000},
        stock_pool_account_cookies=stock_pool_account_cookies,
    )
    input_param_model = FiveYangInputParamModel(
        var_chan_1d_market_direction=direction_1d,
        var_chan_60m_market_direction=direction_60m,
        var_chan_30m_market_direction=direction_30m,
    )
    strategy = FiveYangStrategy(
        init_cash=1000000,
        lot_size=3000,
        nodatabase=False,
        input_data_model=input_data_model,
        input_param_model=input_param_model,
    )
    strategy.run_strategy()
    positions = strategy.get_current_positions()
    trading_day = strategy.get_current_trading_day()
    return {
        "account_cookie": strategy.strategy_name,
        "positions": positions,
        "trading_day": trading_day,
    }


def save_stock_pool(strategy_result: dict, strategy_type: str) -> dict:
    """保存股票池"""
    positions = strategy_result.get("positions")
    trading_day = strategy_result.get("trading_day")
    account_cookie = strategy_result.get("account_cookie")
    print(trading_day, account_cookie)

    if not positions or not trading_day or not account_cookie:
        raise ValueError("策略未返回有效的持仓、交易日或账户标识信息")

    codes = [code.split(".")[1] if "." in code else code for code in positions.keys()]
    expire_at = pendulum.datetime(2099, 12, 31, 23, 59, 59)

    last_trade_date = tool_trade_date_last()
    if last_trade_date and trading_day == last_trade_date.strftime('%Y-%m-%d'):
        save_a_stock_pre_pool(
            codes=codes,
            category=account_cookie,
            expire_at=expire_at,
            append_mode=False,
            strategy_type=strategy_type,
        )

    return {"account_cookie": account_cookie, "codes": codes}


def analyze_strategy_performance(strategy_result: dict) -> dict:
    """分析策略表现"""
    account_cookie = strategy_result.get("account_cookie")
    analyzer = StrategyAnalyzer(account_cookie)
    stats = analyzer.analyze_strategy()
    return {"account_cookie": account_cookie, "stats": stats}


def generate_direction_suffix(
    direction_1d: Optional[MarketDirection],
    direction_60m: Optional[MarketDirection],
    direction_30m: Optional[MarketDirection],
) -> tuple[str, str]:
    """生成方向后缀"""
    if direction_1d is None and direction_60m is None and direction_30m is None:
        return "", ""

    direction_map = {MarketDirection.LONG: "多", MarketDirection.SHORT: "空"}
    parts = []
    asset_parts = []

    if direction_1d is not None:
        parts.append(f"日{direction_map[direction_1d]}")
        asset_parts.append(f"1d_{direction_1d.value}")
    if direction_60m is not None:
        parts.append(f"60{direction_map[direction_60m]}")
        asset_parts.append(f"60m_{direction_60m.value}")
    if direction_30m is not None:
        parts.append(f"30{direction_map[direction_30m]}")
        asset_parts.append(f"30m_{direction_30m.value}")

    description_suffix = f"-{''.join(parts)}"
    asset_suffix = f"_{'_'.join(asset_parts)}"
    return asset_suffix, description_suffix


def build_five_yang_tasks(runner: StrategyRunner):
    """构建五连阳策略任务"""
    # 主策略
    main_strategy_name = "five_yang_strategy"

    runner.add_task(
        StrategyTask(
            name=main_strategy_name,
            task_type='five_yang_main',
        )
    )

    # 8个子策略
    directions = [MarketDirection.LONG, MarketDirection.SHORT]
    for direction_1d, direction_60m, direction_30m in product(directions, repeat=3):
        asset_suffix, _ = generate_direction_suffix(
            direction_1d, direction_60m, direction_30m
        )
        child_strategy_name = f"five_yang_strategy{asset_suffix}"

        runner.add_task(
            StrategyTask(
                name=child_strategy_name,
                task_type='five_yang_child',
                params={
                    'direction_1d': direction_1d,
                    'direction_60m': direction_60m,
                    'direction_30m': direction_30m,
                },
                dependencies=[main_strategy_name],
            )
        )


# ============== CLXS Strategy ==============


def run_clxs_strategy(model_opt: int) -> dict:
    """运行CLXS策略"""
    input_data_model = InputDataModel(data_length={'1d': 3000})
    input_param_model = ClxsInputParamModel(
        var_model_opt=model_opt,
        var_wave_opt=1560,
        var_stretch_opt=0,
        var_trend_opt=1,
        var_atr_period=20,
        var_atr_multiplier=2.0,
        var_profit_loss_ratio=1.0,
    )
    strategy = ClxsStrategy(
        init_cash=1000000,
        lot_size=3000,
        nodatabase=False,
        input_data_model=input_data_model,
        input_param_model=input_param_model,
    )
    strategy.run_strategy()
    positions = strategy.get_current_positions()
    trading_day = strategy.get_current_trading_day()
    return {
        "account_cookie": strategy.strategy_name,
        "positions": positions,
        "trading_day": trading_day,
    }


def build_clxs_tasks(runner: StrategyRunner):
    """构建CLXS策略任务"""
    model_opts = [1, 10001, 10002, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

    for model_opt in model_opts:
        strategy_name = f"clxs_strategy_{str(model_opt).zfill(5)}"

        runner.add_task(
            StrategyTask(
                name=strategy_name,
                task_type='clxs',
                params={'model_opt': model_opt},
            )
        )


def main():
    parser = argparse.ArgumentParser(
        description='运行策略脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python script/run_strategies.py --strategy five_yang --max-workers 5
    python script/run_strategies.py --strategy clxs --max-workers 5
    python script/run_strategies.py --strategy all --max-workers 10
        """,
    )
    parser.add_argument(
        '--strategy',
        choices=['five_yang', 'clxs', 'all'],
        default='all',
        help='要运行的策略类型 (默认: all)',
    )
    parser.add_argument(
        '--max-workers',
        type=int,
        default=10,
        help='最大并发数量 (默认: 10)',
    )

    args = parser.parse_args()

    runner = StrategyRunner(max_workers=args.max_workers)

    if args.strategy in ('five_yang', 'all'):
        logger.info("添加五连阳策略任务...")
        build_five_yang_tasks(runner)

    if args.strategy in ('clxs', 'all'):
        logger.info("添加CLXS策略任务...")
        build_clxs_tasks(runner)

    logger.info(f"共 {len(runner.tasks)} 个任务，最大并发数: {args.max_workers}")
    logger.info("开始运行策略...")

    results = runner.run_all()

    # 统计结果
    success_count = sum(1 for r in results.values() if "error" not in r)
    fail_count = len(results) - success_count

    logger.info(f"运行完成: 成功 {success_count}, 失败 {fail_count}")

    if fail_count > 0:
        logger.error("失败的任务:")
        for name, result in results.items():
            if "error" in result:
                logger.error(f"  - {name}: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()

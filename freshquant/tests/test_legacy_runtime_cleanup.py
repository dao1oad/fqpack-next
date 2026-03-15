from pathlib import Path


def test_legacy_huey_runtime_files_are_removed() -> None:
    assert not Path("freshquant/worker/__init__.py").exists()
    assert not Path("freshquant/worker/consumer.py").exists()
    assert not Path("freshquant/worker/market_data_task.py").exists()
    assert not Path("freshquant/worker/queue.py").exists()
    assert not Path("freshquant/market_data/stock_cn_a_collector.py").exists()
    assert not Path("freshquant/market_data/stock_cn_a_sina_tick_collector.py").exists()


def test_legacy_batch_deploy_scripts_are_removed() -> None:
    assert not Path("deploy.bat").exists()
    assert not Path("deploy_rear.bat").exists()

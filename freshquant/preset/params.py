# -*- coding: utf-8 -*-

from freshquant.database.mongodb import DBfreshquant
from freshquant.util.mask_helper import mask


def init_param_dict(quiet=False):
    # 从数据库获取当前配置
    notification_config = DBfreshquant.params.find_one({"code": "notification"}) or {}
    dingtalk_config = (
        notification_config.get("value", {}).get("webhook", {}).get("dingtalk", {})
    )
    webhook_dingtalk_private_url = dingtalk_config.get("private", "")
    webhook_dingtalk_public_url = dingtalk_config.get("public", "")
    if quiet:
        print("\n当前钉钉Webhook配置：")
        print(f"私密URL: {mask(webhook_dingtalk_private_url, show_chars=10)}")
        print(f"公共URL: {mask(webhook_dingtalk_public_url, show_chars=10)}")
    else:
        print("请配置钉钉Webhook（直接回车保持当前值）")
        webhook_dingtalk_private_url = (
            input(f"私密URL [{mask(webhook_dingtalk_private_url, show_chars=10)}]: ")
            or webhook_dingtalk_private_url
        )
        webhook_dingtalk_public_url = (
            input(f"公共URL [{mask(webhook_dingtalk_public_url, show_chars=10)}]: ")
            or webhook_dingtalk_public_url
        )
    DBfreshquant.params.update_one(
        {"code": "notification"},
        {
            "$setOnInsert": {
                "value": {
                    "webhook": {
                        "dingtalk": {
                            "private": webhook_dingtalk_private_url,
                            "public": webhook_dingtalk_public_url,
                        }
                    },
                },
            }
        },
        upsert=True,
    )

    # 获取当前监控配置
    monitor_config = DBfreshquant.params.find_one({"code": "monitor"}) or {}
    current_periods = (
        monitor_config.get("value", {}).get("stock", {}).get("periods", ["1m"])
    )

    if quiet:
        print("\n当前监控周期配置：")
        print(f"K线周期: {', '.join(current_periods)}")
    else:
        print("\n请配置监控周期（多个值用逗号分隔，直接回车保持当前值）")
        print("可选周期: 1m,3m,5m,15m,30m,60m,90m,120m,1d")
        periods_input = input(f"K线周期 [{', '.join(current_periods)}]: ")
        if periods_input:
            current_periods = [p.strip() for p in periods_input.split(",") if p.strip()]

    DBfreshquant.params.update_one(
        {"code": "monitor"},
        {
            "$setOnInsert": {
                "value": {
                    "stock": {
                        "periods": current_periods,
                        "auto_open": True,  # 保持原有默认值
                    },
                },
            }
        },
        upsert=True,
    )

    # XTData 监控模式（严格二选一，重启后生效；标的集合在 Producer 侧可动态增量订阅）
    monitor_config = DBfreshquant.params.find_one({"code": "monitor"}) or {}
    xtdata_cfg = (monitor_config.get("value", {}) or {}).get("xtdata", {}) or {}
    xtdata_mode = xtdata_cfg.get("mode", "clx_15_30")
    xtdata_max_symbols = int(xtdata_cfg.get("max_symbols", 50) or 50)
    prewarm_cfg = xtdata_cfg.get("prewarm", {}) or {}
    prewarm_max_bars = int(prewarm_cfg.get("max_bars", 20000) or 20000)

    if quiet:
        print("\n当前XTData监控配置：")
        print(f"mode: {xtdata_mode} (guardian_1m | clx_15_30)")
        print(f"max_symbols: {xtdata_max_symbols}")
        print(f"prewarm.max_bars: {prewarm_max_bars}")

    DBfreshquant.params.update_one(
        {"code": "monitor"},
        {
            "$set": {
                "value.xtdata.mode": xtdata_mode,
                "value.xtdata.max_symbols": xtdata_max_symbols,
                "value.xtdata.prewarm.max_bars": prewarm_max_bars,
            }
        },
        upsert=True,
    )

    # 获取当前xtquant配置
    xtquant_config = DBfreshquant.params.find_one({"code": "xtquant"}) or {}
    current_value = xtquant_config.get("value", {})
    current_path = current_value.get("path", "")
    current_account = current_value.get("account", "")

    if quiet:
        print("\n当前xtquant配置：")
        print(f"MiniQMT路径: {current_path}")
        print(f"交易账号: {mask(current_account, show_chars=3)}")
    else:
        print("\n请配置xtQuant（直接回车保持当前值）")
        print("提示：路径指向userdata_mini目录，账号为MiniQMT登录账号")
        current_path = input(f"MiniQMT路径 [{current_path}]: ") or current_path
        current_account = (
            input(f"交易账号 [{mask(current_account, show_chars=3)}]: ")
            or current_account
        )

    DBfreshquant.params.update_one(
        {"code": "xtquant"},
        {"$set": {"value.path": current_path, "value.account": current_account}},
        upsert=True,
    )

    # 获取当前guardian配置
    guardian_config = DBfreshquant.params.find_one({"code": "guardian"}) or {}
    stock_config = guardian_config.get("value", {}).get("stock", {})
    current_position_pct = stock_config.get("position_pct", 30.0)
    current_auto_open = stock_config.get("auto_open", True)
    current_lot_amount = stock_config.get("lot_amount", 3000.0)
    current_min_amount = stock_config.get("min_amount", 1000.0)

    if quiet:
        print("\n当前交易守护者配置：")
        print(f"最低仓位比例(%): {current_position_pct}")
        print(f"是否自动开仓: {'是' if current_auto_open else '否'}")
        print(f"普通一网交易金额: {current_lot_amount}")
        print(f"最低一网交易金额: {current_min_amount}")
    else:
        print("\n请配置交易守护者（直接回车保持当前值）")
        current_position_pct = float(
            input(f"最低仓位比例(%) [{current_position_pct}]: ") or current_position_pct
        )
        auto_open_input = input(
            f"是否自动开仓(yes/no) [{'是' if current_auto_open else '否'}]: "
        ).lower()
        current_auto_open = (
            auto_open_input in ['y', 'yes', '是']
            if auto_open_input
            else current_auto_open
        )
        current_lot_amount = float(
            input(f"一网交易金额 [{current_lot_amount}]: ") or current_lot_amount
        )
        current_min_amount = float(
            input(f"最低一网交易金额 [{current_min_amount}]: ") or current_min_amount
        )

    DBfreshquant.params.update_one(
        {"code": "guardian"},
        {
            "$set": {
                "value.stock.position_pct": current_position_pct,
                "value.stock.auto_open": current_auto_open,
                "value.stock.lot_amount": current_lot_amount,
                "value.stock.min_amount": current_min_amount,
            }
        },
        upsert=True,
    )

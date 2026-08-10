from freshquant.system_settings_contract import (
    DEFAULT_BROKER_SUBMIT_MODE,
    DEFAULT_XTQUANT_ACCOUNT_TYPE,
    VALID_BROKER_SUBMIT_MODES,
)


def resolve_stock_account(
    query_param=None,
    stock_account_cls=None,
    settings_provider=None,
):
    if stock_account_cls is None:
        from xtquant.xttype import StockAccount as stock_account_cls

    if settings_provider is None and query_param is None:
        from freshquant.system_settings import system_settings as settings_provider

    if settings_provider is not None:
        xtquant_settings = getattr(settings_provider, "xtquant", None)
        account_id = str(getattr(xtquant_settings, "account", "") or "").strip()
        account_type = str(
            getattr(xtquant_settings, "account_type", "STOCK") or "STOCK"
        )
    else:
        account_id = str(query_param("xtquant.account", "") or "").strip()
        account_type = str(query_param("xtquant.account_type", "STOCK") or "STOCK")
    if not account_id:
        return None, "", ""

    account_type = account_type.strip().upper() or "STOCK"
    account = stock_account_cls(account_id, account_type)
    return account, account_id, account_type


def resolve_broker_submit_mode(settings_provider=None):
    """解析 broker 提交模式。

    默认从 system_settings 读取；非法值归一到合同默认 `normal`。
    旧 query_param 兼容分支已删除：当前生产调用只使用 settings_provider。
    """

    if settings_provider is None:
        from freshquant.system_settings import system_settings as settings_provider

    submit_mode = (
        str(
            getattr(
                settings_provider.xtquant,
                "broker_submit_mode",
                DEFAULT_BROKER_SUBMIT_MODE,
            )
            or DEFAULT_BROKER_SUBMIT_MODE
        )
        .strip()
        .lower()
        or DEFAULT_BROKER_SUBMIT_MODE
    )
    if submit_mode not in VALID_BROKER_SUBMIT_MODES:
        return DEFAULT_BROKER_SUBMIT_MODE
    return submit_mode

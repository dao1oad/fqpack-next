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


def resolve_broker_submit_mode(query_param=None, settings_provider=None):
    if settings_provider is None and query_param is None:
        from freshquant.system_settings import system_settings as settings_provider

    if settings_provider is not None:
        submit_mode = str(
            getattr(settings_provider.xtquant, "broker_submit_mode", "normal")
            or "normal"
        )
    else:
        submit_mode = str(
            query_param("xtquant.broker_submit_mode", "normal") or "normal"
        )
    submit_mode = submit_mode.strip().lower() or "normal"
    if submit_mode not in {"normal", "observe_only"}:
        return "normal"
    return submit_mode

def resolve_stock_account(query_param=None, stock_account_cls=None):
    if query_param is None:
        from freshquant.carnation.param import queryParam as query_param

    if stock_account_cls is None:
        from xtquant.xttype import StockAccount as stock_account_cls

    account_id = str(query_param("xtquant.account", "") or "").strip()
    if not account_id:
        return None, "", ""

    account_type = str(query_param("xtquant.account_type", "STOCK") or "STOCK")
    account_type = account_type.strip().upper() or "STOCK"
    account = stock_account_cls(account_id, account_type)
    return account, account_id, account_type

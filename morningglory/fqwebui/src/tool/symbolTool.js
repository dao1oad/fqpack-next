const _M = {}

_M.isStock = function (symbol) {
  symbol = symbol.toUpperCase()
  return symbol.indexOf('SH') === 0 || symbol.indexOf('SZ') === 0
}

export default _M

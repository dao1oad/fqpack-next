const _M = {}

_M.getUrlQueryParams = function (url) {
  const params = {}
  const searchParams = new URLSearchParams(new URL(url).search)
  for (const [key, value] of searchParams) {
    params[key] = value
  }
  return params
}

_M.getLocationQueryParams = function () {
  return _M.getUrlQueryParams(window.location.href)
}

_M.getParam = function (name) {
  return _M.getLocationQueryParams()[name]
}

export default _M

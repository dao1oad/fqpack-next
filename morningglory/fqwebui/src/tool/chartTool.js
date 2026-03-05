const _M = {}

_M.currentChartGet = function (vueComp, period) {
  if (period === '1d') {
    return vueComp.myChart1d
  } else if (period === '5m') {
    return vueComp.myChart5
  } else if (period === '15m') {
    return vueComp.myChart15
  } else if (period === '30m') {
    return vueComp.myChart30
  } else if (period === '60m') {
    return vueComp.myChart60
  } else if (period === '1m') {
    return vueComp.myChart1
  }
  return null
}

export default _M

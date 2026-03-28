import _ from 'lodash'
import echartsConfig from './echartsConfig'

export default (vueComp, klineData) => {
  const query = vueComp.$route.query
  const markLineData = []
  const entryLedger = klineData.entry_ledger || klineData.stock_fills
  // 当前价格
  vueComp.currentPrice = klineData.close[klineData.close.length - 1]
  // 1手需要的保证金
  if (query.symbol === 'BTC') {
    vueComp.marginPrice = (
      (0.01 * vueComp.currentPrice) /
            vueComp.marginLevel
    ).toFixed(2)
  } else {
    // 内盘 和外盘
    vueComp.marginPrice = (
      (vueComp.contractMultiplier * vueComp.currentPrice) /
            vueComp.marginLevel
    ).toFixed(2)
  }
  if (entryLedger) {
    // 跟据最新价格计算出来的信息
    let profitQuantity = 0
    let profitAmount = 0.0
    let color = echartsConfig.currentPriceColor
    for (const fill of entryLedger) {
      if (vueComp.currentPrice > fill.price) {
        profitQuantity = profitQuantity + fill.quantity
        profitAmount = profitAmount + fill.quantity * (vueComp.currentPrice - fill.price)
        const rate = (vueComp.currentPrice - fill.price) / fill.price
        if (rate >= 0.01) {
          color = echartsConfig.upColor
        }
      }
    }
    let currentInfo = ''
    if (profitQuantity > 0) {
      currentInfo = `获利数量: ${profitQuantity}\n获利金额: ${profitAmount.toFixed(2)}`
    }
    const markLineCurrent = {
      yAxis: vueComp.currentPrice,
      lineStyle: {
        opacity: 1,
        type: 'dashed',
        width: 1,
        color: 'yellow'
      },
      symbol: 'circle',
      symbolSize: 1,
      label: {
        color,
        formatter: `最新价格: ${vueComp.currentPrice.toFixed(3)}\n${currentInfo}`
      }
    }
    markLineData.push(markLineCurrent)
  }
  if (entryLedger) {
    const stockFills = _.reduce(entryLedger, (acc, cur) => {
      const item = _.find(acc, item => item.date === cur.date)
      if (item) {
        item.quantity = item.quantity + cur.quantity
        item.amount = item.amount + cur.price * cur.quantity
        item.price = item.amount / item.quantity
        if (cur.time > item.time) {
          item.time = cur.time
        }
      } else {
        acc.push({ date: cur.date, time: cur.time, quantity: cur.quantity, price: cur.price, amount: cur.price * cur.quantity })
      }
      return acc
    }, [])
    for (const fill of stockFills) {
      const rate = (vueComp.currentPrice - fill.price) / fill.price
      const quantity = fill.quantity
      const profit = (quantity * (vueComp.currentPrice - fill.price)).toFixed(
        2
      )
      markLineData.push({
        yAxis: fill.price.toFixed(3),
        lineStyle: {
          opacity: 1,
          type: 'dashed',
          width: 1,
          color:
                          rate >= 0.01
                            ? echartsConfig.upColor
                            : echartsConfig.downColor
        },
        symbol: 'circle',
        symbolSize: 1,
        label: {
          position: 'middle',
          color:
                          rate >= 0.01
                            ? echartsConfig.upColor
                            : echartsConfig.downColor,
          formatter: `价格: ${fill.price.toFixed(
                          3
                      )} 数量: ${quantity} 获利比率: ${(rate * 100).toFixed(
                          2
                      )}% 获利金额：${profit}`
        }
      })
    }
  }
  if (_.get(klineData, 'future_fills[0]')) {
    // 跟据最新价格计算出来的信息
    let profitQuantity = 0
    let profitAmount = 0.0
    let color = echartsConfig.currentPriceColor
    for (const fill of _.get(klineData, 'future_fills[0]')) {
      if (vueComp.currentPrice > fill.price) {
        profitQuantity = profitQuantity + fill.pos
        profitAmount = profitAmount + fill.pos * (vueComp.currentPrice - fill.price)
        const rate = (vueComp.currentPrice - fill.price) / fill.price
        if (rate >= 0.01) {
          color = echartsConfig.upColor
        }
      }
    }
    let currentInfo = ''
    if (profitQuantity > 0) {
      currentInfo = `获利数量: ${profitQuantity}\n获利点数: ${profitAmount.toFixed(2)}`
    }
    const markLineCurrent = {
      yAxis: vueComp.currentPrice,
      lineStyle: {
        opacity: 1,
        type: 'dashed',
        width: 1,
        color: 'yellow'
      },
      symbol: 'circle',
      symbolSize: 1,
      label: {
        color,
        formatter: `最新价格: ${vueComp.currentPrice.toFixed(3)}\n${currentInfo}`
      }
    }
    markLineData.push(markLineCurrent)
  }
  if (_.get(klineData, 'future_fills[0]')) {
    for (const fill of klineData.future_fills[0]) {
      const rate = (vueComp.currentPrice - fill.price) / fill.price
      const quantity = fill.pos
      const profit = (quantity * (vueComp.currentPrice - fill.price)).toFixed(
        2
      )
      markLineData.push({
        yAxis: fill.price,
        lineStyle: {
          opacity: 1,
          type: 'dashed',
          width: 1,
          color:
                          rate >= 0.01
                            ? echartsConfig.upColor
                            : echartsConfig.downColor
        },
        symbol: 'circle',
        symbolSize: 1,
        label: {
          position: 'middle',
          color:
                          rate >= 0.01
                            ? echartsConfig.upColor
                            : echartsConfig.downColor,
          formatter: `方向: 多  价格: ${fill.price.toFixed(
                          3
                      )}  数量: ${quantity}  获利比率: ${(rate * 100).toFixed(
                          2
                      )}%  获利点数：${profit}`
        }
      })
    }
  }
  if (_.get(klineData, 'future_fills[1]')) {
    for (const fill of klineData.future_fills[1]) {
      const rate = (fill.price - vueComp.currentPrice) / fill.price
      const quantity = fill.pos
      const profit = (quantity * (fill.price - vueComp.currentPrice)).toFixed(
        2
      )
      markLineData.push({
        yAxis: fill.price,
        lineStyle: {
          opacity: 1,
          type: 'dashed',
          width: 1,
          color:
                          rate >= 0.01
                            ? echartsConfig.upColor
                            : echartsConfig.downColor
        },
        symbol: 'circle',
        symbolSize: 1,
        label: {
          position: 'middle',
          color:
                          rate >= 0.01
                            ? echartsConfig.upColor
                            : echartsConfig.downColor,
          formatter: `方向: 空  价格: ${fill.price.toFixed(
                          3
                      )}  数量: ${quantity}  获利比率: ${(rate * 100).toFixed(
                          2
                      )}%  获利点数：${profit}`
        }
      })
    }
  }
  return markLineData
}

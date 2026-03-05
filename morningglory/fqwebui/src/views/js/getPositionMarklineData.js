import manba from 'manba'
import echartsConfig from './echartsConfig'

export default (vueComp, klineData) => {
  const query = vueComp.$route.query
  const markLineData = []
  // 开仓价格
  const openPrice = vueComp.currentPosition.price
  const openAmount = vueComp.currentPosition.amount
  const direction = vueComp.currentPosition.direction
  // 当前价格
  vueComp.currentPrice = klineData.close[klineData.close.length - 1]
  // 合约乘数
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
  // 止损价格
  const stopLosePrice = vueComp.currentPosition.stop_lose_price
  // 当前盈利百分比
  let currentPercent = ''
  if (direction === 'long') {
    currentPercent = (
      ((vueComp.currentPrice - openPrice) / openPrice) *
            100 *
            vueComp.marginLevel
    ).toFixed(2)
  } else {
    currentPercent = (
      ((openPrice - vueComp.currentPrice) / openPrice) *
            100 *
            vueComp.marginLevel
    ).toFixed(2)
  }
  // 止损百分比
  const stopLosePercent = (
    (Math.abs(openPrice - stopLosePrice) / stopLosePrice) *
        100 *
        vueComp.marginLevel
  ).toFixed(2)
  // 如果中间做过动止，加仓，又没有平今的话，持仓成本是变动的，因此这个盈利率和盈亏比只是跟据开仓价来计算的
  const targetPercent = (
    (Math.abs(openPrice - stopLosePrice) / openPrice) *
        100 *
        vueComp.marginLevel
  ).toFixed(2)
  // 单位是万
  const currentProfit = (
    (openAmount * vueComp.marginPrice * Number(currentPercent)) /
        100 /
        10000
  ).toFixed(2)
  // 动止算法2     动止百分比 = 1/(1+盈亏比)
  let dynamicWinCount
  if (currentPercent <= 0) {
    dynamicWinCount = 0
  } else {
    dynamicWinCount = Math.ceil(
      openAmount * (1 / (1 + currentPercent / targetPercent))
    )
  }

  vueComp.currentInfo =
        ' 率: ' +
        currentPercent +
        '% 额: ' +
        currentProfit +
        ' 万,盈亏比:' +
        Math.abs((currentPercent / targetPercent).toFixed(1)) +
        ' 新: ' +
        vueComp.currentPrice.toFixed(2) +
        ' 动止: ' +
        dynamicWinCount +
        ' 开仓时间：' +
        vueComp.currentPosition.fire_time +
        ' ' +
        vueComp.currentPosition.period +
        ' ' +
        vueComp.currentPosition.signal

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
      color: echartsConfig.currentPriceColor,
      formatter: '新: ' + vueComp.currentPrice.toFixed(3)
    }
  }
  markLineData.push(markLineCurrent)
  // 开仓价
  const markLineOpen = {
    yAxis: openPrice,
    lineStyle: {
      opacity: 1,
      type: 'dashed',
      width: 1,
      color: 'white'
    },
    symbol: 'circle',
    symbolSize: 1,
    label: {
      color: 'white',
      formatter:
                  '开: ' +
                  openPrice.toFixed(3) +
                  ' ' +
                  vueComp.dynamicDirectionMap[direction] +
                  ': ' +
                  openAmount +
                  ' 手'
    }
  }
  markLineData.push(markLineOpen)

  // 止损线
  const markLineStop = {
    yAxis: stopLosePrice,
    lineStyle: {
      opacity: 1,
      type: 'dashed',
      width: 1,
      color: echartsConfig.upColor
    },
    symbol: 'circle',
    symbolSize: 1,
    label: {
      color: echartsConfig.upColor,
      formatter:
                  '止: ' +
                  stopLosePrice.toFixed(3) +
                  ' 率: -' +
                  stopLosePercent +
                  '%'
    }
  }
  markLineData.push(markLineStop)
  if (vueComp.currentPosition.hasOwnProperty('dynamicPositionList')) {
    // 动止记录
    for (
      let i = 0;
      i < vueComp.currentPosition.dynamicPositionList.length;
      i++
    ) {
      // 数量
      const dynamicItem = vueComp.currentPosition.dynamicPositionList[i]
      // let dynamicPercent = (Math.abs(dynamicItem.price - openPrice) / openPrice * 100 * marginLevel).toFixed(2)
      const stop_win_count = dynamicItem.stop_win_count
      const direction = vueComp.dynamicDirectionMap[dynamicItem.direction]
      const markLineObj = {
        yAxis: dynamicItem.stop_win_price,
        lineStyle: {
          opacity: 1,
          type: 'dashed',
          width: 1,
          color: echartsConfig.dynamicOpertionColor
        },
        label: {
          color: echartsConfig.dynamicOpertionColor,
          formatter:
                          '动止: ' +
                          manba(dynamicItem.date_created).format('MM-DD HH:mm') +
                          ' ' +
                          dynamicItem.stop_win_price +
                          ' ' +
                          direction +
                          ' ' +
                          stop_win_count +
                          '手' +
                          ' 额：' +
                          dynamicItem.stop_win_money,
          position: 'insideEndTop'
        },
        symbol: 'circle',
        symbolSize: 1
      }
      markLineData.push(markLineObj)
    }
  }
  let higherBottomPrice = 0
  let higherHigherBottomPrice = 0
  let higherTopPrice = 0
  let higherHigherTopPrice = 0
  //  多单查找顶型
  if (direction === 'long') {
    if (
      JSON.stringify(klineData.fractal[0]) !== '{}' &&
            klineData.fractal[0].direction === 1
    ) {
      higherBottomPrice = klineData.fractal[0].top_fractal.bottom
      // 高级别分型线
      const markLineFractal = {
        yAxis: higherBottomPrice,
        lineStyle: {
          opacity: 1,
          type: 'dashed',
          width: 1,
          color: echartsConfig.higherColor
        },
        symbol: 'circle',
        symbolSize: 1,
        label: {
          color: echartsConfig.higherColor,
          formatter:
                          '顶: ' + klineData.fractal[0].period + ' ' + higherBottomPrice,
          position: 'insideMiddleTop'
        }
      }
      markLineData.push(markLineFractal)
    }
    if (
      JSON.stringify(klineData.fractal[1]) !== '{}' &&
            klineData.fractal[1].direction === 1
    ) {
      higherHigherBottomPrice = klineData.fractal[1].top_fractal.bottom
      // 高高级别分型线
      const markLineFractal = {
        yAxis: higherHigherBottomPrice,
        lineStyle: {
          opacity: 1,
          type: 'dashed',
          width: 1,
          color: echartsConfig.higherHigherColor
        },
        symbol: 'circle',
        symbolSize: 1,
        label: {
          color: echartsConfig.higherHigherColor,
          formatter:
                          '顶: ' +
                          klineData.fractal[1].period +
                          ' ' +
                          higherHigherBottomPrice,
          position: 'insideMiddleBottom'
        }
      }
      markLineData.push(markLineFractal)
    }
  } else {
    // 空单查找底分型
    if (
      JSON.stringify(klineData.fractal[0]) !== '{}' &&
            klineData.fractal[0].direction === -1
    ) {
      higherTopPrice = klineData.fractal[0].bottom_fractal.top
      // 高级别分型线
      const markLineFractal = {
        yAxis: higherTopPrice,
        lineStyle: {
          opacity: 1,
          type: 'dashed',
          width: 1,
          color: echartsConfig.higherColor
        },
        symbol: 'circle',
        symbolSize: 1,
        label: {
          color: echartsConfig.higherColor,
          formatter:
                          '底: ' + klineData.fractal[0].period + ' ' + higherTopPrice,
          position: 'insideMiddleBottom'
        }
      }
      markLineData.push(markLineFractal)
    }
    if (
      JSON.stringify(klineData.fractal[1]) !== '{}' &&
            klineData.fractal[1].direction === -1
    ) {
      higherHigherTopPrice = klineData.fractal[1].bottom_fractal.top
      // 高高级别分型线
      const markLineFractal = {
        yAxis: higherHigherTopPrice,
        lineStyle: {
          opacity: 1,
          type: 'dashed',
          width: 1,
          color: echartsConfig.higherHigherColor
        },
        symbol: 'circle',
        symbolSize: 1,
        label: {
          color: echartsConfig.higherHigherColor,
          formatter:
                          '底: ' +
                          klineData.fractal[1].period +
                          ' ' +
                          higherHigherTopPrice,
          position: 'insideMiddleTop'
        }
      }
      markLineData.push(markLineFractal)
    }
  }
  return markLineData
}

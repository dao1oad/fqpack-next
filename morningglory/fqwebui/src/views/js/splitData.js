import getMarklineData from './getMarklineData'
import getPositionMarklineData from './getPositionMarklineData'
import get_macd_divergence_markpoint_data from './get_macd_divergence_markpoint_data'
import manba from 'manba'
import echartsConfig from './echartsConfig'
import { ema, multiplyBy, subtract } from 'indicatorts'

const macdMupltipliers = {
  '1m': 5,
  '3m': 5,
  '5m': 6,
  '15m': 4,
  '30m': 8,
  '60m': 8,
  '120m': 8,
  '1d': 5
}

function macdMupltiplierGet (period) {
  return macdMupltipliers[period] || 5
}

export default (vueComp, klineData) => {
  const stockDate = klineData.date
  const stockHigh = klineData.high
  const stockLow = klineData.low
  const stockOpen = klineData.open
  const stockClose = klineData.close
  const volumeData = klineData.volume

  const bidata = klineData.bidata
  const duandata = klineData.duandata
  const higherDuanData = klineData.higherDuanData

  const zsdata = klineData.zsdata
  const zsflag = klineData.zsflag

  const duan_zsdata = klineData.duan_zsdata
  const duan_zsflag = klineData.duan_zsflag

  const higher_duan_zsdata = klineData.higher_duan_zsdata
  const higher_duan_zsflag = klineData.higher_duan_zsflag

  const values = []
  for (let i = 0; i < stockDate.length; i++) {
    values.push([stockOpen[i], stockClose[i], stockLow[i], stockHigh[i]])
  }

  const EMA12 = ema(stockClose, { period: 12 })
  const EMA26 = ema(stockClose, { period: 26 })
  const DIF = subtract(EMA12, EMA26)
  const DEA = ema(DIF, { period: 9 })
  const MACD = multiplyBy(2, subtract(DIF, DEA))
  const n = macdMupltiplierGet(klineData.period)
  const EMA12_B = ema(stockClose, { period: 12 * n })
  const EMA26_B = ema(stockClose, { period: 26 * n })
  const DIF_B = subtract(EMA12_B, EMA26_B)
  const DEA_B = ema(DIF_B, { period: 9 * n })
  const MACD_B = multiplyBy(2, subtract(DIF_B, DEA_B))

  // 笔数据
  const biValues = []
  for (let i = 0; i < bidata.date.length; i++) {
    biValues.push([bidata.date[i], bidata.data[i]])
  }
  // 段数据
  const duanValues = []
  for (let i = 0; i < duandata.date.length; i++) {
    duanValues.push([duandata.date[i], duandata.data[i]])
  }
  // 段的端点价格数据
  const duanPriceValues = []
  for (let i = 0; i < duandata.date.length; i++) {
    let value = {}
    if (i > 0 && duandata.data[i] > duandata.data[i - 1]) {
      value = {
        coord: [duandata.date[i], duandata.data[i]],
        value: duandata.data[i],
        symbolRotate: 0,
        symbolSize: 5,
        symbol: 'circle',
        itemStyle: {
          color: echartsConfig.downColor
        },
        label: {
          position: 'inside',
          offset: [0, -10],
          textBorderColor: echartsConfig.downColor,
          textBorderWidth: 2,
          color: 'white'
        }
      }
    } else {
      value = {
        coord: [duandata.date[i], duandata.data[i]],
        value: duandata.data[i],
        symbolRotate: 0,
        symbolSize: 5,
        symbol: 'circle',
        itemStyle: {
          color: echartsConfig.upColor
        },
        label: {
          position: 'inside',
          offset: [0, 10],
          textBorderColor: echartsConfig.upColor,
          textBorderWidth: 2,
          color: 'white'
        }
      }
    }
    duanPriceValues.push(value)
  }

  const higherDuanValues = []
  for (let i = 0; i < higherDuanData.date.length; i++) {
    higherDuanValues.push([higherDuanData.date[i], higherDuanData.data[i]])
  }

  // 中枢数据
  const zsvalues = []
  for (let i = 0; i < zsdata.length; i++) {
    let value
    if (zsflag[i] > 0) {
      // 上涨中枢
      value = [
        {
          coord: zsdata[i][0],
          itemStyle: {
            color: echartsConfig.upColor,
            borderWidth: '2',
            borderColor: 'red',
            opacity: 0.2
          }
        },
        {
          coord: zsdata[i][1],
          itemStyle: {
            color: echartsConfig.upColor,
            borderWidth: '1',
            borderColor: echartsConfig.upColor,
            opacity: 0.2
          }
        }
      ]
    } else {
      // 下跌中枢
      value = [
        {
          coord: zsdata[i][0],
          itemStyle: {
            color: echartsConfig.downColor,
            borderWidth: '1',
            borderColor: echartsConfig.downColor,
            opacity: 0.2
          }
        },
        {
          coord: zsdata[i][1],
          itemStyle: {
            color: echartsConfig.downColor,
            borderWidth: '1',
            borderColor: echartsConfig.downColor,
            opacity: 0.2
          }
        }
      ]
    }
    zsvalues.push(value)
  }
  // 段中枢
  for (let i = 0; i < duan_zsdata.length; i++) {
    let value
    if (duan_zsflag[i] > 0) {
      // 上涨中枢
      value = [
        {
          coord: duan_zsdata[i][0],
          itemStyle: {
            color: echartsConfig.higherUpColor,
            borderWidth: '2',
            borderColor: echartsConfig.higherUpColor,
            opacity: 0.2
          }
        },
        {
          coord: duan_zsdata[i][1],
          itemStyle: {
            color: echartsConfig.higherUpColor,
            borderWidth: '1',
            borderColor: echartsConfig.higherUpColor,
            opacity: 0.2
          }
        }
      ]
    } else {
      // 下跌中枢
      value = [
        {
          coord: duan_zsdata[i][0],
          itemStyle: {
            color: echartsConfig.higherDownColor,
            borderWidth: '1',
            borderColor: echartsConfig.higherDownColor,
            opacity: 0.2
          }
        },
        {
          coord: duan_zsdata[i][1],
          itemStyle: {
            color: echartsConfig.higherDownColor,
            borderWidth: '1',
            borderColor: echartsConfig.higherDownColor,
            opacity: 0.2
          }
        }
      ]
    }
    zsvalues.push(value)
  }
  // 高级别段中枢
  for (let i = 0; i < higher_duan_zsdata.length; i++) {
    let value
    if (higher_duan_zsflag[i] > 0) {
      // 上涨中枢
      value = [
        {
          coord: higher_duan_zsdata[i][0],
          itemStyle: {
            color: echartsConfig.higherHigherUpColor,
            borderWidth: '2',
            borderColor: echartsConfig.higherHigherUpColor,
            opacity: 0.1
          }
        },
        {
          coord: higher_duan_zsdata[i][1],
          itemStyle: {
            color: echartsConfig.higherHigherUpColor,
            borderWidth: '1',
            borderColor: echartsConfig.higherHigherUpColor,
            opacity: 0.1
          }
        }
      ]
    } else {
      // 下跌中枢
      value = [
        {
          coord: higher_duan_zsdata[i][0],
          itemStyle: {
            color: echartsConfig.higherHigherDownColor,
            borderWidth: '1',
            borderColor: echartsConfig.higherHigherDownColor,
            opacity: 0.1
          }
        },
        {
          coord: higher_duan_zsdata[i][1],
          itemStyle: {
            color: echartsConfig.higherHigherDownColor,
            borderWidth: '1',
            borderColor: echartsConfig.higherHigherDownColor,
            opacity: 0.1
          }
        }
      ]
    }
    zsvalues.push(value)
  }

  // 中枢拉回
  const markPointValues = []
  if (klineData.buy_zs_huila) {
    for (let i = 0; i < klineData.buy_zs_huila.datetime.length; i++) {
      const value = {
        coord: [klineData.buy_zs_huila.datetime[i].substring(0, 16), klineData.buy_zs_huila.price[i]],
        value: klineData.buy_zs_huila.price[i] + klineData.buy_zs_huila.tag[i],
        symbolRotate: -90,
        symbol: 'circle',
        symbolSize: 10,
        symbolOffset: [0, '0%'],
        itemStyle: {
          color: echartsConfig.upColor,
          opacity: '0.9'
        },
        label: {
          // position: ['-50%','50%'],
          position: 'inside',
          offset: [5, 5],
          textBorderColor: 'red',
          textBorderWidth: 3,
          color: 'white'
          // borderColor: 'blue',
          // borderWidth: 1,
        }
      }
      markPointValues.push(value)
    }
  }
  if (klineData.sell_zs_huila) {
    for (let i = 0; i < klineData.sell_zs_huila.datetime.length; i++) {
      const value = {
        coord: [klineData.sell_zs_huila.datetime[i].substring(0, 16), klineData.sell_zs_huila.price[i]],
        value: klineData.sell_zs_huila.price[i] + klineData.sell_zs_huila.tag[i],
        symbolRotate: 90,
        symbol: 'circle',
        symbolSize: 10,
        symbolOffset: [0, '0%'],
        itemStyle: {
          color: echartsConfig.downColor,
          opacity: '0.9'
        },
        label: {
          // position: ['-50%','50%'],
          position: 'inside',
          offset: [-5, 5],
          textBorderColor: 'red',
          textBorderWidth: 3,
          color: 'white'
          // borderColor: 'blue',
          // borderWidth: 1,
        }
      }
      markPointValues.push(value)
    }
  }
  // 中枢突破
  if (klineData.buy_zs_tupo) {
    for (let i = 0; i < klineData.buy_zs_tupo.date.length; i++) {
      const value = {
        coord: [klineData.buy_zs_tupo.date[i], klineData.buy_zs_tupo.data[i]],
        value: klineData.buy_zs_tupo.data[i] + klineData.buy_zs_tupo.tag[i],
        symbolRotate: 0,
        symbol: 'circle',
        symbolSize: 10,
        symbolOffset: [0, '0%'],
        itemStyle: {
          color: echartsConfig.upColor,
          opacity: '0.9'
        },
        label: {
          // position: ['-50%','50%'],
          position: 'inside',
          offset: [0, 5],
          textBorderColor: 'red',
          textBorderWidth: 3,
          color: 'white'
          // borderColor: 'blue',
          // borderWidth: 1,
        }
      }
      markPointValues.push(value)
    }
  }

  if (klineData.sell_zs_tupo) {
    for (let i = 0; i < klineData.sell_zs_tupo.date.length; i++) {
      const value = {
        coord: [klineData.sell_zs_tupo.date[i], klineData.sell_zs_tupo.data[i]],
        value: klineData.sell_zs_tupo.data[i] + klineData.sell_zs_tupo.tag[i],
        symbolRotate: 180,
        symbolSize: 10,
        symbol: 'circle',
        symbolOffset: [0, '0%'],
        itemStyle: {
          color: echartsConfig.downColor,
          opacity: '0.9'
        },
        label: {
          // position: ['-50%','50%'],
          position: 'inside',
          offset: [0, 5],
          textBorderColor: 'red',
          textBorderWidth: 3,
          color: 'white'
          // borderColor: 'blue',
          // borderWidth: 1,
        }
      }
      markPointValues.push(value)
    }
  }
  // 3买卖V反
  if (klineData.buy_v_reverse) {
    for (let i = 0; i < klineData.buy_v_reverse.datetime.length; i++) {
      const value = {
        coord: [klineData.buy_v_reverse.datetime[i].substring(0, 16), klineData.buy_v_reverse.price[i]],
        value: klineData.buy_v_reverse.price[i] + klineData.buy_v_reverse.tag[i],
        symbolRotate: 0,
        symbol: 'circle',
        symbolSize: 10,
        symbolOffset: [0, '0%'],
        itemStyle: {
          color: echartsConfig.upColor,
          opacity: '0.9'
        },
        label: {
          // position: ['-50%','50%'],
          position: 'inside',
          offset: [0, 5],
          textBorderColor: 'red',
          textBorderWidth: 3,
          color: 'white'
          // borderColor: 'blue',
          // borderWidth: 1,
        }
      }
      markPointValues.push(value)
    }
  }

  if (klineData.sell_v_reverse) {
    for (let i = 0; i < klineData.sell_v_reverse.datetime.length; i++) {
      const value = {
        coord: [
          klineData.sell_v_reverse.datetime[i].substring(0, 16),
          klineData.sell_v_reverse.price[i]
        ],
        value: klineData.sell_v_reverse.price[i] + klineData.sell_v_reverse.tag[i],
        symbolRotate: 180,
        symbolSize: 10,
        symbol: 'circle',
        symbolOffset: [0, '0%'],
        itemStyle: {
          color: echartsConfig.downColor,
          opacity: '0.9'
        },
        label: {
          // position: ['-50%','50%'],
          position: 'inside',
          offset: [0, 5],
          textBorderColor: 'red',
          textBorderWidth: 3,
          color: 'white'
          // borderColor: 'blue',
          // borderWidth: 1,
        }
      }
      markPointValues.push(value)
    }
  }

  // 线段破坏
  if (klineData.buy_duan_break) {
    for (let i = 0; i < klineData.buy_duan_break.date.length; i++) {
      const value = {
        coord: [
          klineData.buy_duan_break.date[i],
          klineData.buy_duan_break.data[i]
        ],
        value: klineData.buy_duan_break.data[i] + klineData.buy_duan_break.tag[i],
        symbolRotate: 0,
        symbol: 'circle',
        symbolSize: 10,
        symbolOffset: [0, '0%'],
        itemStyle: {
          color: echartsConfig.upColor,
          opacity: '0.9'
        },
        label: {
          // position: ['-50%','50%'],
          position: 'inside',
          offset: [0, 5],
          textBorderColor: 'red',
          textBorderWidth: 3,
          color: 'white'
          // borderColor: 'blue',
          // borderWidth: 1,
        }
      }
      markPointValues.push(value)
    }
  }

  if (klineData.sell_duan_break) {
    for (let i = 0; i < klineData.sell_duan_break.date.length; i++) {
      const value = {
        coord: [
          klineData.sell_duan_break.date[i],
          klineData.sell_duan_break.data[i]
        ],
        value:
                    klineData.sell_duan_break.data[i] + klineData.sell_duan_break.tag[i],
        symbolRotate: 180,
        symbolSize: 10,
        symbol: 'circle',
        symbolOffset: [0, '0%'],
        itemStyle: {
          color: echartsConfig.downColor,
          opacity: '0.9'
        },
        label: {
          // position: ['-50%','50%'],
          position: 'inside',
          offset: [0, 5],
          textBorderColor: 'red',
          textBorderWidth: 3,
          color: 'white'
          // borderColor: 'blue',
          // borderWidth: 1,
        }
      }
      markPointValues.push(value)
    }
  }

  const entryLedger = klineData.entry_ledger || klineData.stock_fills
  if (entryLedger) {
    for (let i = 0; i < entryLedger.length; i++) {
      const fill = entryLedger[i]
      let dt = manba(`${fill.date} ${fill.time}`, 'YYYYMMDD HH:mm:ss').format('YYYY-MM-DD HH:mm')
      for (let j = 0; j < stockDate.length; j++) {
        if (stockDate[j] >= dt) {
          dt = stockDate[j]
          break
        }
      }
      const value = {
        coord: [dt, fill.price - 0.01],
        value: `${fill.price}`,
        symbolSize: 20,
        symbol: 'triangle',
        symbolOffset: [0, '80%'],
        z: 100,
        itemStyle: {
          color: echartsConfig.upColor,
          opacity: '0.9'
        },
        label: {
          position: 'bottom',
          offset: [0, 5],
          textBorderColor: 'red',
          textBorderWidth: 3,
          color: 'white'
        }
      }
      markPointValues.push(value)
    }
  }
  // MACD背驰
  const macd_divergence_markpoint_values = get_macd_divergence_markpoint_data(klineData, DIF)

  let markLineData
  if (vueComp.isPosition === 'true') {
    markLineData = getPositionMarklineData(vueComp, klineData)
  } else {
    markLineData = getMarklineData(vueComp, klineData)
  }
  return {
    date: stockDate,
    values,
    volume: volumeData,
    biValues,
    duanValues,
    duanPriceValues,
    higherDuanValues,
    zsvalues,
    zsflag,
    close: stockClose,
    markLineData,
    markPointValues,
    macd_divergence_markpoint_values,
    notLower: klineData.notLower,
    notHigher: klineData.notHigher,
    MACD,
    DIF,
    DEA,
    MACD_B,
    DIF_B,
    DEA_B
  }
}

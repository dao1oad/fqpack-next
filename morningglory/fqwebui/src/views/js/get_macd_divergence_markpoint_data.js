import echartsConfig from './echartsConfig'

/**
 * 创建一个处理背离标记点的通用函数
 * @param {object} divergence_data - 背离数据，如 kline_data.macd_bullish_divergence
 * @param {Array<number>} dif - DIF 数据线
 * @param {object} config - 标记点的特定配置
 * @returns {Array<object>} - 生成的标记点数组
 */
function create_divergence_markpoints (divergence_data, dif, config) {
  const markpoints = []
  // 将检查逻辑前置，不满足条件直接返回空数组
  if (
    !divergence_data ||
    !Array.isArray(divergence_data.datetime) ||
    !Array.isArray(divergence_data.idx) ||
    divergence_data.datetime.length !== divergence_data.idx.length
  ) {
    return markpoints
  }

  for (let i = 0; i < divergence_data.datetime.length; i++) {
    const time = divergence_data.datetime[i]
    const index = divergence_data.idx[i]

    if (index >= 0 && index < dif.length) {
      const point = {
        coord: [time.substring(0, 16), dif[index]],
        value: config.value,
        symbolRotate: config.symbol_rotate,
        symbol: 'arrow',
        symbolSize: 10,
        symbolOffset: config.symbol_offset,
        itemStyle: {
          color: config.color,
          opacity: '0.9'
        },
        label: {
          position: 'inside',
          offset: config.label_offset,
          textBorderColor: config.color,
          textBorderWidth: 2,
          color: 'white'
        }
      }
      markpoints.push(point)
    }
  }
  return markpoints
}

export default function (kline_data, dif) {
  const { macd_bullish_divergence, macd_bearish_divergence } = kline_data

  // 看涨背离的特定配置
  const bullish_config = {
    value: '看涨背驰',
    symbol_rotate: 0,
    symbol_offset: [0, '50%'],
    color: echartsConfig.upColor,
    label_offset: [0, -10]
  }

  // 看跌背离的特定配置
  const bearish_config = {
    value: '看跌背驰',
    symbol_rotate: 180,
    symbol_offset: [0, '-50%'],
    color: echartsConfig.downColor,
    label_offset: [0, 10]
  }

  const bullish_markpoints = create_divergence_markpoints(macd_bullish_divergence, dif, bullish_config)
  const bearish_markpoints = create_divergence_markpoints(macd_bearish_divergence, dif, bearish_config)

  // 合并两种背离的标记点
  return [...bullish_markpoints, ...bearish_markpoints]
}

import splitData from './splitData'
import { sma } from 'indicatorts'
import echartsConfig from './echartsConfig'
import chartTool from '@/tool/chartTool'

export default (vueComp, klineData, period) => {
  const query = vueComp.$route.query
  const resultData = splitData(vueComp, klineData)
  const dataTitle = `${query.symbol} ${klineData.name} ${period}`
  const subText = `杠杆: ${vueComp.marginLevel}   保证金: ${vueComp.marginPrice}  乘数: ${vueComp.contractMultiplier}  ` +
    `线段前高：${resultData.notHigher ? '下' : '上'} 线段前低：${resultData.notLower ? '上' : '下'}  ${vueComp.currentInfo || ''}`
  const currentChart = query.period ? vueComp.myChart : chartTool.currentChartGet(vueComp, period)
  if (!currentChart) {
    return
  }
  let specialMA5 = 5
  let specialMA34 = 34
  let specialMA55 = 55
  // 5日  20日 均线
  // 内盘 每天交易时间 6小时， 外盘交易时间24小时  ,
  if (vueComp.globalFutureSymbol.indexOf(query.symbol) !== -1) {
    // 其中 ZM ZS ZL 是18小时
    if (
      query.symbol === 'S' ||
            query.symbol === 'SM' ||
            query.symbol === 'BO'
    ) {
      switch (period) {
        case '1m':
          specialMA5 = 5400
          specialMA34 = 21600
          break
        case '1d':
          specialMA5 = 5
          specialMA34 = 34
          break
        case '5m':
          specialMA5 = 1080
          specialMA34 = 4320
          break
        case '15m':
          specialMA5 = 360
          specialMA34 = 1440
          break
        case '30m':
          // 5 * 48 = 240
          // 20 *48 = 960
          specialMA5 = 180
          specialMA34 = 720
          break
        case '60m':
          // 5*18 = 90
          // 20*18 = 360
          specialMA5 = 90
          specialMA34 = 360
          break
        case '180m':
          // 180
          specialMA5 = 30
          specialMA34 = 120
          break
      }
    } else {
      switch (period) {
        case '1m':
          specialMA5 = 7200
          specialMA34 = 28800
          break
        case '1d':
          specialMA5 = 5
          specialMA34 = 34
          break
        case '5m':
          specialMA5 = 1440
          specialMA34 = 5760
          break
        case '15m':
          specialMA5 = 480
          specialMA34 = 1920
          break
        case '30m':
          // 5 * 48 = 240
          // 20 *48 = 960
          specialMA5 = 240
          specialMA34 = 960
          break
        case '60m':
          // 5*24 = 120
          // 20*24 = 480
          specialMA5 = 120
          specialMA34 = 480
          break
        case '180m':
          // 180
          specialMA5 = 40
          specialMA34 = 160
          break
      }
    }
  } else {
    // 4小时
    const _4HourSymbolList = ['AP', 'CJ', 'UR', 'JD']
    // 6小时
    // const _6HourSymbolList = []
    // 8小时
    const _8HourSymbolList = ['NI', 'ZN']
    const _9_5HourSymbolList = ['AG', 'AU']

    const simpleSymbol = query.symbol.replace(/[0-9]/g, '')
    let baseHour = 6

    const _5base = 5
    const _34base = 34
    const _55base = 55
    if (_4HourSymbolList.indexOf(simpleSymbol) !== -1) {
      baseHour = 4
    } else if (_8HourSymbolList.indexOf(simpleSymbol) !== -1) {
      baseHour = 8
    } else if (_9_5HourSymbolList.indexOf(simpleSymbol) !== -1) {
      baseHour = 9.5
    } else {
      baseHour = 6
    }
    switch (period) {
      case '1m':
        specialMA5 = _5base * baseHour * 2 * 2 * 5 * 3
        specialMA34 = _34base * baseHour * 2 * 2 * 5 * 3
        specialMA55 = _55base * baseHour * 2 * 2 * 5 * 3
        break
      case '1d':
        specialMA5 = _5base
        specialMA34 = _34base
        specialMA55 = _55base
        break
      case '5m':
        specialMA5 = _5base * baseHour * 2 * 2 * 3
        specialMA34 = _34base * baseHour * 2 * 2 * 3
        specialMA55 = _55base * baseHour * 2 * 2 * 3
        break
      case '15m':
        specialMA5 = _5base * baseHour * 2 * 2
        specialMA34 = _34base * baseHour * 2 * 2
        specialMA55 = _55base * baseHour * 2 * 2
        break
      case '30m':
        // 5 * 8 = 40
        // 20 *8 = 160
        specialMA5 = _5base * baseHour * 2
        specialMA34 = _34base * baseHour * 2
        specialMA55 = _55base * baseHour * 2
        break
      case '60m':
        // 5*4 = 20
        // 20*4 = 80
        specialMA5 = _5base * baseHour
        specialMA34 = _34base * baseHour
        specialMA55 = _55base * baseHour
        break
      case '180m':
        // 180
        specialMA5 = (_5base * baseHour) / 3
        specialMA34 = (_34base * baseHour) / 3
        specialMA55 = (_55base * baseHour) / 3
        console.log('内盘', specialMA5, specialMA34, specialMA55)
        break
    }
  }
  let option = currentChart.getOption()
  if (option) {
    option.title = {
      text: dataTitle,
      subtext: subText,
      left: '2%',
      textStyle: {
        color: 'white'
      }
    }
    option.series[0].data = resultData.values
    option.series[0].markArea.data = resultData.zsvalues
    option.series[0].markLine.data = resultData.markLineData
    option.series[0].markPoint.data = resultData.markPointValues
    option.series[1].data = resultData.biValues
    option.series[2].data = resultData.duanValues
    option.series[2].markPoint.data = resultData.duanPriceValues
    option.series[3].data = resultData.higherDuanValues
    option.series[4].data = sma(resultData.values.map(x => x[1]), { period: specialMA5 })
    option.series[5].data = sma(resultData.values.map(x => x[1]), { period: specialMA34 })
    option.series[6].data = sma(resultData.values.map(x => x[1]), { period: specialMA55 })
    option.series[7].data = resultData.MACD
    option.series[8].data = resultData.DIF
    option.series[9].data = resultData.DEA
    option.series[10].data = resultData.MACD_B
    option.series[11].data = resultData.DIF_B
    option.series[12].data = resultData.DEA_B
    option.xAxis[0].data = resultData.date
    option.xAxis[1].data = resultData.date
    option.xAxis[2].data = resultData.date
  } else {
    option = {
      animation: false,
      backgroundColor: echartsConfig.bgColor,
      title: {
        text: dataTitle,
        subtext: subText,
        left: '2%',
        textStyle: {
          color: 'white'
        }
      },
      tooltip: {
        // 提示框
        trigger: 'axis', // 触发类型：axis坐标轴触发,item
        axisPointer: {
          // 坐标轴指示器配置项
          type: 'cross' // 指示器类型，十字准星
        }
      },
      axisPointer: {
        link: { xAxisIndex: 'all' }
      },
      toolbox: {
        orient: 'horizontal',
        itemSize: 25,
        itemGap: 8,
        top: 16,
        right: '3%',
        feature: {
          myLevel1: {
            show: true,
            title: '放大',
            icon: 'image://' + vueComp.periodIcons[10],
            onclick: function () {
              vueComp.jumpToKlineBig(period)
            }
          }
        }
      },
      color: ['yellow', 'green', 'blue', 'white', 'yellow', 'red'],
      legend: {
        data: ['笔', '段', '高级别段', 'MA5', 'MA34', 'MA55'],
        selected: {
          笔: true,
          段: true,
          高级别段: true,
          MA5: true,
          MA34: true,
          MA55: true
          // 'markline': true
        },
        top: 10,
        textStyle: {
          color: 'white'
        }
      },
      grid: [
        {
          // 直角坐标系
          left: '0%',
          right: '10%',
          height: '57%',
          top: 50
        },
        {
          top: '65%',
          height: '20%',
          left: '0%',
          right: '10%'
        },
        {
          top: '80%',
          height: '15%',
          left: '0%',
          right: '10%'
        }
      ],
      xAxis: [
        {
          type: 'category',
          data: resultData.date,
          scale: true,
          boundaryGap: false,
          splitLine: { show: false },
          splitNumber: 20,
          min: 'dataMin',
          max: 'dataMax',
          axisLine: { onZero: true, lineStyle: { color: '#8392A5' } }
        },
        {
          type: 'category',
          gridIndex: 1,
          data: resultData.date,
          axisTick: {
            show: false
          },
          axisLabel: {
            show: false
          },
          axisLine: { lineStyle: { color: '#8392A5' } }
        },
        {
          type: 'category',
          gridIndex: 2,
          data: resultData.date,
          axisTick: {
            show: false
          },
          axisLabel: {
            show: false
          },
          axisLine: { lineStyle: { color: '#8392A5' } }
        }
      ],
      yAxis: [
        {
          scale: true,
          splitNumber: 10,
          splitArea: {
            show: false
          },
          splitLine: {
            lineStyle: {
              opacity: 0.3,
              type: 'dashed',
              color: echartsConfig.bgColor
            }
          },
          axisLine: { lineStyle: { color: echartsConfig.bgColor } },
          axisLabel: {
            show: true,
            formatter: function(value) {
              return value.toFixed(3)
            }
          }
        },
        // 本级别macd
        {
          gridIndex: 1,
          splitNumber: 2,
          axisTick: {
            show: false
          },
          splitLine: {
            show: false
          },
          axisLabel: {
            show: true
          },
          axisLine: { onZero: true, lineStyle: { color: '#8392A5' } }
        },
        // 大级别macd
        {
          gridIndex: 2,
          splitNumber: 2,
          axisTick: {
            show: false
          },
          splitLine: {
            show: false
          },
          axisLabel: {
            show: false
          },
          axisLine: {
            lineStyle: { color: '#8392A5' },
            onZero: false
          }
        }
        // 成交量
        // {
        //     gridIndex: 3,
        //     splitNumber: 1,
        //     axisLine: {
        //         onZero: false
        //     },
        //     axisTick: {
        //         show: false
        //     },
        //     splitLine: {
        //         show: false
        //     },
        //     axisLabel: {
        //         show: false
        //     },
        //     axisLine: {lineStyle: {color: '#8392A5'}},
        // },
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 0],
          start: 55,
          end: 100,
          minSpan: 10
        },
        {
          type: 'inside',
          xAxisIndex: [0, 1],
          start: 55,
          end: 100,
          minSpan: 10
        },
        {
          xAxisIndex: [0, 1, 2],
          type: 'inside',
          start: 55,
          end: 100,
          top: '95%',
          minSpan: 10,
          textStyle: {
            color: '#8392A5'
          },
          dataBackground: {
            areaStyle: {
              color: '#8392A5'
            },
            lineStyle: {
              opacity: 0.8,
              color: '#8392A5'
            }
          },
          handleStyle: {
            color: '#fff',
            shadowBlur: 3,
            shadowColor: 'rgba(0, 0, 0, 0.6)',
            shadowOffsetX: 2,
            shadowOffsetY: 2
          }
        }
      ],
      series: [
        {
          name: 'K线图',
          type: 'k',
          data: resultData.values,
          animation: false,
          itemStyle: {
            color: echartsConfig.upColor,
            color0: echartsConfig.downColor,
            borderColor: echartsConfig.upBorderColor,
            borderColor0: echartsConfig.downBorderColor
          },
          markPoint: {
            data: resultData.markPointValues,
            animation: false
          },
          markArea: {
            silent: true,
            data: resultData.zsvalues
          },
          markLine: {
            silent: true,
            data: resultData.markLineData,
            symbol: 'circle',
            symbolSize: 1
          }
        },
        {
          name: '笔',
          type: 'line',
          z: 1,
          data: resultData.biValues,
          lineStyle: {
            opacity: 1,
            type: 'dashed',
            width: 1,
            color: 'yellow'
          },
          symbol: 'none',
          animation: false
        },
        {
          name: '段',
          type: 'line',
          z: 1,
          data: resultData.duanValues,
          lineStyle: {
            opacity: 1,
            type: 'solid',
            width: 2,
            color: '#FF8000'
          },
          markPoint: {
            data: resultData.duanPriceValues
          },
          symbol: 'none',
          animation: false
        },
        {
          name: '高级别段',
          type: 'line',
          z: 1,
          data: resultData.higherDuanValues,
          lineStyle: {
            opacity: 1,
            type: 'solid',
            width: 2,
            color: '#FFAEC9'
          },
          symbol: 'none',
          animation: false
        },
        {
          name: 'MA5',
          type: 'line',
          data: sma(resultData.values.map(x => x[1]), { period: specialMA5 }),
          smooth: true,
          lineStyle: {
            opacity: 0.9,
            type: 'solid',
            width: 2,
            color: 'white'
          },
          symbol: 'none',
          animation: false
        },
        {
          name: 'MA34',
          type: 'line',
          data: sma(resultData.values.map(x => x[1]), { period: specialMA34 }),
          smooth: true,
          lineStyle: {
            opacity: 0.9,
            type: 'solid',
            width: 2,
            color: 'yellow'
          },
          symbol: 'none',
          animation: false
        },
        {
          name: 'MA55',
          type: 'line',
          data: sma(resultData.values.map(x => x[1]), { period: specialMA55 }),
          smooth: true,
          lineStyle: {
            opacity: 0.9,
            type: 'solid',
            width: 2,
            color: 'red'
          },
          symbol: 'none',
          animation: false
        },
        {
          name: 'MACD',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: resultData.MACD,
          barWidth: 2,
          itemStyle: {
            color: function (params) {
              let colorList
              if (params.data >= 0) {
                if (params.data >= echartsConfig.macdUpLastValue) {
                  colorList = echartsConfig.macdUpDarkColor
                } else {
                  colorList = echartsConfig.macdUpLightColor
                }
                echartsConfig.macdUpLastValue = params.data
              } else {
                if (params.data <= echartsConfig.macdDownLastValue) {
                  colorList = echartsConfig.macdDownDarkColor
                } else {
                  colorList = echartsConfig.macdDownLightColor
                }
                echartsConfig.macdDownLastValue = params.data
              }
              return colorList
            }
          }
        },
        {
          name: 'DIF',
          type: 'line',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: resultData.DIF,
          smooth: true,
          lineStyle: {
            opacity: 1,
            type: 'solid',
            width: 1,
            color: 'white'
          },
          markPoint: {
            data: resultData.macd_divergence_markpoint_values
          },
          symbol: 'none',
          animation: false
        },
        {
          name: 'DEA',
          type: 'line',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: resultData.DEA,
          smooth: true,
          lineStyle: {
            opacity: 1,
            type: 'solid',
            width: 1,
            color: 'yellow'
          },
          symbol: 'none',
          animation: false
        },
        // 大级别MACD
        {
          name: 'MACD_B',
          type: 'bar',
          xAxisIndex: 2,
          yAxisIndex: 2,
          data: resultData.MACD_B,
          barWidth: 3,
          itemStyle: {
            color: function (params) {
              let colorList

              if (params.data >= 0) {
                if (params.data >= echartsConfig.bigMacdUpLastValue) {
                  colorList = echartsConfig.macdUpDarkColor
                } else {
                  colorList = echartsConfig.macdUpLightColor
                }
                echartsConfig.bigMacdUpLastValue = params.data
              } else {
                if (params.data <= echartsConfig.bigMacdDownLastValue) {
                  colorList = echartsConfig.macdDownDarkColor
                } else {
                  colorList = echartsConfig.macdDownLightColor
                }
                echartsConfig.bigMacdDownLastValue = params.data
              }
              return colorList
            }
          }
        },
        {
          name: 'DIF_B',
          type: 'line',
          xAxisIndex: 2,
          yAxisIndex: 2,
          data: resultData.DIF_B,
          smooth: true,
          lineStyle: {
            opacity: 1,
            type: 'solid',
            width: 1,
            color: 'white'
          },
          symbol: 'none',
          animation: false
        },
        {
          name: 'DEA_B',
          type: 'line',
          xAxisIndex: 2,
          yAxisIndex: 2,
          data: resultData.DEA_B,
          smooth: true,
          lineStyle: {
            opacity: 1,
            type: 'solid',
            width: 1,
            color: 'yellow'
          },
          symbol: 'none',
          animation: false
        }
      ],
      graphic: []
    }
    if (query.period) {
      option.toolbox.feature = {}
    }
  }
  currentChart.setOption(option)
  currentChart.hideLoading()
}

<template>
  <div class="statistic-echarts-main">
    <div class="block">
      <el-date-picker
        placeholder="选择日期"
        v-model="dateRange"
        @change="getStatisticList()"
        format="yyyy 年 MM 月 dd 日"
        value-format="yyyy-MM-dd"
        type="daterange"
        align="right"
        unlink-panels
        range-separator="to"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        size="small"
        :picker-options="pickerOptions"
      >
      </el-date-picker>

      <el-button
        @click="getStatisticList()"
        type="primary"
        size="small"
        class="ml-5 primary-button"
        >刷新</el-button
      >
      <div class="signal-statistic">
        <table class="item">
          <thead>
            <tr>
              <th>
                信号
              </th>
              <th>
                盈利数
              </th>
              <th>
                亏损数
              </th>
              <th>
                胜率
              </th>
              <th>
                盈亏比
              </th>
              <th>
                期望
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>背驰</td>
              <td>{{ signal_result.beichi_win_count }}</td>
              <td>{{ signal_result.beichi_lose_count }}</td>
              <td>{{ signal_result.beichi_win_lose_count_rate }}%</td>
              <td>{{ signal_result.beichi_win_lose_money_rate }}</td>
              <td>
                {{
                  1 / (1 + signal_result.beichi_win_lose_money_rate) <
                  signal_result.beichi_win_lose_count_rate
                    ? '正'
                    : '负'
                }}
              </td>
            </tr>
            <tr>
              <td>破坏</td>
              <td>{{ signal_result.break_win_count }}</td>
              <td>{{ signal_result.break_lose_count }}</td>
              <td>{{ signal_result.break_win_lose_count_rate }}%</td>
              <td>{{ signal_result.break_win_lose_money_rate }}</td>
              <!--                <td>{{signal_result.break_win_lose_count_rate*signal_result.break_win_money -(1-signal_result.break_win_lose_count_rate)*signal_result.break_lose_money }}</td>-->
              <td>
                {{
                  1 / (1 + signal_result.break_win_lose_money_rate) <
                  signal_result.break_win_lose_count_rate
                    ? '正'
                    : '负'
                }}
              </td>
            </tr>
            <tr>
              <td>拉回</td>
              <td>{{ signal_result.huila_win_count }}</td>
              <td>{{ signal_result.huila_lose_count }}</td>
              <td>{{ signal_result.huila_win_lose_count_rate }}%</td>
              <td>{{ signal_result.huila_win_lose_money_rate }}</td>
              <!--                    <td>{{signal_result.huila_win_lose_count_rate*signal_result.huila_win_money -(1-signal_result.huila_win_lose_count_rate)*signal_result.huila_lose_money }}</td>-->
              <td>
                {{
                  1 / (1 + signal_result.huila_win_lose_money_rate) <
                  signal_result.huila_win_lose_count_rate
                    ? '正'
                    : '负'
                }}
              </td>
            </tr>
            <tr>
              <td>突破</td>
              <td>{{ signal_result.tupo_win_count }}</td>
              <td>{{ signal_result.tupo_lose_count }}</td>
              <td>{{ signal_result.tupo_win_lose_count_rate }}%</td>
              <td>{{ signal_result.tupo_win_lose_money_rate }}</td>
              <!--                    <td>{{signal_result.tupo_win_lose_count_rate*signal_result.tupo_win_money -(1-signal_result.tupo_win_lose_count_rate)*signal_result.tupo_lose_money }}</td>-->
              <td>
                {{
                  1 / (1 + signal_result.tupo_win_lose_money_rate) <
                  signal_result.tupo_win_lose_count_rate
                    ? '正'
                    : '负'
                }}
              </td>
            </tr>
            <tr>
              <td>V反</td>
              <td>{{ signal_result.five_v_reverse_win_count }}</td>
              <td>{{ signal_result.five_v_reverse_lose_count }}</td>
              <td>{{ signal_result.five_v_reverse_win_lose_count_rate }}%</td>
              <td>{{ signal_result.five_v_reverse_win_lose_money_rate }}</td>
              <!--                    <td>{{signal_result.five_v_reverse_win_lose_count_rate*signal_result.five_v_reverse_win_money-->
              <!--                        -(1-signal_result.five_v_reverse_win_lose_count_rate)*signal_result.five_v_reverse_lose_money }}-->
              <!--                    </td> -->
              <td>
                {{
                  1 / (1 + signal_result.five_v_reverse_win_lose_money_rate) <
                  signal_result.five_v_reverse_win_lose_count_rate
                    ? '正'
                    : '负'
                }}
              </td>
            </tr>
          </tbody>
        </table>
        <div class="item desc">
          <p>胜率： 盈利次数 / 亏损次数 + 盈利次数</p>
          <p>盈亏比： 盈利额 / 亏损额</p>
          <p>期望： 胜率 * 盈利额 - 败率 * 亏损额</p>
        </div>
      </div>

      <div class="statistic-echarts-list">
        <div class="profit-chart" id="profit-chart-parent">
          <div id="profit-chart" />
        </div>
        <div class="common-chart" id="win-lose-count-rate-chart-parent">
          <div id="win-lose-count-rate-chart" />
        </div>
        <div class="margin-chart" id="margin-chart-parent">
          <div id="margin-chart" />
        </div>
        <div class="pie-chart-list">
          <div id="win-pie-chart-parent" class="pie-chart">
            <div id="win-pie-chart" />
          </div>
          <div id="lose-pie-chart-parent" class="pie-chart">
            <div id="lose-pie-chart" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
<script>
import CommonTool from '../tool/CommonTool'
import { futureApi } from '../api/futureApi'
import * as echarts from 'echarts'

export default {
  data () {
    return {
      statisticList: null,
      loseEndCountListNegative: [], // 将亏损数目取反用于图表显示
      signal_result: {},
      dateRange: [],
      profitChart: null,
      winPiechart: null,
      losePieChart: null,
      marginChart: null,
      winLoseCountRateChart: null,
      totalNetProfit: 0,
      totalExchangeCount: 0, // 交易频数
      winLoseCountRate: 0, // 胜率
      evWinLoseCountRate: [0, 0], // 根据胜率计算出正期望的盈亏比,根据盈亏比计算出正期望的胜率
      winloseRate: 0, // 当前盈亏比
      resizeHandler: null,
      pickerOptions: {
        shortcuts: [
          {
            text: '最近一周',
            onClick (picker) {
              const end = new Date()
              const start = new Date()
              start.setTime(start.getTime() - 3600 * 1000 * 24 * 7)
              picker.$emit('pick', [start, end])
            }
          },
          {
            text: '最近一个月',
            onClick (picker) {
              const end = new Date()
              const start = new Date()
              start.setTime(start.getTime() - 3600 * 1000 * 24 * 30)
              picker.$emit('pick', [start, end])
            }
          },
          {
            text: '最近三个月',
            onClick (picker) {
              const end = new Date()
              const start = new Date()
              start.setTime(start.getTime() - 3600 * 1000 * 24 * 90)
              picker.$emit('pick', [start, end])
            }
          }
        ]
      }
    }
  },
  mounted () {
    const now = new Date()
    const lastWeek = now.getTime() - 3600 * 1000 * 24 * 7
    const start = CommonTool.parseTime(lastWeek, '{y}-{m}-{d}')
    const end = CommonTool.dateFormat('yyyy-MM-dd')

    this.dateRange = [start, end]
    this.$nextTick(() => {
      this.initChart()
      this.getStatisticList()
    })
  },
  beforeUnmount () {
    if (this.resizeHandler) {
      window.removeEventListener('resize', this.resizeHandler)
      this.resizeHandler = null
    }
    for (const chart of [
      this.profitChart,
      this.marginChart,
      this.winPiechart,
      this.losePieChart,
      this.winLoseCountRateChart
    ]) {
      if (chart) {
        chart.dispose()
      }
    }
    this.profitChart = null
    this.marginChart = null
    this.winPiechart = null
    this.losePieChart = null
    this.winLoseCountRateChart = null
  },
  methods: {
    getStatisticList () {
      futureApi
        .getStatisticList(this.dateRange)
        .then(res => {
          this.statisticList = res
          this.signal_result = res.signal_result
          this.totalNetProfit = 0
          this.totalExchangeCount = 0
          let totalWin = 0
          let totalLose = 0

          this.winloseRate = 0
          for (let i = 0; i < this.statisticList.net_profit_list.length; i++) {
            const item = this.statisticList.net_profit_list[i]
            totalWin += this.statisticList.win_end_list[i]
            totalLose += this.statisticList.lose_end_list[i]
            this.totalNetProfit += item
            this.totalExchangeCount +=
              this.statisticList.win_end_count_list[i] +
              this.statisticList.lose_end_count_list[i]
          }
          let win_end_count = 0
          if (this.statisticList.win_end_count_list.length !== 0) {
            win_end_count = this.statisticList.win_end_count_list.reduce(
              (sum, number) => {
                return sum + number
              }
            )
          }
          let lose_end_count = 0
          if (this.statisticList.lose_end_count_list.length !== 0) {
            lose_end_count = this.statisticList.lose_end_count_list.reduce(
              (sum, number) => {
                return sum + number
              }
            )
            this.loseEndCountListNegative = this.statisticList.lose_end_count_list.map(
              item => -item
            )
          }

          this.winLoseCountRate =
            win_end_count / (win_end_count + lose_end_count)
          this.winloseRate = Math.abs((totalWin / totalLose).toFixed(1))

          this.evWinLoseCountRate[0] = 1 / (1 + this.winloseRate)
          this.evWinLoseCountRate[1] = Math.abs(1 - 1 / this.winLoseCountRate)
          this.processData()
        })
        .catch(() => {})
    },
    processData () {
      const that = this
      // 盈利列表
      this.profitChart.setOption({
        backgroundColor: '#12161c',
        title: {
          text:
            '净盈利：' +
            this.totalNetProfit +
            '    盈亏比:  ' +
            this.winloseRate +
            '    正期望胜率需 > ' +
            (this.evWinLoseCountRate[0] * 100).toFixed(1) +
            '%',
          x: '20',
          top: '20',
          textStyle: {
            color: '#fff',
            fontSize: '22'
          },
          subtextStyle: {
            color: '#fff',
            fontSize: '16'
          }
        },
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            textStyle: {
              color: '#fff'
            }
          }
        },
        grid: {
          left: '5%',
          right: '5%',
          borderWidth: 0,
          top: 150,
          bottom: 95,
          textStyle: {
            color: '#fff'
          }
        },
        legend: {
          x: '5%',
          top: '10%',
          textStyle: {
            color: '#fff'
          },
          data: ['盈利', '亏损', '净盈利']
        },
        calculable: true,
        xAxis: [
          {
            type: 'category',
            axisLine: {
              lineStyle: {
                color: '#fff'
              }
            },
            splitLine: {
              show: false
            },
            axisTick: {
              show: false
            },
            splitArea: {
              show: false
            },
            axisLabel: {
              interval: 0
            },
            data: this.statisticList.date
          }
        ],
        yAxis: [
          {
            type: 'value',
            splitLine: {
              show: false
            },
            axisLine: {
              lineStyle: {
                color: '#fff'
              }
            },
            axisTick: {
              show: false
            },
            axisLabel: {
              interval: 0
            },
            splitArea: {
              show: false
            }
          }
        ],
        dataZoom: [
          {
            show: true,
            height: 30,
            xAxisIndex: [0],
            bottom: 30,
            start: 0,
            end: 100,
            handleIcon:
              'path://M306.1,413c0,2.2-1.8,4-4,4h-59.8c-2.2,0-4-1.8-4-4V200.8c0-2.2,1.8-4,4-4h59.8c2.2,0,4,1.8,4,4V413z',
            handleSize: '110%',
            handleStyle: {
              color: '#d3dee5'
            },
            textStyle: {
              color: '#fff'
            },
            borderColor: '#fff'
          },
          {
            type: 'inside',
            show: true,
            height: 15,
            start: 1,
            end: 35
          }
        ],
        series: [
          {
            name: '盈利',
            type: 'bar',
            stack: 'total',
            barMaxWidth: 40,
            barGap: '10%',
            itemStyle: {
              color: 'rgba(255,144,128,1)',
              label: {
                show: true,
                textStyle: {
                  color: '#fff'
                },
                position: 'insideTop',
                formatter (p) {
                  return p.value > 0 ? p.value : ''
                }
              }
            },
            data: this.statisticList.win_end_list
          },

          {
            name: '亏损',
            type: 'bar',
            stack: 'total',
            barMaxWidth: 40,
            itemStyle: {
              color: 'rgba(0,191,183,1)',
              borderRadius: 0,
              label: {
                show: true,
                textStyle: {
                  color: '#fff'
                },
                position: 'insideTop'
              }
            },
            data: this.statisticList.lose_end_list
          },
          {
            name: '净盈利',
            type: 'line',
            stack: 'total',
            symbolSize: 10,
            symbol: 'circle',
            itemStyle: {
              color: 'rgba(252,230,48,1)',
              borderRadius: 0,
              label: {
                show: true,
                position: 'top',
                formatter (p) {
                  return (
                    that.statisticList.win_end_list[p.dataIndex] +
                    that.statisticList.lose_end_list[p.dataIndex] +
                    '\n\n 盈亏比' +
                    Math.abs(
                      that.statisticList.win_end_list[p.dataIndex] /
                        that.statisticList.lose_end_list[p.dataIndex]
                    ).toFixed(1)
                  )
                }
              }
            },
            data: this.statisticList.net_profit_list
          }
        ]
      })
      // 胜率列表

      this.winLoseCountRateChart.setOption({
        backgroundColor: '#12161c',
        title: {
          text:
            '交易频数：' +
            this.totalExchangeCount +
            '   胜率:  ' +
            (this.winLoseCountRate * 100).toFixed(1) +
            '%  正期望盈亏比需 >' +
            this.evWinLoseCountRate[1].toFixed(1),
          x: '20',
          top: '20',
          textStyle: {
            color: '#fff',
            fontSize: '22'
          },
          subtextStyle: {
            color: '#fff',
            fontSize: '16'
          }
        },
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            textStyle: {
              color: '#fff'
            }
          }
        },
        grid: {
          left: '5%',
          right: '5%',
          borderWidth: 0,
          top: 150,
          bottom: 95,
          textStyle: {
            color: '#fff'
          }
        },
        legend: {
          x: '5%',
          top: '10%',
          textStyle: {
            color: '#fff'
          },
          data: ['盈利次数', '亏损次数', '胜率']
        },
        calculable: true,
        xAxis: [
          {
            type: 'category',
            axisLine: {
              lineStyle: {
                color: '#fff'
              }
            },
            splitLine: {
              show: false
            },
            axisTick: {
              show: false
            },
            splitArea: {
              show: false
            },
            axisLabel: {
              interval: 0
            },
            data: this.statisticList.date
          }
        ],
        yAxis: [
          {
            type: 'value',
            splitLine: {
              show: false
            },
            axisLine: {
              lineStyle: {
                color: '#fff'
              }
            },
            axisTick: {
              show: false
            },
            axisLabel: {
              interval: 0
            },
            splitArea: {
              show: false
            }
          }
        ],
        dataZoom: [
          {
            show: true,
            height: 30,
            xAxisIndex: [0],
            bottom: 30,
            start: 0,
            end: 100,
            handleIcon:
              'path://M306.1,413c0,2.2-1.8,4-4,4h-59.8c-2.2,0-4-1.8-4-4V200.8c0-2.2,1.8-4,4-4h59.8c2.2,0,4,1.8,4,4V413z',
            handleSize: '110%',
            handleStyle: {
              color: '#d3dee5'
            },
            textStyle: {
              color: '#fff'
            },
            borderColor: '#fff'
          },
          {
            type: 'inside',
            show: true,
            height: 15,
            start: 1,
            end: 35
          }
        ],
        series: [
          {
            name: '盈利次数',
            type: 'bar',
            stack: 'total',
            barMaxWidth: 40,
            barGap: '10%',
            itemStyle: {
              color: 'rgba(255,144,128,1)',
              label: {
                show: true,
                textStyle: {
                  color: '#fff'
                },
                position: 'insideTop',
                formatter (p) {
                  return p.value > 0 ? p.value : ''
                }
              }
            },
            data: this.statisticList.win_end_count_list
          },

          {
            name: '亏损次数',
            type: 'bar',
            stack: 'total',
            itemStyle: {
              color: 'rgba(0,191,183,1)',
              borderRadius: 0,
              label: {
                show: true,
                position: 'insideTop',
                formatter (p) {
                  return p.value
                }
              }
            },
            data: this.loseEndCountListNegative
          },
          {
            name: '胜率',
            type: 'line',
            stack: 'total',
            symbolSize: 10,
            symbol: 'circle',
            itemStyle: {
              color: 'rgba(252,230,48,1)',
              borderRadius: 0,
              label: {
                show: true,
                position: 'top',
                formatter (p) {
                  return parseInt(p.value * 100) + '%'
                }
              }
            },
            data: this.statisticList.win_lose_count_rate
          }
        ]
      })

      // 保证金列表
      this.marginChart.setOption({
        backgroundColor: '#12161c',
        title: {
          text: '保证金占用（最大仓位）',
          x: '20',
          top: '20',
          textStyle: {
            color: '#fff',
            fontSize: '22'
          },
          subtextStyle: {
            color: '#fff',
            fontSize: '16'
          }
        },
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            textStyle: {
              color: '#fff'
            }
          }
        },
        grid: {
          left: '8%',
          right: '5%',
          borderWidth: 0,
          top: 150,
          bottom: 95,
          textStyle: {
            color: '#fff'
          }
        },
        legend: {
          x: '5%',
          top: '10%',
          textStyle: {
            color: '#fff'
          },
          data: ['保证金占用']
        },
        calculable: true,
        xAxis: [
          {
            type: 'category',
            axisLine: {
              lineStyle: {
                color: '#fff'
              }
            },
            splitLine: {
              show: false
            },
            axisTick: {
              show: false
            },
            splitArea: {
              show: false
            },
            axisLabel: {
              interval: 0
            },
            data: this.statisticList.date
          }
        ],
        yAxis: [
          {
            type: 'value',
            splitLine: {
              show: false
            },
            axisLine: {
              lineStyle: {
                color: '#fff'
              }
            },
            axisTick: {
              show: false
            },
            axisLabel: {
              interval: 0
            },
            splitArea: {
              show: false
            }
          }
        ],
        dataZoom: [
          {
            show: true,
            height: 30,
            xAxisIndex: [0],
            bottom: 30,
            start: 0,
            end: 100,
            handleIcon:
              'path://M306.1,413c0,2.2-1.8,4-4,4h-59.8c-2.2,0-4-1.8-4-4V200.8c0-2.2,1.8-4,4-4h59.8c2.2,0,4,1.8,4,4V413z',
            handleSize: '110%',
            handleStyle: {
              color: '#d3dee5'
            },
            textStyle: {
              color: '#fff'
            },
            borderColor: '#fff'
          },
          {
            type: 'inside',
            show: true,
            height: 15,
            start: 1,
            end: 35
          }
        ],
        series: [
          {
            name: '保证金占用',
            type: 'bar',
            stack: 'total',
            barMaxWidth: 40,
            barGap: '10%',
            itemStyle: {
              color: function (params) {
                return parseInt(
                  (params.data / (that.$futureAccount * 10000)) * 100
                ) > 50
                  ? 'rgba(255,144,128,1)'
                  : 'rgba(0,191,183,1)'
              },
              label: {
                show: true,
                textStyle: {
                  color: '#fff'
                },
                position: 'top',
                formatter (p) {
                  return (
                    p.value +
                    '\n\n占比' +
                    parseInt(
                      (p.value / (that.$futureAccount * 10000)) * 100
                    ) +
                    '%'
                  )
                }
              }
            },
            data: this.statisticList.total_margin
          }
        ]
      })

      // 盈利品种列表
      this.winPiechart.setOption({
        title: {
          text: '品种盈利排行及持仓天数',
          top: '2%',
          textStyle: {
            color: 'white'
          }
        },
        xAxis: {
          type: 'category',
          data: this.statisticList.win_symbol_list,
          axisLine: { lineStyle: { color: 'white' } }
        },
        yAxis: {
          type: 'value',
          axisLine: { lineStyle: { color: 'white' } },
          splitLine: {
            show: false
          }
        },
        tooltip: {
          trigger: 'item',
          formatter: '{a} <br/>{b} : {c}'
        },
        legend: {
          left: 'center',
          bottom: '10',
          data: this.statisticList.win_symbol_list
        },

        series: [
          {
            name: '盈利排行',
            type: 'bar',
            data: this.statisticList.win_money_list,
            animationEasing: 'cubicInOut',
            animationDuration: 2600,
            itemStyle: {
              color: function (params) {
                return '#EF5350'
              },
              label: {
                color: '#fff',
                show: true,
                position: 'top',
                formatter (p) {
                  return (
                    that.statisticList.win_end_holding_day_list[p.dataIndex] +
                    '天'
                  )
                }
              }
            }
          }
        ]
      })
      // 亏损品种列表
      this.losePieChart.setOption({
        title: {
          text: '品种亏损排行及持仓天数',
          top: '2%',
          textStyle: {
            color: 'white'
          }
        },
        tooltip: {
          trigger: 'item',
          formatter: '{a} <br/>{b} : {c}'
        },
        legend: {
          left: 'center',
          bottom: '10',
          data: this.statisticList.lose_symbol_list
        },

        xAxis: {
          type: 'category',
          data: this.statisticList.lose_symbol_list,
          axisLine: { lineStyle: { color: 'white' } }
        },
        yAxis: {
          type: 'value',
          axisLine: { lineStyle: { color: 'white' } },
          splitLine: {
            show: false
          }
        },
        series: [
          {
            name: '亏损排行',
            type: 'bar',
            data: this.statisticList.lose_money_list,
            animationEasing: 'cubicInOut',
            animationDuration: 2600,
            itemStyle: {
              color: function (params) {
                return '#26A69A'
              },
              label: {
                color: '#fff',
                show: true,
                position: 'top',
                formatter (p) {
                  return (
                    that.statisticList.lose_end_holding_day_list[
                      p.dataIndex
                    ] + '天'
                  )
                }
              }
            }
          }
        ]
      })
    },
    initChart () {
      if (this.profitChart) {
        return
      }
      const profitDom = this.prepareChartHost('profit-chart-parent', 'profit-chart')
      const marginDom = this.prepareChartHost('margin-chart-parent', 'margin-chart')
      const winLoseCountRateDom = this.prepareChartHost(
        'win-lose-count-rate-chart-parent',
        'win-lose-count-rate-chart'
      )
      const winPieDom = this.prepareChartHost('win-pie-chart-parent', 'win-pie-chart')
      const losePieDom = this.prepareChartHost('lose-pie-chart-parent', 'lose-pie-chart')

      this.profitChart = echarts.init(profitDom)
      this.marginChart = echarts.init(marginDom)
      this.winPiechart = echarts.init(winPieDom)
      this.losePieChart = echarts.init(losePieDom)
      this.winLoseCountRateChart = echarts.init(winLoseCountRateDom)

      this.profitChart.resize()
      this.marginChart.resize()
      this.winPiechart.resize()
      this.losePieChart.resize()
      this.winLoseCountRateChart.resize()

      this.resizeHandler = () => {
        this.chartssize(document.getElementById('profit-chart-parent'), profitDom)
        this.chartssize(document.getElementById('margin-chart-parent'), marginDom)
        this.chartssize(
          document.getElementById('win-lose-count-rate-chart-parent'),
          winLoseCountRateDom
        )
        this.chartssize(document.getElementById('win-pie-chart-parent'), winPieDom)
        this.chartssize(document.getElementById('lose-pie-chart-parent'), losePieDom)
        this.profitChart.resize()
        this.marginChart.resize()
        this.winPiechart.resize()
        this.losePieChart.resize()
        this.winLoseCountRateChart.resize()
      }
      window.addEventListener('resize', this.resizeHandler)
    },
    prepareChartHost (containerId, chartId) {
      const container = document.getElementById(containerId)
      const chart = document.getElementById(chartId)
      this.chartssize(container, chart)
      return chart
    },
    // 计算echarts 高度
    chartssize (container, charts) {
      if (!container || !charts) {
        return
      }
      function getStyle (el, name) {
        if (window.getComputedStyle) {
          return window.getComputedStyle(el, null)
        } else {
          return el.currentStyle
        }
      }

      const wi = container.clientWidth || parseInt(getStyle(container, 'width').width, 10) || 1200
      const hi = container.clientHeight || parseInt(getStyle(container, 'height').height, 10) || 300
      charts.style.height = `${hi}px`
      charts.style.width = `${wi}px`
    }
  }
}
</script>
<style lang="stylus">
.statistic-echarts-main {
    /*.profit-chart {
        flex 2
        height: 500px
        width: 1200px
    }

    .pie-chart {
        flex: 1
        width: 400px;
        height: 300px;
        margin-top 100px;
    }*/
}

input.el-range-input {
    background-color: #12161c;
    border: 1px solid rgba(127, 127, 122, .2);
    color: white
}

.el-date-editor .el-range-input {
    color: white !important
}

.signal-statistic {
    display flex
    flex-direction row

    .item {
        flex 1

        th, td {
            width: 100px;
            text-align: center
            height: 50px;
            line-height 50px;
        }
    }

    .desc {
        margin-top 10px;
        line-height 30px;
        height 30px;
    }

}

.statistic-echarts-list {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    height: 100%
    width: 100%
    margin-top 10px;

    .profit-chart {
        height: 500px
        width: 1200px
    }

    .margin-chart {
        height: 500px
        width: 1200px
    }

    .common-chart {
        height: 500px
        width: 1200px
    }

    .pie-chart-list {
        display: flex;
        flex-wrap: wrap;
        justify-content: space-between;
        flex-direction column
        width: 100%;
        height: auto;

        .pie-chart {
            flex: 0 0 auto
            width: 1200px;
            min-height: 300px;
            height: 300px;
        }
    }

    #profit-chart,
    #win-lose-count-rate-chart,
    #margin-chart,
    #win-pie-chart,
    #lose-pie-chart {
        width: 100%;
        height: 100%;
    }

}
</style>

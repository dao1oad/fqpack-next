<template>
  <div class="pie-chart" id="pie-chart" />
</template>

<script>
import * as echarts from 'echarts'

export default {
  data () {
    return {
      chart: null
    }
  },
  mounted () {
    this.$nextTick(() => {
      this.initChart()
    })
  },
  beforeUnmount () {
    if (!this.chart) {
      return
    }
    this.chart.dispose()
    this.chart = null
  },
  methods: {
    initChart () {
      this.chart = echarts.init(
        document.getElementById('pie-chart'),
        'macarons'
      )
      this.chart.setOption({
        title: {
          text: '盈利品种排行',
          top: '2%',
          textStyle: {
            color: 'black'
          }
        },
        tooltip: {
          trigger: 'item',
          formatter: '{a} <br/>{b} : {c} ({d}%)'
        },
        legend: {
          left: 'center',
          bottom: '10',
          data: ['螺纹', '橡胶', '豆粕', '沪镍', '黄金']
        },
        series: [
          {
            name: '盈利品种占比',
            type: 'pie',
            roseType: 'radius',
            radius: [15, 95],
            center: ['50%', '38%'],
            data: [
              { value: 320, name: '螺纹' },
              { value: 240, name: '橡胶' },
              { value: 149, name: '豆粕' },
              { value: 100, name: '沪镍' },
              { value: 59, name: '黄金' }
            ],
            animationEasing: 'cubicInOut',
            animationDuration: 2600
          }
        ]
      })
    }
  }
}
</script>
<style lang="stylus">
.pie-chart {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    height: 25vh
    width: 25vw
}
</style>

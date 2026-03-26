import * as echarts from 'echarts'
import elementTool from '@/tool/elementTool'
import echartsConfig from './echartsConfig'

export default (vueComp) => {
  const query = vueComp.$route.query
  const singleChartPeriod = query.period || vueComp.query?.period || (vueComp.view === 'klineBig' ? vueComp.periodList?.[0] : null)
  //  大图只显示选中的k线图
  if (singleChartPeriod) {
    elementTool.fitToContainerSize(document.getElementById('main'), document.getElementById('mainParent'))
    const myChart = echarts.getInstanceByDom(document.getElementById('main'))
    if (myChart != null) {
      myChart.dispose()
    }
    vueComp.myChart = echarts.init(document.getElementById('main'), 'dark')
    vueComp.myChart.resize()
    vueComp.myChart.showLoading(echartsConfig.loadingOption)
    window.addEventListener('resize', () => {
      vueComp.myChart.resize()
    })
  } else {
    elementTool.fitToContainerSize(document.getElementById('main1'), document.getElementById('main1Parent'))
    elementTool.fitToContainerSize(document.getElementById('main1d'), document.getElementById('main1dParent'))
    elementTool.fitToContainerSize(document.getElementById('main15'), document.getElementById('main15Parent'))
    elementTool.fitToContainerSize(document.getElementById('main60'), document.getElementById('main60Parent'))
    elementTool.fitToContainerSize(document.getElementById('main5'), document.getElementById('main5Parent'))
    elementTool.fitToContainerSize(document.getElementById('main30'), document.getElementById('main30Parent'))

    const myChart1d = echarts.getInstanceByDom(document.getElementById('main1d'))
    if (myChart1d != null) {
      myChart1d.dispose()
    }
    vueComp.myChart1d = echarts.init(document.getElementById('main1d'), 'dark')
    const myChart5 = echarts.getInstanceByDom(document.getElementById('main5'))
    if (myChart5 != null) {
      myChart5.dispose()
    }
    vueComp.myChart5 = echarts.init(document.getElementById('main5'), 'dark')
    const myChart15 = echarts.getInstanceByDom(document.getElementById('main15'))
    if (myChart15 != null) {
      myChart15.dispose()
    }
    vueComp.myChart15 = echarts.init(document.getElementById('main15'), 'dark')
    const myChart30 = echarts.getInstanceByDom(document.getElementById('main30'))
    if (myChart30 != null) {
      myChart30.dispose()
    }
    vueComp.myChart30 = echarts.init(document.getElementById('main30'), 'dark')
    const myChart60 = echarts.getInstanceByDom(document.getElementById('main60'))
    if (myChart60 != null) {
      myChart60.dispose()
    }
    vueComp.myChart60 = echarts.init(document.getElementById('main60'), 'dark')
    const myChart1 = echarts.getInstanceByDom(document.getElementById('main1'))
    if (myChart1 != null) {
      myChart1.dispose()
    }
    vueComp.myChart1 = echarts.init(document.getElementById('main1'), 'dark')

    vueComp.myChart1.resize()
    vueComp.myChart1d.resize()
    vueComp.myChart5.resize()
    vueComp.myChart15.resize()
    vueComp.myChart30.resize()
    vueComp.myChart60.resize()

    vueComp.myChart1.showLoading(echartsConfig.loadingOption)
    vueComp.myChart1d.showLoading(echartsConfig.loadingOption)
    vueComp.myChart5.showLoading(echartsConfig.loadingOption)
    vueComp.myChart15.showLoading(echartsConfig.loadingOption)
    vueComp.myChart30.showLoading(echartsConfig.loadingOption)
    vueComp.myChart60.showLoading(echartsConfig.loadingOption)

    window.addEventListener('resize', () => {
      vueComp.myChart1d.resize()
      vueComp.myChart5.resize()
      vueComp.myChart15.resize()
      vueComp.myChart30.resize()
      vueComp.myChart60.resize()
      vueComp.myChart1.resize()
    })
  }
}

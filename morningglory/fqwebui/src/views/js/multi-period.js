import klineMixin from './kline-mixin'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import draw from './draw'
import { futureApi } from '@/api/futureApi'
import queryParamTool from '@/tool/queryParamTool'
import _ from 'lodash'
import { reactive } from 'vue'
import manba from 'manba'

async function loadKlinePeriodData({ query, period }) {
  const { symbol, endDate } = queryParamTool.getLocationQueryParams()
  if (!symbol) {
    return null
  }
  const data = await futureApi.stockData(
    Object.assign({
      symbol, period, endDate
    }, _.pick(query, ['symbol', 'endDate'])))
  data._dtString = manba(data.dt).format('YYYY-MM-DD HH:mm:ss')
  return data
}

export default {
  name: 'multi-period',
  mixins: [klineMixin],
  data () {
    return {
      view: 'multiPeriod'
    }
  },
  setup () {
    const query = reactive({})
    const { data: klineData1Min } = useQuery({
      queryKey: ['klineData1Min'],
      queryFn: async () => loadKlinePeriodData({ query, period: '1m' }),
      refetchInterval: 10000,
      staleTime: 5000
    })
    const { data: klineData5Min } = useQuery({
      queryKey: ['klineData5Min'],
      queryFn: async () => loadKlinePeriodData({ query, period: '5m' }),
      refetchInterval: 10000,
      staleTime: 5000
    })
    const { data: klineData15Min } = useQuery({
      queryKey: ['klineData15Min'],
      queryFn: async () => loadKlinePeriodData({ query, period: '15m' }),
      refetchInterval: 10000,
      staleTime: 5000
    })
    const { data: klineData30Min } = useQuery({
      queryKey: ['klineData30Min'],
      queryFn: async () => loadKlinePeriodData({ query, period: '30m' }),
      refetchInterval: 10000,
      staleTime: 5000
    })
    const { data: klineData60Min } = useQuery({
      queryKey: ['klineData60Min'],
      queryFn: async () => loadKlinePeriodData({ query, period: '60m' }),
      refetchInterval: 10000,
      staleTime: 5000
    })
    const { data: klineData1D } = useQuery({
      queryKey: ['klineData1D'],
      queryFn: async () => loadKlinePeriodData({ query, period: '1d' }),
      refetchInterval: 10000,
      staleTime: 5000
    })
    const queryClient = useQueryClient()
    return {
      myChart1: null,
      myChart5: null,
      myChart15: null,
      myChart30: null,
      myChart60: null,
      myChart1d: null,
      query,
      klineData1Min,
      klineData5Min,
      klineData15Min,
      klineData30Min,
      klineData60Min,
      klineData1D,
      queryClient
    }
  },
  watch: {
    klineData1Min: function (newKlineData) {
      if (newKlineData) {
        draw(this, newKlineData, '1m')
      }
    },
    klineData5Min: function (newKlineData) {
      if (newKlineData) {
        draw(this, newKlineData, '5m')
      }
    },
    klineData15Min: function (newKlineData) {
      if (newKlineData) {
        draw(this, newKlineData, '15m')
      }
    },
    klineData30Min: function (newKlineData) {
      if (newKlineData) {
        draw(this, newKlineData, '30m')
      }
    },
    klineData60Min: function (newKlineData) {
      if (newKlineData) {
        draw(this, newKlineData, '60m')
      }
    },
    klineData1D: function (newKlineData) {
      if (newKlineData) {
        draw(this, newKlineData, '1d')
      }
    }
  }
}

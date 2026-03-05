import klineMixin from './kline-mixin'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import draw from './draw'
import { futureApi } from '@/api/futureApi'
import queryParamTool from '@/tool/queryParamTool'
import _ from 'lodash'
import { reactive } from 'vue'
import manba from 'manba'

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
      queryFn: async () => {
        const { symbol, endDate } = queryParamTool.getLocationQueryParams()
        const data = await futureApi.stockData(
          Object.assign({
            symbol, period: '1m', endDate
          }, _.pick(query, ['symbol', 'endDate'])))
        data._dtString = manba(data.dt).format('YYYY-MM-DD HH:mm:ss')
        return data
      },
      refetchInterval: 10000,
      staleTime: 5000
    })
    const { data: klineData5Min } = useQuery({
      queryKey: ['klineData5Min'],
      queryFn: async () => {
        const { symbol, endDate } = queryParamTool.getLocationQueryParams()
        const data = await futureApi.stockData(
          Object.assign({
            symbol, period: '5m', endDate
          }, _.pick(query, ['symbol', 'endDate'])))
        data._dtString = manba(data.dt).format('YYYY-MM-DD HH:mm:ss')
        return data
      },
      refetchInterval: 10000,
      staleTime: 5000
    })
    const { data: klineData15Min } = useQuery({
      queryKey: ['klineData15Min'],
      queryFn: async () => {
        const { symbol, endDate } = queryParamTool.getLocationQueryParams()
        const data = await futureApi.stockData(
          Object.assign({
            symbol, period: '15m', endDate
          }, _.pick(query, ['symbol', 'endDate'])))
        data._dtString = manba(data.dt).format('YYYY-MM-DD HH:mm:ss')
        return data
      },
      refetchInterval: 10000,
      staleTime: 5000
    })
    const { data: klineData30Min } = useQuery({
      queryKey: ['klineData30Min'],
      queryFn: async () => {
        const { symbol, endDate } = queryParamTool.getLocationQueryParams()
        const data = await futureApi.stockData(
          Object.assign({
            symbol, period: '30m', endDate
          }, _.pick(query, ['symbol', 'endDate'])))
        data._dtString = manba(data.dt).format('YYYY-MM-DD HH:mm:ss')
        return data
      },
      refetchInterval: 10000,
      staleTime: 5000
    })
    const { data: klineData60Min } = useQuery({
      queryKey: ['klineData60Min'],
      queryFn: async () => {
        const { symbol, endDate } = queryParamTool.getLocationQueryParams()
        const data = await futureApi.stockData(
          Object.assign({
            symbol, period: '60m', endDate
          }, _.pick(query, ['symbol', 'endDate'])))
        data._dtString = manba(data.dt).format('YYYY-MM-DD HH:mm:ss')
        return data
      },
      refetchInterval: 10000,
      staleTime: 5000
    })
    const { data: klineData1D } = useQuery({
      queryKey: ['klineData1D'],
      queryFn: async () => {
        const { symbol, endDate } = queryParamTool.getLocationQueryParams()
        const data = await futureApi.stockData(
          Object.assign({
            symbol, period: '1d', endDate
          }, _.pick(query, ['symbol', 'endDate'])))
        data._dtString = manba(data.dt).format('YYYY-MM-DD HH:mm:ss')
        return data
      },
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
      draw(this, newKlineData, '60m')
    },
    klineData1D: function (newKlineData) {
      if (newKlineData) {
        draw(this, newKlineData, '1d')
      }
    }
  }
}

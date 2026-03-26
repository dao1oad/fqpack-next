import klineMixin from './kline-mixin'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { futureApi } from '@/api/futureApi'
import draw from './draw'
import { reactive } from 'vue'
import queryParamTool from '@/tool/queryParamTool'
import _ from 'lodash'
import manba from 'manba'

export default {
  name: 'kline-big',
  mixins: [klineMixin],
  data () {
    return {
      view: 'klineBig'
    }
  },
  setup () {
    const query = reactive({})
    const { data: klineData, isLoading } = useQuery({
      queryKey: ['klineData'],
      queryFn: async () => {
        const { symbol, period, endDate } = queryParamTool.getLocationQueryParams()
        if (!symbol) {
          return null
        }
        const resolvedPeriod = period || query.period || '1m'
        const data = await futureApi.stockData(
          Object.assign({ symbol, period: resolvedPeriod, endDate }, _.pick(query, ['symbol', 'period', 'endDate']))
        )
        data._resolvedPeriod = resolvedPeriod
        data._dtString = manba(data.dt).format('YYYY-MM-DD HH:mm:ss')
        return data
      },
      refetchInterval: 10000,
      staleTime: 5000
    })
    const queryClient = useQueryClient()
    return { myChart: null, query, queryClient, klineData, isLoading }
  },
  watch: {
    klineData: function (newKlineData) {
      if (newKlineData) {
        draw(
          this,
          newKlineData,
          newKlineData._resolvedPeriod || this.query.period || this.$route.query.period || '1m'
        )
      }
    }
  }
}

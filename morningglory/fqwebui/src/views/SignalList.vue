<template>
  <div class="stock-control-list stock-control-list--signal">
    <div class="stock-control-ledger-shell">
      <div v-loading="isLoading" class="stock-control-ledger stock-control-ledger--signal">
        <div class="stock-control-ledger__header stock-control-signal-ledger__grid">
          <span>信号时间</span>
          <span>入库时间</span>
          <span>标的代码</span>
          <span>标的名称</span>
          <span>方向</span>
          <span>类型</span>
          <span>触发价/止损价/止损%</span>
        </div>
        <div class="stock-control-ledger__viewport">
          <div
            v-for="(row, rowIndex) in signalRows"
            :key="`${category}-${formatCode(row)}-${formatCreatedAt(row)}-${rowIndex}`"
            class="stock-control-ledger__row stock-control-signal-ledger__grid"
          >
            <span class="stock-control-ledger__cell stock-control-ledger__cell--mono stock-control-ledger__cell--time">{{ formatDateTime(row.fire_time) }}</span>
            <span class="stock-control-ledger__cell stock-control-ledger__cell--mono stock-control-ledger__cell--time">{{ formatDateTime(formatCreatedAt(row)) }}</span>
            <span class="stock-control-ledger__cell stock-control-ledger__cell--mono stock-control-ledger__cell--strong">{{ formatCode(row) }}</span>
            <span class="stock-control-ledger__cell stock-control-ledger__cell--strong" :title="formatText(row.name)">{{ formatText(row.name) }}</span>
            <span class="stock-control-ledger__cell stock-control-ledger__cell--strong">{{ formatDirection(row.position) }}</span>
            <span class="stock-control-ledger__cell" :title="formatSignalType(row)">{{ formatSignalType(row) }}</span>
            <span class="stock-control-ledger__cell stock-control-ledger__cell--mono stock-control-ledger__cell--strong stock-control-ledger__cell--price">{{ formatPriceSummary(row.price, row.stop_lose_price) }}</span>
          </div>
          <div v-if="!isLoading && signalRows.length === 0" class="stock-control-ledger__empty">
            暂无数据
          </div>
        </div>
      </div>
    </div>
    <div class="stock-control-list__pagination">
      <el-pagination
        background
        layout="total,sizes,prev,pager,next"
        v-model:current-page="listQuery.current"
        :page-size="listQuery.size"
        :total="listQuery.total"
        :page-sizes="[100, 200, 500]"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>
  </div>
</template>

<script>
import { stockApi } from '@/api/stockApi'
import _ from 'lodash'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, reactive } from 'vue'
import { formatBeijingTimestamp } from '../tool/beijingTime.mjs'

export default {
  name: 'SignalList',
  props: {
    title: {
      type: String,
      default: 'must_pools买入信号'
    },
    category: {
      type: String,
      default: 'must_pool_buys'
    }
  },
  setup (props) {
    const listQuery = reactive({
      size: 100,
      total: 0,
      current: 1
    })
    const { isLoading, data: signalList } = useQuery({
      queryKey: ['stockSignalList', props.category],
      queryFn: async () => {
        const rows = await stockApi.getStockSignalList({
          page: 1,
          size: 1000,
          category: props.category
        })
        listQuery.total = _.size(rows)
        const start = (listQuery.current - 1) * listQuery.size
        const end = start + listQuery.size
        return _.slice(rows, start, end)
      },
      refetchInterval: 30000,
      staleTime: 5000
    })
    const signalRows = computed(() => signalList.value || [])
    const queryClient = useQueryClient()
    return { isLoading, signalList, signalRows, listQuery, queryClient }
  },
  methods: {
    handleSizeChange (currentSize) {
      this.listQuery.size = currentSize
      this.listQuery.current = 1
      this.queryClient.invalidateQueries({ queryKey: ['stockSignalList', this.category] })
    },
    handlePageChange (currentPage) {
      this.listQuery.current = currentPage
      this.queryClient.invalidateQueries({ queryKey: ['stockSignalList', this.category] })
    },
    formatText (value) {
      const normalized = String(value ?? '').trim()
      return normalized || '--'
    },
    formatCode (row) {
      const code = String(row?.code ?? '').trim()
      if (code) {
        return code
      }
      const symbol = String(row?.symbol ?? '').trim()
      const matched = symbol.match(/(\d{6})$/)
      return matched?.[1] || symbol || '--'
    },
    formatCreatedAt (row) {
      return this.formatText(row?.created_at || row?.fire_time)
    },
    formatDirection (value) {
      const normalized = this.formatText(value)
      if (normalized === 'BUY_LONG') {
        return '买入'
      }
      if (normalized === 'SELL_SHORT') {
        return '卖出'
      }
      return normalized === '--' ? '--' : normalized
    },
    formatSignalType (row) {
      const remark = this.formatText(row?.remark)
      if (remark !== '--') {
        return remark
      }
      const category = row?.category
      if (Array.isArray(category) && category.length > 0) {
        return category.map((item) => this.formatText(item)).filter((item) => item !== '--').join(' / ') || '--'
      }
      return this.formatText(category)
    },
    formatDateTime (value) {
      return formatBeijingTimestamp(value, '--')
    },
    formatPrice (value) {
      if (value === null || value === undefined || value === '') {
        return '--'
      }
      const parsed = Number(value)
      if (!Number.isFinite(parsed)) {
        return '--'
      }
      return parsed.toFixed(3)
    },
    formatStopLossRate (price, stopLosePrice) {
      const firePrice = Number(price)
      const stopPrice = Number(stopLosePrice)
      if (!Number.isFinite(firePrice) || !Number.isFinite(stopPrice) || firePrice === 0) {
        return '--'
      }
      return `${(((stopPrice - firePrice) / firePrice) * 100).toFixed(3)}%`
    },
    formatPriceSummary (price, stopLosePrice) {
      return `${this.formatPrice(price)}/${this.formatPrice(stopLosePrice)}/${this.formatStopLossRate(price, stopLosePrice)}`
    }
  }
}
</script>

<style lang="stylus" scoped>
@import '../style/stock-control-ledger.styl';

.stock-control-list
  display flex
  flex 1 1 auto
  flex-direction column
  min-width 0
  min-height 0
  overflow hidden

.stock-control-signal-ledger__grid
  grid-template-columns 148px 148px 56px minmax(0, 0.52fr) 40px minmax(0, 1fr) 160px
</style>

<template>
  <div class="stock-control-list stock-control-list--model">
    <div class="stock-control-ledger-shell">
      <div v-loading="isLoading" class="stock-control-ledger stock-control-ledger--model">
        <div class="stock-control-ledger__header stock-control-model-ledger__grid">
          <span>信号时间</span>
          <span>入库时间</span>
          <span>标的代码</span>
          <span>标的名称</span>
          <span>周期</span>
          <span>分组</span>
          <span>模型</span>
          <span>来源</span>
          <span>触发价/止损价/止损%</span>
        </div>
        <div class="stock-control-ledger__viewport">
          <div
            v-for="(row, rowIndex) in signalRows"
            :key="`${formatText(row.code)}-${formatText(row.datetime)}-${rowIndex}`"
            class="stock-control-ledger__row stock-control-model-ledger__grid"
          >
            <span class="stock-control-ledger__cell stock-control-ledger__cell--mono stock-control-ledger__cell--time">{{ formatDateTime(row.datetime) }}</span>
            <span class="stock-control-ledger__cell stock-control-ledger__cell--mono stock-control-ledger__cell--time">{{ formatDateTime(row.created_at) }}</span>
            <span class="stock-control-ledger__cell stock-control-ledger__cell--mono stock-control-ledger__cell--strong">{{ formatText(row.code) }}</span>
            <span class="stock-control-ledger__cell stock-control-ledger__cell--strong" :title="formatText(row.name)">{{ formatText(row.name) }}</span>
            <span class="stock-control-ledger__cell stock-control-ledger__cell--mono">{{ formatText(row.period) }}</span>
            <span class="stock-control-ledger__cell" :title="formatModelGroup(row.model)">{{ formatModelGroup(row.model) }}</span>
            <span class="stock-control-ledger__cell" :title="formatModelLabel(row.model)">{{ formatModelLabel(row.model) }}</span>
            <span class="stock-control-ledger__cell" :title="formatText(row.source)">{{ formatText(row.source) }}</span>
            <span class="stock-control-ledger__cell stock-control-ledger__cell--mono stock-control-ledger__cell--strong stock-control-ledger__cell--price">{{ formatPriceSummary(row.close, row.stop_loss_price) }}</span>
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
import { resolveDailyScreeningClsModelPresentation } from './dailyScreeningPage.mjs'
import _ from 'lodash'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, reactive } from 'vue'

export default {
  name: 'ModelSignalList',
  props: {
    title: {
      type: String,
      default: 'stock_pools模型信号'
    }
  },
  setup () {
    const listQuery = reactive({
      size: 100,
      total: 0,
      current: 1
    })
    const { isLoading, data: signalList } = useQuery({
      queryKey: ['stockModelSignalList'],
      queryFn: async () => {
        const rows = await stockApi.getStockModelSignalList({
          page: 1,
          size: 1000
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
      this.queryClient.invalidateQueries({ queryKey: ['stockModelSignalList'] })
    },
    handlePageChange (currentPage) {
      this.listQuery.current = currentPage
      this.queryClient.invalidateQueries({ queryKey: ['stockModelSignalList'] })
    },
    formatText (value) {
      const normalized = String(value ?? '').trim()
      return normalized || '--'
    },
    formatDateTime (value) {
      const normalized = this.formatText(value)
      const matched = normalized.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/)
      if (!matched) {
        return normalized
      }
      return `${matched[2]}-${matched[3]} ${matched[4]}:${matched[5]}`
    },
    resolveModelPresentation (value) {
      return resolveDailyScreeningClsModelPresentation(value)
    },
    formatModelGroup (value) {
      return this.resolveModelPresentation(value).groupLabel
    },
    formatModelLabel (value) {
      return this.resolveModelPresentation(value).modelLabel
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
    formatStopLossRate (price, stopLossPrice) {
      const firePrice = Number(price)
      const stopPrice = Number(stopLossPrice)
      if (!Number.isFinite(firePrice) || !Number.isFinite(stopPrice) || firePrice === 0) {
        return '--'
      }
      return `${(((stopPrice - firePrice) / firePrice) * 100).toFixed(3)}%`
    },
    formatPriceSummary (price, stopLossPrice) {
      return `${this.formatPrice(price)}/${this.formatPrice(stopLossPrice)}/${this.formatStopLossRate(price, stopLossPrice)}`
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

.stock-control-model-ledger__grid
  grid-template-columns 72px 72px 56px minmax(0, 1fr) 80px 100px 120px 46px 160px
</style>

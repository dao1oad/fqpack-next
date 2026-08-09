<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { clxDailySelectionApi } from '@/api/clxDailySelectionApi.js'
import {
  fetchOfficialResult,
  formatResultTime,
  buildResultExportPayload,
} from './clxResultPanelLogic.mjs'

const props = defineProps({
  tradeDate: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['selection-time', 'pre-status'])

const loading = ref(false)
const exporting = ref(false)
const error = ref('')
const result = ref(null)
const cursor = ref('')
const rows = ref([])
const search = ref('')
const selectedCode = ref('')

const status = computed(() => result.value?.status || 'loading')
const resultTime = computed(() => formatResultTime(result.value?.resultTime))
const counts = computed(() => result.value?.counts || {})
const visibleRows = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((row) =>
    [row.symbol, row.name].some((value) =>
      String(value || '').toLowerCase().includes(q),
    ),
  )
})

const load = async ({ append = false } = {}) => {
  loading.value = true
  error.value = ''
  try {
    const next = await fetchOfficialResult({
      tradeDate: props.tradeDate,
      q: '',
      cursor: append ? cursor.value : '',
    })
    result.value = next
    rows.value = append ? [...rows.value, ...next.rows] : next.rows
    cursor.value = next.nextCursor || ''
    emit('selection-time', {
      resultTime: next.resultTime,
      tradeDate: next.tradeDate,
      batchId: next.batchId,
    })
    emit('pre-status', {
      status: next.status,
      tradeDate: next.tradeDate,
      batchId: next.batchId,
      generationId: next.generationId,
    })
  } catch (err) {
    error.value = err?.message || '选股结果加载失败'
  } finally {
    loading.value = false
  }
}

const loadMore = () => {
  if (cursor.value && !loading.value) load({ append: true })
}

const exportToTdx = async () => {
  const payload = buildResultExportPayload({
    batchId: result.value?.batchId,
    rows: rows.value,
  })
  if (!payload) {
    ElMessage.warning('当前没有可导出的正式选股结果')
    return
  }
  exporting.value = true
  try {
    const response = await clxDailySelectionApi.syncSelectedBatchResultsToTdx(
      payload.batchId,
      { items: payload.items },
    )
    const data = response?.data ?? response ?? {}
    ElMessage.success(
      `已导出当前结果到 CLX_18：${data.written_count ?? payload.items.length} 只`,
    )
  } catch (err) {
    ElMessage.error(err?.response?.data?.message || err?.message || '导出 CLX_18 失败')
  } finally {
    exporting.value = false
  }
}

const selectRow = (row) => {
  selectedCode.value = row.symbol || row.code || ''
}

onMounted(() => load())

defineExpose({ load, refresh: () => load() })
</script>

<template>
  <section class="clx-workbench-panel clx-result-panel">
    <header class="clx-panel-head">
      <div>
        <h2>CLX pure-buy 结果</h2>
        <p class="clx-panel-time">
          选股结果时间
          <strong>{{ resultTime }}</strong>
          <template v-if="result?.tradeDate">（{{ result.tradeDate }}）</template>
        </p>
      </div>
      <div class="clx-panel-actions">
        <el-button size="small" :loading="loading" @click="load()">刷新</el-button>
        <el-button
          size="small"
          type="primary"
          :loading="exporting"
          :disabled="!result || rows.length === 0"
          @click="exportToTdx"
        >
          导出当前结果到 CLX_18
        </el-button>
      </div>
    </header>

    <div class="clx-panel-kpis">
      <span>pure-buy <strong>{{ counts.pureBuyTotal }}</strong></span>
      <span>Stock <strong>{{ counts.stock }}</strong></span>
      <span>ETF <strong>{{ counts.etf }}</strong></span>
    </div>

    <div v-if="error" class="clx-panel-error">{{ error }}</div>
    <div v-else-if="status === 'no_ready'" class="clx-panel-empty">
      当日 CLX 尚未发布
    </div>
    <template v-else>
      <el-input
        v-model="search"
        size="small"
        clearable
        placeholder="搜索代码或名称"
      />
      <div class="clx-panel-list" @scroll="loadMore">
        <div v-if="loading && !rows.length" class="clx-panel-empty">加载中...</div>
        <div v-else-if="visibleRows.length === 0" class="clx-panel-empty">
          暂无 pure-buy 结果
        </div>
        <button
          v-for="row in visibleRows"
          :key="`${row.asset_type}-${row.symbol}`"
          type="button"
          class="clx-panel-row"
          :class="{ 'clx-panel-row--selected': selectedCode === row.symbol }"
          @click="selectRow(row)"
        >
          <span class="clx-panel-row__code">{{ row.symbol }}</span>
          <span class="clx-panel-row__name">{{ row.name }}</span>
          <span class="clx-panel-row__type">{{ row.asset_type }}</span>
          <span class="clx-panel-row__models">{{ row.distinct_model_count }}模型</span>
        </button>
        <div v-if="cursor && !loading" class="clx-panel-more">滚动加载更多</div>
        <div v-if="loading && rows.length" class="clx-panel-more">加载中...</div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.clx-workbench-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--fq-border-soft, #ebeef5);
  border-radius: var(--fq-radius-md, 8px);
  background: var(--fq-panel-bg, #fff);
  box-shadow: var(--fq-shadow-sm, 0 1px 2px rgba(15, 23, 42, 0.04));
}

.clx-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--fq-border-soft, #ebeef5);
}

.clx-panel-head h2 {
  margin: 0;
  font-size: 15px;
}

.clx-panel-time {
  margin: 6px 0 0;
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
}

.clx-panel-time strong {
  color: var(--fq-text-primary, #303133);
}

.clx-panel-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.clx-panel-kpis {
  display: flex;
  gap: 8px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--fq-border-soft, #ebeef5);
}

.clx-panel-kpis span {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--fq-chip-bg-muted, #f8fafc);
  color: var(--fq-text-secondary, #606266);
  font-size: 12px;
}

.clx-panel-kpis strong {
  margin-left: 4px;
}

.clx-panel-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 8px 10px;
}

.clx-panel-row {
  display: grid;
  grid-template-columns: 90px minmax(0, 1fr) 48px 56px;
  gap: 8px;
  align-items: center;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--fq-text-primary, #303133);
  text-align: left;
  cursor: pointer;
}

.clx-panel-row + .clx-panel-row {
  margin-top: 4px;
}

.clx-panel-row:hover {
  background: var(--fq-chip-bg-primary, #f4f9ff);
}

.clx-panel-row--selected {
  border-color: var(--fq-status-primary, #409eff);
  background: var(--fq-chip-bg-primary, #f4f9ff);
}

.clx-panel-row__code {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-weight: 600;
}

.clx-panel-row__name {
  overflow: hidden;
  color: var(--fq-text-secondary, #606266);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clx-panel-row__type,
.clx-panel-row__models {
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
  text-align: right;
}

.clx-panel-empty,
.clx-panel-error,
.clx-panel-more {
  padding: 16px 12px;
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
  text-align: center;
}

.clx-panel-error {
  color: var(--fq-status-danger, #dc2626);
}
</style>

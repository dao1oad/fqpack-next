<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  fetchPoolRows,
  syncPoolFromTdx,
  buildSyncSummaryText,
  buildSyncConfirmMessage,
} from './poolWorkspaceLogic.mjs'

const activeTab = ref('pre')
const preRows = ref([])
const stockRows = ref([])
const mustRows = ref([])
const loading = ref(false)
const syncing = ref('')
const lastSyncAt = ref({ stock: '', must: '' })
const syncSummary = ref({ stock: null, must: null })

const tabs = [
  { key: 'pre', label: '预选池' },
  { key: 'stock', label: '监控池' },
  { key: 'must', label: '待买池' },
]

const activeRows = computed(() => {
  if (activeTab.value === 'pre') return preRows.value
  if (activeTab.value === 'stock') return stockRows.value
  return mustRows.value
})

const loadAll = async () => {
  loading.value = true
  try {
    const [pre, stock, must] = await Promise.all([
      fetchPoolRows({ poolKind: 'pre' }),
      fetchPoolRows({ poolKind: 'stock' }),
      fetchPoolRows({ poolKind: 'must' }),
    ])
    preRows.value = pre
    stockRows.value = stock
    mustRows.value = must
  } catch (err) {
    ElMessage.error(err?.message || '池子加载失败')
  } finally {
    loading.value = false
  }
}

const runSync = async (poolKind) => {
  try {
    await ElMessageBox.confirm(
      buildSyncConfirmMessage(poolKind),
      poolKind === 'stock' ? '同步自选股' : '同步待买组',
      {
        confirmButtonText: '继续',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  syncing.value = poolKind
  try {
    const result = await syncPoolFromTdx({ poolKind })
    syncSummary.value[poolKind] = result
    lastSyncAt.value[poolKind] = new Date().toLocaleString('zh-CN', { hour12: false })
    ElMessage.success(buildSyncSummaryText(result))
    await loadAll()
  } catch (err) {
    ElMessage.error(err?.response?.data?.msg || err?.message || '同步失败')
  } finally {
    syncing.value = ''
  }
}

const formatParamState = (row) => {
  if (row.stopLossPrice === null && row.lotAmount === null) return '—'
  const parts = []
  if (row.stopLossPrice !== null) parts.push(`止损 ${row.stopLossPrice}`)
  if (row.lotAmount !== null) parts.push(`金额 ${row.lotAmount}`)
  return parts.join(' / ')
}

onMounted(loadAll)

defineExpose({ loadAll })
</script>

<template>
  <section class="clx-workbench-panel clx-pools-panel">
    <header class="clx-panel-head">
      <div>
        <h2>三池工作区</h2>
        <p class="clx-panel-time">pre 自动落池；stock/must 以通达信分组为唯一来源</p>
      </div>
      <el-button size="small" :loading="loading" @click="loadAll">刷新池子</el-button>
    </header>

    <div class="clx-pool-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="clx-pool-tab"
        :class="{ 'clx-pool-tab--active': activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <div v-if="activeTab === 'stock'" class="clx-pool-sync-bar">
      <el-button
        size="small"
        type="primary"
        :loading="syncing === 'stock'"
        @click="runSync('stock')"
      >
        同步自选股
      </el-button>
      <span v-if="lastSyncAt.stock" class="clx-pool-sync-time">
        上次成功：{{ lastSyncAt.stock }}
      </span>
    </div>
    <div v-else-if="activeTab === 'must'" class="clx-pool-sync-bar">
      <el-button
        size="small"
        type="warning"
        :loading="syncing === 'must'"
        @click="runSync('must')"
      >
        同步待买组
      </el-button>
      <span v-if="lastSyncAt.must" class="clx-pool-sync-time">
        上次成功：{{ lastSyncAt.must }}
      </span>
    </div>
    <div v-else class="clx-pool-sync-bar clx-pool-sync-bar--note">
      <span>预选池由 CLX 正式结果自动生成，只读展示</span>
    </div>

    <div v-if="syncSummary[activeTab]" class="clx-pool-sync-summary">
      {{ buildSyncSummaryText(syncSummary[activeTab]) }}
    </div>

    <div class="clx-panel-list">
      <div v-if="loading && !activeRows.length" class="clx-panel-empty">加载中...</div>
      <div v-else-if="activeRows.length === 0" class="clx-panel-empty">暂无数据</div>
      <div
        v-for="row in activeRows"
        :key="`${activeTab}-${row.code}`"
        class="clx-pool-row"
      >
        <span class="clx-pool-row__code">{{ row.code }}</span>
        <span class="clx-pool-row__name">{{ row.name }}</span>
        <span v-if="activeTab === 'pre'" class="clx-pool-row__type">
          {{ row.assetType || 'stock' }}
        </span>
        <span v-else class="clx-pool-row__params">{{ formatParamState(row) }}</span>
      </div>
    </div>
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

.clx-pool-tabs {
  display: flex;
  gap: 4px;
  padding: 8px 10px 0;
}

.clx-pool-tab {
  flex: 1 1 0;
  padding: 8px 0;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--fq-text-secondary, #606266);
  font-size: 13px;
  cursor: pointer;
}

.clx-pool-tab--active {
  border-color: var(--fq-border-soft, #ebeef5);
  background: var(--fq-panel-bg-muted, #f8fafc);
  color: var(--fq-status-primary, #409eff);
  font-weight: 600;
}

.clx-pool-sync-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
}

.clx-pool-sync-bar--note {
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
}

.clx-pool-sync-time {
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
}

.clx-pool-sync-summary {
  margin: 0 10px 8px;
  padding: 8px 10px;
  border: 1px solid var(--fq-chip-border-success, #d1fae5);
  border-radius: 6px;
  background: var(--fq-chip-bg-success, #f0fdf4);
  color: var(--fq-text-secondary, #606266);
  font-size: 12px;
}

.clx-panel-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 4px 10px 10px;
}

.clx-pool-row {
  display: grid;
  grid-template-columns: 84px minmax(0, 1fr) minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  padding: 8px 10px;
  border-bottom: 1px solid var(--fq-border-soft, #ebeef5);
  font-size: 12px;
}

.clx-pool-row__code {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-weight: 600;
}

.clx-pool-row__name {
  overflow: hidden;
  color: var(--fq-text-secondary, #606266);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clx-pool-row__type,
.clx-pool-row__params {
  color: var(--fq-text-muted, #909399);
  text-align: right;
}

.clx-panel-empty {
  padding: 16px 12px;
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
  text-align: center;
}
</style>

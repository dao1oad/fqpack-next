<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import MyHeader from './MyHeader.vue'
import WorkbenchPage from '../components/workbench/WorkbenchPage.vue'
import StatusChip from '../components/workbench/StatusChip.vue'
import ClxFundamentalRankingPanel from '../components/clx-workbench/ClxFundamentalRankingPanel.vue'
import ClxFundamentalDetailPanel from '../components/clx-workbench/ClxFundamentalDetailPanel.vue'
import ClxFundamentalStatsPanel from '../components/clx-workbench/ClxFundamentalStatsPanel.vue'

const selection = reactive({
  resultTime: '',
  tradeDate: '',
  batchId: '',
})

const evaluation = reactive({
  generatedAt: '',
  tradeDate: '',
  evaluatedBatchId: '',
})

const preStatus = ref({
  status: '',
  tradeDate: '',
  batchId: '',
  generationId: '',
})

const rankingPanel = ref(null)
const detailPanel = ref(null)
const statsPanel = ref(null)
const selectedRow = ref(null)
const industryFilter = ref([])
const filterVersion = ref(0)
const gateStatus = ref('passed')
const gateDetail = ref('')
const statsSummary = ref(null)

const route = useRoute()
const router = useRouter()

const legacyTradeDate = computed(() => {
  const value = route.query.trade_date || route.query.tradeDate || ''
  return String(value || '').trim()
})

const refreshAll = () => {
  rankingPanel.value?.refresh?.()
  detailPanel.value?.refresh?.()
  statsPanel.value?.refresh?.()
}

const onSelect = (row) => {
  selectedRow.value = row
}

const onCloseDetail = () => {
  selectedRow.value = null
}

const onIndustryFilter = (industries) => {
  industryFilter.value = industries
  filterVersion.value += 1
}

const onSymbolSearch = (symbol) => {
  const query = { ...route.query, q: symbol }
  router.replace({ query }).catch(() => {})
}

const onStatsReady = (stats) => {
  gateStatus.value = stats?.qualityGateStatus || 'passed'
  statsSummary.value = stats?.summary || null
  const gates = stats?.qualityGates || {}
  const failed = Object.entries(gates)
    .filter(([key, gate]) => key !== 'rerunConsistency' && gate?.passed === false)
    .map(([key, gate]) => `${key}:${gate?.detail || gate?.value}`)
  gateDetail.value = failed.join('；')
}

const preStatusLabel = () => {
  const status = preStatus.value.status
  if (!status) return 'CLX 状态未知'
  if (status === 'no_ready') return '当日 CLX 尚未发布'
  if (status === 'error') return 'CLX 加载失败'
  if (status === 'ready') return '基本面排序已就绪'
  return 'CLX 同步中'
}

const amberBannerVisible = computed(() => gateStatus.value === 'amber')
</script>

<template>
  <WorkbenchPage class="clx-workbench-page">
    <MyHeader />
    <div class="workbench-body clx-workbench-body">
      <header class="clx-workbench-topbar">
        <div class="clx-workbench-topbar__title">
          <div class="workbench-page-title">每日选股工作台</div>
          <div class="workbench-page-meta">
            <span>排序结果时间 <strong>{{ selection.resultTime || '—' }}</strong></span>
            <span>交易日 <strong>{{ selection.tradeDate || evaluation.tradeDate || '—' }}</strong></span>
            <span>批次 <strong>{{ selection.batchId || '—' }}</strong></span>
          </div>
        </div>
        <div class="clx-workbench-topbar__actions">
          <StatusChip variant="info">{{ preStatusLabel() }}</StatusChip>
          <StatusChip :variant="gateStatus === 'passed' ? 'success' : 'warning'">
            质量门：{{ gateStatus === 'passed' ? '通过' : '琥珀' }}
          </StatusChip>
          <el-button size="small" @click="refreshAll">刷新全部</el-button>
        </div>
      </header>

      <div v-if="amberBannerVisible" class="clx-workbench-amber">
        ⚠ 批次质量门未全部通过：{{ gateDetail || '请查看统计面板质量门明细' }}
      </div>

      <div class="clx-workbench-grid">
        <ClxFundamentalRankingPanel
          ref="rankingPanel"
          class="clx-workbench-grid__ranking"
          :trade-date="legacyTradeDate"
          :industry-filter="industryFilter"
          :filter-version="filterVersion"
          @select="onSelect"
          @selection-time="Object.assign(selection, $event)"
          @pre-status="preStatus = $event"
        />
        <ClxFundamentalDetailPanel
          ref="detailPanel"
          class="clx-workbench-grid__detail"
          :row="selectedRow"
          @close="onCloseDetail"
        />
        <ClxFundamentalStatsPanel
          ref="statsPanel"
          class="clx-workbench-grid__stats"
          @industry-filter="onIndustryFilter"
          @symbol-search="onSymbolSearch"
          @stats-ready="onStatsReady"
        />
      </div>

      <footer class="clx-workbench-statusbar">
        <span>深析 <strong>{{ statsSummary?.deep ?? '—' }}</strong></span>
        <span>初评 <strong>{{ statsSummary?.snapshot ?? '—' }}</strong></span>
        <span>深析完成 <strong>{{ statsSummary?.deepComplete ?? '—' }}</strong></span>
        <span>证据 A+B <strong>{{ statsSummary?.evidenceABShare != null
          ? `${(statsSummary.evidenceABShare * 100).toFixed(0)}%` : '—' }}</strong></span>
        <span>质量门 <strong>{{ gateStatus === 'passed' ? '通过' : '琥珀' }}</strong></span>
        <span>生成时间 <strong>{{ selection.resultTime || '—' }}</strong></span>
      </footer>
    </div>
  </WorkbenchPage>
</template>

<style scoped>
.clx-workbench-page {
  height: 100dvh;
  overflow: hidden;
}

.clx-workbench-body {
  overflow: hidden;
  padding: 12px 16px 16px;
}

.clx-workbench-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex: 0 0 auto;
  margin-bottom: 8px;
}

.clx-workbench-topbar__title {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.workbench-page-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
}

.workbench-page-meta strong {
  color: var(--fq-text-primary, #303133);
}

.clx-workbench-topbar__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
}

.clx-workbench-amber {
  flex: 0 0 auto;
  margin-bottom: 8px;
  padding: 6px 12px;
  border: 1px solid var(--fq-chip-border-warning, #fde68a);
  border-radius: 6px;
  background: var(--fq-chip-bg-warning, #fef3c7);
  color: var(--fq-status-warning, #d97706);
  font-size: 12px;
}

.clx-workbench-grid {
  display: grid;
  flex: 1 1 auto;
  grid-template-columns:
    minmax(460px, 40fr)
    minmax(500px, 38fr)
    minmax(300px, 22fr);
  gap: 12px;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}

.clx-workbench-grid__ranking,
.clx-workbench-grid__detail,
.clx-workbench-grid__stats {
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}

.clx-workbench-statusbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  flex: 0 0 auto;
  margin-top: 8px;
  padding: 4px 10px;
  border: 1px solid var(--fq-border-soft, #ebeef5);
  border-radius: 6px;
  background: var(--fq-panel-bg-muted, #f8fafc);
  color: var(--fq-text-muted, #909399);
  font-size: 11px;
}

.clx-workbench-statusbar strong {
  color: var(--fq-text-secondary, #606266);
}

@media (max-width: 1280px) {
  .clx-workbench-grid {
    grid-template-columns:
      minmax(460px, 44fr)
      minmax(500px, 56fr);
    grid-template-rows: minmax(0, 1fr) minmax(220px, 0.42fr);
  }

  .clx-workbench-grid__stats {
    grid-column: 1 / -1;
    grid-row: 2;
  }
}

@media (max-width: 960px) {
  .clx-workbench-grid {
    display: block;
  }

  .clx-workbench-grid__ranking {
    height: 100%;
  }

  .clx-workbench-grid__stats {
    display: none;
  }

  .clx-workbench-grid__detail {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: 900;
    width: min(420px, 92vw);
    border-left: 1px solid var(--fq-border-soft, #ebeef5);
    box-shadow: -8px 0 24px rgba(15, 23, 42, 0.12);
  }
}
</style>

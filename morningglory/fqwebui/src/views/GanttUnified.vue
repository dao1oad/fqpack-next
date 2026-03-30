<template>
  <WorkbenchPage class="gantt-page">
    <MyHeader />

    <div class="workbench-body gantt-page-body">
      <WorkbenchToolbar class="gantt-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">板块趋势</div>
            <div class="workbench-page-meta">
              <span>板块热点时间窗</span>
              <span>/</span>
              <span>支持 provider 切换与 drill-down</span>
            </div>
          </div>

          <div class="workbench-toolbar__actions">
            <el-radio-group v-model="activeProvider" size="small" class="gantt-provider-switch">
              <el-radio-button value="xgb">选股通</el-radio-button>
              <el-radio-button value="jygs">韭研公社</el-radio-button>
            </el-radio-group>
          </div>
        </div>

        <WorkbenchSummaryRow class="gantt-summary-row">
          <StatusChip variant="info">
            provider <strong>{{ activeProviderLabel }}</strong>
          </StatusChip>
          <StatusChip variant="muted">
            时间窗 <strong>{{ windowDays }} 日</strong>
          </StatusChip>
        </WorkbenchSummaryRow>
      </WorkbenchToolbar>

      <el-alert
        class="workbench-alert gantt-page-alert"
        type="info"
        :closable="false"
        title="支持 provider 切换与 drill-down；主区保留原有趋势时间窗工作流。"
        show-icon
      />

      <WorkbenchLedgerPanel class="gantt-history-panel">
        <div class="workbench-panel__header">
          <div class="workbench-panel__title">板块趋势时间窗</div>
        </div>

        <div class="gantt-page-content">
          <GanttHistory
            mode="plates"
            :provider="activeProvider"
            :window-days="windowDays"
            title="板块趋势"
            @update:window-days="handleWindowDaysChange"
            @drill-down="handleDrillDown"
          />
        </div>
      </WorkbenchLedgerPanel>
    </div>
  </WorkbenchPage>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import StatusChip from '@/components/workbench/StatusChip.vue'
import WorkbenchLedgerPanel from '@/components/workbench/WorkbenchLedgerPanel.vue'
import WorkbenchPage from '@/components/workbench/WorkbenchPage.vue'
import WorkbenchSummaryRow from '@/components/workbench/WorkbenchSummaryRow.vue'
import WorkbenchToolbar from '@/components/workbench/WorkbenchToolbar.vue'
import MyHeader from './MyHeader.vue'
import GanttHistory from './components/GanttHistory.vue'

const route = useRoute()
const router = useRouter()
const PROVIDER_LABELS = {
  xgb: '选股通',
  jygs: '韭研公社',
}

const normalizeProvider = (value) => {
  return String(value || '').trim() === 'jygs' ? 'jygs' : 'xgb'
}

const normalizeDays = (value, fallback = 30) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback
  return Math.min(90, Math.max(1, Math.floor(parsed)))
}

const activeProvider = ref(normalizeProvider(route.query.p))
const windowDays = ref(normalizeDays(route.query.days))
const activeProviderLabel = computed(() => PROVIDER_LABELS[activeProvider.value] || '选股通')

watch(
  () => route.query.p,
  (value) => {
    const next = normalizeProvider(value)
    if (next !== activeProvider.value) activeProvider.value = next
  },
)

watch(
  () => route.query.days,
  (value) => {
    const next = normalizeDays(value, windowDays.value)
    if (next !== windowDays.value) windowDays.value = next
  },
)

watch(activeProvider, (value) => {
  if (normalizeProvider(route.query.p) === value) return
  router.replace({
    name: 'gantt',
    query: {
      ...(route.query || {}),
      p: value,
      days: String(windowDays.value),
    },
  }).catch(() => {})
})

watch(windowDays, (value) => {
  if (normalizeDays(route.query.days, value) === value) return
  router.replace({
    name: 'gantt',
    query: {
      ...(route.query || {}),
      p: activeProvider.value,
      days: String(value),
    },
  }).catch(() => {})
})

const handleWindowDaysChange = (value) => {
  windowDays.value = normalizeDays(value, windowDays.value)
}

const handleDrillDown = ({ plateKey, plateName, days }) => {
  const targetPlateKey = String(plateKey || '').trim()
  if (!targetPlateKey) return
  const nextDays = normalizeDays(days, windowDays.value)
  router.push({
    name: 'gantt-stocks',
    params: { plateKey: targetPlateKey },
    query: {
      p: activeProvider.value,
      days: String(nextDays),
      plate_name: String(plateName || '').trim(),
    },
  }).catch(() => {})
}
</script>

<style scoped>
.gantt-page-body {
  padding-top: 12px;
  gap: 12px;
}

.gantt-toolbar {
  flex: 0 0 auto;
}

.gantt-summary-row {
  margin-top: 12px;
}

.gantt-page-alert {
  flex: 0 0 auto;
}

.gantt-provider-switch {
  flex: 0 0 auto;
}

.gantt-history-panel {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.gantt-page-content {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}
</style>

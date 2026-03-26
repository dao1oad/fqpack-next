<template>
  <WorkbenchPage class="gantt-page">
    <MyHeader />

    <div class="workbench-body gantt-page-body">
      <WorkbenchToolbar class="gantt-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">板块趋势 / 个股</div>
            <div class="workbench-page-meta">
              <span>板块内个股回看</span>
              <span>/</span>
              <span>{{ plateName || plateKey || '未选板块' }}</span>
            </div>
          </div>

          <div class="workbench-toolbar__actions">
            <el-radio-group v-model="activeProvider" size="small" class="gantt-provider-switch">
              <el-radio-button value="xgb">选股通</el-radio-button>
              <el-radio-button value="jygs">韭研公社</el-radio-button>
            </el-radio-group>
          </div>
        </div>
      </WorkbenchToolbar>

      <div class="gantt-page-content">
        <GanttHistory
          mode="stocks"
          :provider="activeProvider"
          :plate-key="plateKey"
          :plate-name="plateName"
          :window-days="windowDays"
          title="板块趋势"
          @update:window-days="handleWindowDaysChange"
          @back="handleBack"
        />
      </div>
    </div>
  </WorkbenchPage>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import WorkbenchPage from '@/components/workbench/WorkbenchPage.vue'
import WorkbenchToolbar from '@/components/workbench/WorkbenchToolbar.vue'
import MyHeader from './MyHeader.vue'
import GanttHistory from './components/GanttHistory.vue'

const route = useRoute()
const router = useRouter()

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

const plateKey = computed(() => {
  return String(route.params.plateKey || '').trim()
})

const plateName = computed(() => {
  return String(route.query.plate_name || '').trim()
})

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

const navigateBackToPlates = (provider = activeProvider.value) => {
  router.push({
    name: 'gantt',
    query: {
      p: normalizeProvider(provider),
      days: String(windowDays.value),
    },
  }).catch(() => {})
}

watch(activeProvider, (value) => {
  if (normalizeProvider(route.query.p) === value) return
  navigateBackToPlates(value)
})

watch(windowDays, (value) => {
  if (normalizeDays(route.query.days, value) === value) return
  router.replace({
    name: 'gantt-stocks',
    params: { plateKey: plateKey.value },
    query: {
      ...(route.query || {}),
      p: activeProvider.value,
      days: String(value),
      plate_name: plateName.value,
    },
  }).catch(() => {})
})

const handleWindowDaysChange = (value) => {
  windowDays.value = normalizeDays(value, windowDays.value)
}

const handleBack = () => {
  navigateBackToPlates(activeProvider.value)
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

.gantt-provider-switch {
  flex: 0 0 auto;
}

.gantt-page-content {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}
</style>

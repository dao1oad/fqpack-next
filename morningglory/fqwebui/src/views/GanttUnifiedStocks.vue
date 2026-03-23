<template>
  <div class="gantt-page">
    <MyHeader />
    <div class="gantt-page-body">
      <div class="gantt-tabs">
        <el-tabs v-model="activeProvider" @tab-change="handleProviderChange">
          <el-tab-pane label="选股通" name="xgb" />
          <el-tab-pane label="韭研公社" name="jygs" />
        </el-tabs>
      </div>

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
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
  }
)

watch(
  () => route.query.days,
  (value) => {
    const next = normalizeDays(value, windowDays.value)
    if (next !== windowDays.value) windowDays.value = next
  }
)

const navigateBackToPlates = (provider = activeProvider.value) => {
  router.push({
    name: 'gantt',
    query: {
      p: normalizeProvider(provider),
      days: String(windowDays.value)
    }
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
      plate_name: plateName.value
    }
  }).catch(() => {})
})

const handleProviderChange = (value) => {
  activeProvider.value = normalizeProvider(value)
}

const handleWindowDaysChange = (value) => {
  windowDays.value = normalizeDays(value, windowDays.value)
}

const handleBack = () => {
  navigateBackToPlates(activeProvider.value)
}
</script>

<style scoped>
.gantt-page {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  min-height: 100dvh;
  background: #f5f7fa;
}

.gantt-page-body {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}

.gantt-tabs {
  flex: 0 0 auto;
  padding: 8px 16px 0;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}

.gantt-page-content {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}
</style>

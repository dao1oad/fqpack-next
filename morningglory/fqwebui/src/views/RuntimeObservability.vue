<template>
  <div class="runtime-page">
    <MyHeader />
    <div class="runtime-shell">
      <section class="runtime-section">
        <div class="runtime-title-row">
          <div>
            <h1>运行观测</h1>
            <p>链路追踪优先，健康看板同步提供。</p>
          </div>
          <el-button type="primary" :loading="loading.overview" @click="loadOverview">刷新</el-button>
        </div>
        <div class="health-grid">
          <article v-for="card in healthCards" :key="`${card.runtime_node}-${card.component}`" class="health-card">
            <div class="health-card-head">
              <strong>{{ card.component }}</strong>
              <span>{{ card.runtime_node }}</span>
            </div>
            <div class="health-card-body">
              <p>状态: {{ card.status }}</p>
              <p>心跳年龄: {{ card.heartbeat_age_s ?? '-' }}s</p>
              <ul>
                <li v-for="item in card.highlights" :key="item.key">{{ item.key }}: {{ item.value }}</li>
              </ul>
            </div>
          </article>
        </div>
      </section>

      <section class="runtime-section">
        <div class="trace-toolbar">
          <el-input v-model="query.trace_id" clearable placeholder="trace_id" />
          <el-input v-model="query.request_id" clearable placeholder="request_id" />
          <el-input v-model="query.internal_order_id" clearable placeholder="internal_order_id" />
          <el-input v-model="query.symbol" clearable placeholder="symbol" />
          <el-input v-model="query.component" clearable placeholder="component" />
          <el-button type="primary" :loading="loading.traces" @click="loadTraces">查询</el-button>
        </div>

        <div class="trace-layout">
          <div class="trace-list">
            <el-table :data="traceRows" stripe height="460" @row-click="handleTraceClick">
              <el-table-column prop="trace_id" label="Trace" min-width="180" />
              <el-table-column prop="request_ids" label="Request" min-width="160">
                <template #default="{ row }">{{ row.request_ids.join(', ') || '-' }}</template>
              </el-table-column>
              <el-table-column prop="internal_order_ids" label="Order" min-width="160">
                <template #default="{ row }">{{ row.internal_order_ids.join(', ') || '-' }}</template>
              </el-table-column>
              <el-table-column prop="step_count" label="Steps" width="80" />
              <el-table-column prop="last_node" label="Last Node" min-width="140" />
              <el-table-column prop="last_status" label="Status" width="100" />
              <el-table-column prop="last_ts" label="Latest" min-width="180" />
            </el-table>
          </div>

          <div class="trace-detail">
            <div class="trace-detail-head">
              <strong>{{ selectedTrace?.trace_id || '选择一条 Trace' }}</strong>
              <el-button :disabled="!selectedTrace" @click="openRawBrowser">Raw</el-button>
            </div>
            <div v-if="selectedTrace" class="trace-step-list">
              <article v-for="(step, index) in selectedTrace.steps" :key="`${step.ts}-${index}`" class="trace-step-card">
                <header>
                  <strong>{{ step.component }}.{{ step.node }}</strong>
                  <span>{{ step.status || 'info' }}</span>
                </header>
                <p>{{ step.ts }}</p>
                <p v-if="step.reason_code">reason: {{ step.reason_code }}</p>
                <p v-if="step.request_id">request: {{ step.request_id }}</p>
                <p v-if="step.internal_order_id">order: {{ step.internal_order_id }}</p>
                <el-button text type="primary" @click="openRawFromStep(step)">查看 Raw</el-button>
              </article>
            </div>
            <div v-else class="trace-empty">暂无选中链路</div>
          </div>
        </div>
      </section>
    </div>

    <el-drawer v-model="rawDrawerVisible" size="55%" title="Raw Records">
      <div class="raw-toolbar">
        <el-input v-model="rawQuery.runtime_node" placeholder="runtime_node" />
        <el-input v-model="rawQuery.component" placeholder="component" />
        <el-input v-model="rawQuery.date" placeholder="YYYY-MM-DD" />
        <el-select v-model="rawQuery.file" placeholder="选择文件" filterable clearable style="width: 280px">
          <el-option v-for="item in rawFiles" :key="item.name" :label="item.name" :value="item.name" />
        </el-select>
        <el-button @click="loadRawFiles">文件</el-button>
        <el-button type="primary" :disabled="!rawQuery.file" @click="loadRawTail">Tail</el-button>
      </div>
      <pre class="raw-content">{{ rawContent }}</pre>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

import { runtimeObservabilityApi } from '../api/runtimeObservabilityApi'
import MyHeader from './MyHeader.vue'
import {
  buildHealthCards,
  buildRawLookupFromStep,
  buildTraceQuery,
  sortTraceSummaries,
  summarizeTrace,
} from './runtimeObservability.mjs'

const loading = reactive({
  overview: false,
  traces: false,
  raw: false,
})

const query = reactive({
  trace_id: '',
  request_id: '',
  internal_order_id: '',
  symbol: '',
  component: '',
})

const healthCards = ref([])
const traces = ref([])
const selectedTrace = ref(null)
const rawDrawerVisible = ref(false)
const rawFiles = ref([])
const rawRecords = ref([])
const rawQuery = reactive({
  runtime_node: '',
  component: '',
  date: '',
  file: '',
})

const traceRows = computed(() => {
  return sortTraceSummaries(traces.value.map((item) => summarizeTrace(item)))
})

const rawContent = computed(() => {
  if (!rawRecords.value.length) return '暂无记录'
  return JSON.stringify(rawRecords.value, null, 2)
})

const loadOverview = async () => {
  loading.overview = true
  try {
    const [healthResp] = await Promise.all([
      runtimeObservabilityApi.getHealthSummary(),
      loadTraces(),
    ])
    healthCards.value = buildHealthCards(healthResp?.data?.components || [])
  } finally {
    loading.overview = false
  }
}

const loadTraces = async () => {
  loading.traces = true
  try {
    const response = await runtimeObservabilityApi.listTraces(buildTraceQuery(query))
    traces.value = response?.data?.traces || []
    if (!selectedTrace.value && traces.value.length > 0) {
      selectedTrace.value = traces.value[0]
    }
  } finally {
    loading.traces = false
  }
}

const handleTraceClick = async (row) => {
  if (!row?.trace_id) {
    selectedTrace.value = traces.value.find((item) => summarizeTrace(item).trace_id === row?.trace_id) || null
    return
  }
  const response = await runtimeObservabilityApi.getTraceDetail(row.trace_id)
  selectedTrace.value = response?.data?.trace || null
}

const openRawBrowser = () => {
  rawDrawerVisible.value = true
}

const openRawFromStep = async (step) => {
  const lookup = buildRawLookupFromStep(step)
  if (!lookup) return
  rawQuery.runtime_node = lookup.runtime_node
  rawQuery.component = lookup.component
  rawQuery.date = lookup.date
  rawQuery.file = ''
  rawDrawerVisible.value = true
  await loadRawFiles()
  if (rawFiles.value.length > 0) {
    rawQuery.file = rawFiles.value[0].name
    await loadRawTail()
  }
}

const loadRawFiles = async () => {
  loading.raw = true
  try {
    const response = await runtimeObservabilityApi.listRawFiles({
      runtime_node: rawQuery.runtime_node,
      component: rawQuery.component,
      date: rawQuery.date,
    })
    rawFiles.value = response?.data?.files || []
  } finally {
    loading.raw = false
  }
}

const loadRawTail = async () => {
  if (!rawQuery.file) return
  loading.raw = true
  try {
    const response = await runtimeObservabilityApi.tailRawFile({
      runtime_node: rawQuery.runtime_node,
      component: rawQuery.component,
      date: rawQuery.date,
      file: rawQuery.file,
      lines: 120,
    })
    rawRecords.value = response?.data?.records || []
  } finally {
    loading.raw = false
  }
}

onMounted(() => {
  loadOverview()
})
</script>

<style scoped>
.runtime-page {
  min-height: 100vh;
  background:
    linear-gradient(180deg, #eef4ff 0%, #f9fbff 38%, #f5f7fa 100%);
}

.runtime-shell {
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.runtime-section {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #dfe7f3;
  border-radius: 18px;
  padding: 18px;
  box-shadow: 0 12px 36px rgba(20, 48, 84, 0.06);
}

.runtime-title-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 14px;
}

.runtime-title-row h1 {
  margin: 0;
  font-size: 26px;
  color: #17324d;
}

.runtime-title-row p {
  margin: 6px 0 0;
  color: #56718d;
}

.health-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}

.health-card {
  border-radius: 14px;
  padding: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f4f8fc 100%);
  border: 1px solid #dbe5ef;
}

.health-card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  color: #1f3c5b;
}

.health-card-head span {
  color: #6a8198;
  font-size: 12px;
}

.health-card-body p,
.health-card-body li {
  margin: 6px 0;
  color: #39546f;
}

.health-card-body ul {
  padding-left: 16px;
  margin: 0;
}

.trace-toolbar {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr)) auto;
  gap: 10px;
  margin-bottom: 14px;
}

.trace-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.9fr);
  gap: 16px;
}

.trace-list,
.trace-detail {
  min-width: 0;
}

.trace-detail {
  border: 1px solid #dfe7f3;
  border-radius: 14px;
  background: linear-gradient(180deg, #fbfdff 0%, #f4f8fc 100%);
  padding: 14px;
}

.trace-detail-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.trace-step-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 460px;
  overflow: auto;
}

.trace-step-card {
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  padding: 12px;
  background: #fff;
}

.trace-step-card header {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.trace-step-card p {
  margin: 4px 0;
  color: #46607a;
}

.trace-empty {
  min-height: 200px;
  display: grid;
  place-items: center;
  color: #6a8198;
}

.raw-toolbar {
  display: grid;
  grid-template-columns: 1fr 1fr 160px 280px auto auto;
  gap: 10px;
  margin-bottom: 14px;
}

.raw-content {
  margin: 0;
  min-height: 320px;
  max-height: 70vh;
  overflow: auto;
  padding: 16px;
  border-radius: 12px;
  background: #102033;
  color: #dff0ff;
  font-size: 12px;
  line-height: 1.55;
}

@media (max-width: 1080px) {
  .trace-toolbar,
  .raw-toolbar,
  .trace-layout {
    grid-template-columns: 1fr;
  }
}
</style>
